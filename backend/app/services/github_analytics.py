"""GitHub analytics for the GitHub page.

Reads are deliberately built on what the service token can actually reach. The
``cms-cloud-devops-automation`` account holds enterprise owner rights, but the
PAT configured here carries only the ``repo`` scope, so enterprise, Copilot,
billing and security-alert endpoints return 404 or 403. ``capabilities()``
probes the token and reports which areas are unlocked, and the page renders a
"needs scope" panel instead of an error for the rest.

The open-PR board comes from GraphQL rather than REST: ``reviewDecision`` is the
one field that makes the board useful, and REST needs a call per pull request
(152 of them org-wide). A trimmed GraphQL query returns 50 per page at a cost of
1, where asking for 100 plus labels and review counts times out with a 502.
"""
from __future__ import annotations

import asyncio
import calendar
import json
import logging
import math
import time
from datetime import date, datetime, timedelta, timezone

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

_API = "https://api.github.com"
_CACHE_TTL = 300
_STALE_DAYS = 30

# Repos this team owns. The org has 100+ repos belonging to other CMS teams, so
# the board defaults to these and offers org-wide as an explicit choice.
TEAM_REPOS = [
    "cmscloud-devops",
    "devops-dashboard",
    "dso-cjoc-casc",
    "dso-contrl-casc",
    "cms-cloud-devops-observability",
]

_cache: dict[str, tuple[float, dict]] = {}


def _cached(key: str, ttl: float = _CACHE_TTL) -> dict | None:
    hit = _cache.get(key)
    if hit and (time.time() - hit[0]) < ttl:
        return hit[1]
    return None


def _store(key: str, value: dict) -> dict:
    _cache[key] = (time.time(), value)
    return value


def invalidate() -> None:
    _cache.clear()


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {get_settings().GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _has_billing_token() -> bool:
    settings = get_settings()
    return bool(settings.GITHUB_BILLING_TOKEN or settings.GITHUB_TOKEN)


def _billing_headers() -> dict:
    """Headers for enterprise/Copilot/billing reads, which need admin:enterprise.

    Uses GITHUB_BILLING_TOKEN when a deployment splits that credential out,
    falling back to GITHUB_TOKEN. The cluster PAT holds admin:enterprise
    itself, so the fallback is the live path, not a degraded one.
    """
    settings = get_settings()
    token = settings.GITHUB_BILLING_TOKEN or settings.GITHUB_TOKEN
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _age_days(iso: str) -> int:
    try:
        then = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - then).days
    except Exception:  # noqa: BLE001
        return 0


# ─── Capabilities ─────────────────────────────────────────────────────────────

# Feature area -> (probe path, scopes that unlock it). Enterprise paths are used
# wherever they exist, because the enterprise scope reaches them while the
# org-level equivalents additionally want read:org or security_events.
_PROBES = {
    "repos": ("/orgs/{org}/repos?per_page=1", ["repo"]),
    "members": ("/orgs/{org}/members?per_page=1", ["repo", "read:org"]),
    "copilot_seats": ("/enterprises/{ent}/copilot/billing/seats?per_page=1", ["copilot", "admin:enterprise"]),
    "enterprise_audit_log": ("/enterprises/{ent}/audit-log?per_page=1", ["audit_log", "admin:enterprise"]),
    "consumed_licenses": ("/enterprises/{ent}/consumed-licenses", ["admin:enterprise"]),
    "cost_centers": ("/enterprises/{ent}/settings/billing/cost-centers", ["admin:enterprise"]),
    "dependabot_alerts": ("/enterprises/{ent}/dependabot/alerts?per_page=1", ["admin:enterprise", "security_events"]),
    "secret_scanning": ("/enterprises/{ent}/secret-scanning/alerts?per_page=1", ["admin:enterprise", "security_events"]),
    # The org billing endpoint needs org-owner rights the service account does not
    # have, and the old enterprise one now returns 410. The enhanced billing API
    # is the live path and works on the enterprise scope alone.
    "billing_usage": ("/enterprises/{ent}/settings/billing/usage", ["admin:enterprise"]),
}

# These need admin:enterprise, so they go through _billing_headers and pick up
# GITHUB_BILLING_TOKEN where it is split out. repos/members never need it.
_BILLING_AREAS = {
    "copilot_seats", "enterprise_audit_log", "consumed_licenses",
    "cost_centers", "dependabot_alerts", "secret_scanning", "billing_usage",
}


async def capabilities() -> dict:
    """Probe the token: identity, granted scopes, and which areas are reachable."""
    cached = _cached("capabilities")
    if cached:
        return cached

    settings = get_settings()
    org = settings.GITHUB_ORG
    ent = settings.GITHUB_ENTERPRISE_SLUG
    if not settings.GITHUB_TOKEN:
        return {"configured": False, "error": "GITHUB_TOKEN is not configured"}

    async with httpx.AsyncClient(timeout=30, headers=_headers()) as client, \
               httpx.AsyncClient(timeout=30, headers=_billing_headers()) as billing_client:
        try:
            who = await client.get(f"{_API}/user")
        except Exception as exc:  # noqa: BLE001
            return {"configured": True, "error": f"Could not reach GitHub: {exc}"}

        if who.status_code != 200:
            return {"configured": True, "error": f"GitHub returned {who.status_code} for /user"}

        login = who.json().get("login")
        scopes = [s.strip() for s in (who.headers.get("x-oauth-scopes") or "").split(",") if s.strip()]

        async def check(name: str, path: str) -> int:
            c = billing_client if name in _BILLING_AREAS else client
            try:
                r = await c.get(_API + path.format(org=org, ent=ent))
                return r.status_code
            except Exception:  # noqa: BLE001
                return 0

        results = await asyncio.gather(*[check(name, p) for name, (p, _) in _PROBES.items()])

        # read:enterprise is the gate for every enterprise-level read.
        ent_resp = await billing_client.post(
            f"{_API}/graphql",
            json={"query": "{ viewer { enterprises(first:5){nodes{slug name}} } }"},
        )
        ent_json = ent_resp.json() if ent_resp.content else {}
        ent_nodes = (((ent_json.get("data") or {}).get("viewer") or {})
                     .get("enterprises") or {}).get("nodes") or []
        ent_ok = bool(ent_nodes)

        # Several org endpoints need owner rights, which a scope cannot grant.
        try:
            mem = await client.get(f"{_API}/orgs/{org}/memberships/{login}")
            org_role = mem.json().get("role") if mem.status_code == 200 else None
        except Exception:  # noqa: BLE001
            org_role = None

    areas = {}
    for (name, (_, scopes_needed)), code in zip(_PROBES.items(), results):
        areas[name] = {
            "available": code == 200,
            "status": code,
            "scopes_needed": scopes_needed,
        }
    areas["enterprise"] = {
        "available": ent_ok,
        "status": 200 if ent_ok else 403,
        "scopes_needed": ["read:enterprise"],
        "enterprises": [n.get("slug") for n in ent_nodes],
    }

    # A PAT that is not SSO-authorized for the org fails every private-repo read
    # with a 403 that names no scope, so detect it explicitly and carry the
    # authorization URL rather than letting it look like a missing permission.
    sso = {"required": False, "authorization_url": ""}
    repo_name = settings.GITHUB_DEFAULT_REPO or "cmscloud-devops"
    async with httpx.AsyncClient(timeout=30, headers=_headers()) as client:
        probe = await client.get(f"{_API}/repos/{org}/{repo_name}")
        if probe.status_code == 403:
            header = probe.headers.get("x-github-sso", "")
            if "required" in header:
                sso = {
                    "required": True,
                    "authorization_url": header.split("url=", 1)[-1].strip() if "url=" in header else "",
                }

        # TEAM_REPOS the token cannot see drop out of the board silently, so
        # report them instead.
        async def visible(name: str) -> tuple[str, bool]:
            try:
                r = await client.get(f"{_API}/repos/{org}/{name}")
                return name, r.status_code == 200
            except Exception:  # noqa: BLE001
                return name, False

        checked = await asyncio.gather(*[visible(r) for r in TEAM_REPOS])
    unreadable_team_repos = sorted(n for n, ok in checked if not ok)

    locked = sorted(k for k, v in areas.items() if not v["available"])
    missing: list[str] = []
    for k in locked:
        for sc in areas[k]["scopes_needed"]:
            if sc not in scopes and sc not in missing:
                missing.append(sc)

    return _store("capabilities", {
        "configured": True,
        "login": login,
        "scopes": scopes,
        "org": org,
        "enterprise": ent,
        "areas": areas,
        "locked": locked,
        "missing_scopes": missing,
        "sso": sso,
        "unreadable_team_repos": unreadable_team_repos,
        "org_role": org_role,
        "error": None,
    })


# ─── Open pull requests ───────────────────────────────────────────────────────

_PR_QUERY = """
query($q: String!, $n: Int!, $after: String) {
  search(query: $q, type: ISSUE, first: $n, after: $after) {
    issueCount
    pageInfo { hasNextPage endCursor }
    nodes { ... on PullRequest {
      number title isDraft createdAt updatedAt url
      author { login __typename }
      repository { name }
      reviewDecision
    } }
  }
}
"""

_PR_PAGE = 50
_PR_MAX_PAGES = 6


def _bucket(pr: dict) -> str:
    if pr["draft"]:
        return "draft"
    decision = pr["review_decision"]
    if decision == "APPROVED":
        return "approved"
    if decision == "CHANGES_REQUESTED":
        return "changes_requested"
    return "needs_review"


async def pull_requests(scope: str = "team") -> dict:
    """Open PRs with their review state, bucketed for the board.

    scope="team" limits to TEAM_REPOS, scope="org" covers the whole org.
    """
    key = f"prs:{scope}"
    cached = _cached(key)
    if cached:
        return cached

    settings = get_settings()
    org = settings.GITHUB_ORG
    if not settings.GITHUB_TOKEN:
        return {"error": "GITHUB_TOKEN is not configured", "pull_requests": []}

    # Search ORs its scope qualifiers, so org: alongside repo: still matches the
    # whole org. The team board therefore lists repos and omits org: entirely.
    if scope == "team":
        q = "is:pr is:open " + " ".join(f"repo:{org}/{r}" for r in TEAM_REPOS)
    else:
        q = f"org:{org} is:pr is:open"

    rows: list[dict] = []
    total = 0
    after = None
    try:
        async with httpx.AsyncClient(timeout=60, headers=_headers()) as client:
            for _ in range(_PR_MAX_PAGES):
                r = await client.post(_API + "/graphql", json={
                    "query": _PR_QUERY,
                    "variables": {"q": q, "n": _PR_PAGE, "after": after},
                })
                if r.status_code != 200:
                    raise RuntimeError(f"GraphQL returned {r.status_code}")
                payload = r.json()
                if payload.get("errors"):
                    raise RuntimeError(str(payload["errors"])[:200])
                search = payload["data"]["search"]
                total = search["issueCount"]
                for n in search["nodes"]:
                    if not n:
                        continue
                    rows.append({
                        "repo": n["repository"]["name"],
                        "number": n["number"],
                        "title": n["title"],
                        "author": (n.get("author") or {}).get("login", "unknown"),
                        "is_bot": (n.get("author") or {}).get("__typename") == "Bot",
                        "url": n["url"],
                        "draft": bool(n.get("isDraft")),
                        "review_decision": n.get("reviewDecision"),
                        "created_at": n["createdAt"],
                        "age_days": _age_days(n["createdAt"]),
                    })
                if not search["pageInfo"]["hasNextPage"]:
                    break
                after = search["pageInfo"]["endCursor"]
    except Exception as exc:  # noqa: BLE001
        logger.warning("GitHub PR board failed: %s", exc)
        return {"error": str(exc)[:200], "pull_requests": [], "total": 0}

    for pr in rows:
        pr["bucket"] = _bucket(pr)
        pr["stale"] = pr["age_days"] >= _STALE_DAYS

    order = {"approved": 0, "changes_requested": 1, "needs_review": 2, "draft": 3}
    rows.sort(key=lambda p: (order.get(p["bucket"], 9), -p["age_days"]))

    counts = {b: sum(1 for p in rows if p["bucket"] == b) for b in order}
    return _store(key, {
        "scope": scope,
        "total": total,
        "returned": len(rows),
        "truncated": len(rows) < total,
        "counts": counts,
        "stale_count": sum(1 for p in rows if p["stale"]),
        "bot_count": sum(1 for p in rows if p["is_bot"]),
        "pull_requests": rows,
        "error": None,
    })


# ─── Repo activity ────────────────────────────────────────────────────────────

_REPO_STALE_DAYS = 365


def _repo_row(x: dict) -> dict:
    return {
        "name": x["name"],
        "private": x.get("private"),
        "language": x.get("language"),
        "open_issues": x.get("open_issues_count", 0),
        "pushed_at": x.get("pushed_at"),
        "pushed_days": _age_days(x.get("pushed_at") or ""),
        "archived": x.get("archived", False),
        "url": x.get("html_url"),
        "is_team_repo": x["name"] in TEAM_REPOS,
    }


async def repo_activity(limit: int = 15) -> dict:
    """Most recently pushed org repos, plus the ones nobody has pushed to.

    Two sorted pages rather than the whole org: ``direction=desc`` gives the
    freshest repos and ``asc`` the most abandoned, which is all either list
    shows. Archived repos are expected to be idle, so they are kept out of the
    stale list.
    """
    cached = _cached(f"repos:{limit}")
    if cached:
        return cached

    settings = get_settings()
    if not settings.GITHUB_TOKEN:
        return {"error": "GITHUB_TOKEN is not configured", "repos": [], "stale": []}

    url = f"{_API}/orgs/{settings.GITHUB_ORG}/repos"
    try:
        async with httpx.AsyncClient(timeout=40, headers=_headers()) as client:
            recent_r, stale_r = await asyncio.gather(
                client.get(url, params={"per_page": 100, "sort": "pushed", "direction": "desc"}),
                client.get(url, params={"per_page": 100, "sort": "pushed", "direction": "asc"}),
            )
            recent_r.raise_for_status()
            stale_r.raise_for_status()
            recent_data, stale_data = recent_r.json(), stale_r.json()
    except Exception as exc:  # noqa: BLE001
        logger.warning("GitHub repo activity failed: %s", exc)
        return {"error": str(exc)[:200], "repos": [], "stale": []}

    rows = [_repo_row(x) for x in recent_data]
    stale = [
        r for r in (_repo_row(x) for x in stale_data)
        if not r["archived"] and r["pushed_days"] >= _REPO_STALE_DAYS
    ]
    stale.sort(key=lambda r: -r["pushed_days"])

    return _store(f"repos:{limit}", {
        "page_size": len(rows),
        "repos": rows[:limit],
        "team_repos": [r for r in rows if r["is_team_repo"]],
        "recent_count": sum(1 for r in rows if r["pushed_days"] <= _STALE_DAYS),
        "recent_days_threshold": _STALE_DAYS,
        "stale": stale[:50],
        "stale_count": len(stale),
        "stale_days_threshold": _REPO_STALE_DAYS,
        "archived_count": sum(1 for x in stale_data if x.get("archived")),
        "error": None,
    })


# ─── Copilot seats (enterprise) ───────────────────────────────────────────────

_COPILOT_IDLE_DAYS = 30
_SEAT_PAGE = 100
_SEAT_MAX_PAGES = 12


async def copilot_seats() -> dict:
    """Enterprise Copilot seats, with the idle ones called out.

    A seat nobody has used is a license being paid for, so seats are split into
    never-used, idle for 30 days or more, and active.
    """
    cached = _cached("copilot")
    if cached:
        return cached

    settings = get_settings()
    ent = settings.GITHUB_ENTERPRISE_SLUG
    if not _has_billing_token() or not ent:
        return {"error": "GitHub token or enterprise slug is not configured", "seats": []}

    seats: list[dict] = []
    total = 0
    try:
        async with httpx.AsyncClient(timeout=60, headers=_billing_headers()) as client:
            for page in range(1, _SEAT_MAX_PAGES + 1):
                r = await client.get(f"{_API}/enterprises/{ent}/copilot/billing/seats",
                                     params={"per_page": _SEAT_PAGE, "page": page})
                if r.status_code != 200:
                    raise RuntimeError(f"GitHub returned {r.status_code}")
                payload = r.json()
                total = payload.get("total_seats", total)
                batch = payload.get("seats") or []
                seats.extend(batch)
                if len(batch) < _SEAT_PAGE:
                    break
    except Exception as exc:  # noqa: BLE001
        logger.warning("Copilot seat read failed: %s", exc)
        return {"error": str(exc)[:200], "seats": [], "total_seats": 0}

    rows = []
    for s in seats:
        last = s.get("last_activity_at")
        idle = _age_days(last) if last else None
        rows.append({
            "login": (s.get("assignee") or {}).get("login", "unknown"),
            "organization": (s.get("organization") or {}).get("login"),
            "created_at": s.get("created_at"),
            "last_activity_at": last,
            "idle_days": idle,
            "editor": (s.get("last_activity_editor") or "").split("/")[0] or None,
            "pending_cancellation_date": s.get("pending_cancellation_date"),
            "never_used": last is None,
            "idle": last is not None and idle >= _COPILOT_IDLE_DAYS,
        })

    # Least active first. CMS wants everyone on Copilot and using it, so this
    # ordering is about who needs a nudge, not who should lose a seat.
    rows.sort(key=lambda r: (not r["never_used"], -(r["idle_days"] or 0)))
    never = [r for r in rows if r["never_used"]]
    idle = [r for r in rows if r["idle"]]

    by_org: dict[str, dict] = {}
    for r in rows:
        org = r["organization"] or "(no organization)"
        entry = by_org.setdefault(org, {"organization": org, "seats": 0,
                                        "never_used": 0, "idle": 0, "active": 0})
        entry["seats"] += 1
        if r["never_used"]:
            entry["never_used"] += 1
        elif r["idle"]:
            entry["idle"] += 1
        else:
            entry["active"] += 1
    orgs = sorted(by_org.values(), key=lambda e: -e["seats"])
    for entry in orgs:
        entry["active_pct"] = round(entry["active"] * 100 / entry["seats"]) if entry["seats"] else 0

    ever_used = [r["idle_days"] for r in rows if r["idle_days"] is not None]

    return _store("copilot", {
        "enterprise": ent,
        "total_seats": total,
        "fetched": len(rows),
        "never_used_count": len(never),
        "idle_count": len(idle),
        "active_count": len(rows) - len(never) - len(idle),
        "pending_cancellation": sum(1 for r in rows if r["pending_cancellation_date"]),
        "avg_idle_days": round(sum(ever_used) / len(ever_used), 1) if ever_used else None,
        "idle_days_threshold": _COPILOT_IDLE_DAYS,
        "by_org": orgs,
        "seats": (never + idle)[:50],
        # Activity for every seat, not just the least-active ones the table
        # shows, so a lookup by login can tell "active" from "not a seat".
        "activity_by_login": {
            r["login"].lower(): {
                "idle_days": r["idle_days"],
                "never_used": r["never_used"],
                "editor": r["editor"],
                "organization": r["organization"],
            } for r in rows
        },
        "error": None,
    })


# ─── Copilot seat identities ──────────────────────────────────────────────────

_LICENSE_PAGE = 100
_LICENSE_MAX_PAGES = 80


async def _consumed_license_index() -> dict[str, dict]:
    """Map github.com login → the identity the enterprise holds for it.

    A Copilot seat carries only a login, and these logins are vendor handles
    that AD has never heard of, so the enterprise consumed-licenses report is
    the only place that ties a login to a SAML name ID (the EUA) and to any
    verified-domain email. It is a 60-page read, hence its own cache entry.
    """
    cached = _cached("license_index")
    if cached is not None:
        return cached

    settings = get_settings()
    ent = settings.GITHUB_ENTERPRISE_SLUG
    if not _has_billing_token() or not ent:
        return _store("license_index", {})

    index: dict[str, dict] = {}
    try:
        async with httpx.AsyncClient(timeout=60, headers=_billing_headers()) as client:
            for page in range(1, _LICENSE_MAX_PAGES + 1):
                r = await client.get(f"{_API}/enterprises/{ent}/consumed-licenses",
                                     params={"per_page": _LICENSE_PAGE, "page": page})
                if r.status_code != 200:
                    raise RuntimeError(f"GitHub returned {r.status_code}")
                users = r.json().get("users") or []
                if not users:
                    break
                for u in users:
                    login = (u.get("github_com_login") or "").strip()
                    if not login:
                        continue
                    emails = u.get("github_com_verified_domain_emails") or []
                    index[login.lower()] = {
                        "eua": u.get("github_com_saml_name_id") or None,
                        "verified_email": emails[0] if emails else None,
                        "name": u.get("github_com_name") or None,
                    }
                if len(users) < _LICENSE_PAGE:
                    break
    except Exception as exc:  # noqa: BLE001
        logger.warning("Consumed-licenses read failed: %s", exc)
        return index

    return _store("license_index", index)


async def copilot_identities(logins: list[str]) -> dict:
    """Resolve Copilot logins to a reachable email address.

    AD is preferred over the verified-domain email: it holds the contractor
    address people actually read, where the verified-domain value is the
    cms.hhs.gov alias and is populated for only a third of them.
    """
    wanted = [l for l in dict.fromkeys(l.strip() for l in logins) if l]
    if not wanted:
        return {"identities": {}, "resolved": 0, "requested": 0}

    index = await _consumed_license_index()
    euas = [index.get(l.lower(), {}).get("eua") for l in wanted]
    euas = [e for e in euas if e]

    ad: dict[str, dict] = {}
    if euas:
        try:
            from app.services import ldap_accounts
            ad = await asyncio.to_thread(ldap_accounts.get_mail, euas)
        except Exception as exc:  # noqa: BLE001
            logger.warning("AD mail lookup for Copilot seats failed: %s", exc)

    out: dict[str, dict] = {}
    for login in wanted:
        ent = index.get(login.lower()) or {}
        eua = ent.get("eua")
        row = ad.get((eua or "").lower(), {}) if eua else {}
        email = row.get("mail") or ent.get("verified_email")
        out[login] = {
            "eua": eua,
            "email": email,
            "name": row.get("display_name") or ent.get("name"),
            "source": "ad" if row.get("mail") else ("verified_domain" if email else None),
        }

    return {
        "identities": out,
        "requested": len(wanted),
        "resolved": sum(1 for v in out.values() if v["email"]),
    }


# ─── Copilot power users (ai_credits budgets) ─────────────────────────────────

_AI_CREDIT_SKU = "ai_credits"


async def copilot_power_users() -> dict:
    """Users granted their own AI-credit budget, with how much they use Copilot.

    A power user is an enterprise budget scoped to one user against the
    ``ai_credits`` SKU. The budgets API is the only place that records them;
    the Copilot seat object says nothing about credits.

    Consumption is read from the premium-request usage report. That report is
    currently empty for every month checked, and the only Copilot line on the
    billing usage report is "Copilot Business" in user-months, so no credits
    have been drawn down yet. The seat's own last-activity date is therefore
    the usable signal for whether a power user is actually using Copilot.
    """
    cached = _cached("copilot_power")
    if cached is not None:
        return cached

    settings = get_settings()
    ent = settings.GITHUB_ENTERPRISE_SLUG
    if not _has_billing_token() or not ent:
        return {"error": "GitHub token or enterprise slug is not configured", "users": []}

    now = datetime.now(timezone.utc)
    try:
        async with httpx.AsyncClient(timeout=60, headers=_billing_headers()) as client:
            budget_r, usage_r = await asyncio.gather(
                client.get(f"{_API}/enterprises/{ent}/settings/billing/budgets"),
                client.get(f"{_API}/enterprises/{ent}/settings/billing/premium_request/usage",
                           params={"year": now.year, "month": now.month}),
                return_exceptions=True,
            )
        if not hasattr(budget_r, "status_code") or budget_r.status_code != 200:
            code = getattr(budget_r, "status_code", "error")
            return {"error": f"Budget read returned {code}", "users": []}
        budgets = budget_r.json().get("budgets") or []
    except Exception as exc:  # noqa: BLE001
        logger.warning("Copilot power-user read failed: %s", exc)
        return {"error": str(exc)[:200], "users": []}

    credit_budgets = [b for b in budgets if b.get("budget_product_sku") == _AI_CREDIT_SKU]

    # Credits consumed per login this month, when the report has anything.
    used: dict[str, float] = {}
    usage_available = False
    if hasattr(usage_r, "status_code") and usage_r.status_code == 200:
        items = usage_r.json().get("usageItems") or []
        usage_available = bool(items)
        for item in items:
            login = (item.get("userName") or item.get("actor") or "").lower()
            if login:
                used[login] = used.get(login, 0.0) + float(item.get("quantity") or 0)

    cp = await copilot_seats()
    activity = cp.get("activity_by_login") or {}

    users = []
    for b in credit_budgets:
        if b.get("budget_scope") != "user":
            continue
        login = (b.get("budget_entity_name") or "").strip()
        seat = activity.get(login.lower())
        idle_days = seat["idle_days"] if seat else None
        never_used = bool(seat and seat["never_used"])
        users.append({
            "login": login,
            "budget_amount": b.get("budget_amount"),
            "blocks_at_cap": bool(b.get("prevent_further_usage")),
            "alerting": bool((b.get("budget_alerting") or {}).get("will_alert")),
            "credits_used": used.get(login.lower()),
            "never_used": never_used,
            "idle_days": idle_days,
            "editor": seat.get("editor") if seat else None,
            "organization": seat.get("organization") if seat else None,
            # A budget whose holder has no Copilot seat at all is the clearest
            # case: they are being granted credits they cannot spend.
            "has_seat": seat is not None,
            # Only ever a suggestion: a power user who is not using Copilot at
            # all is the one worth a conversation about stepping back down.
            "downgrade_candidate": (
                seat is None or never_used
                or (idle_days is not None and idle_days >= _COPILOT_IDLE_DAYS)
            ),
        })
    users.sort(key=lambda u: (not u["downgrade_candidate"], u["login"].lower()))

    pools = [{
        "name": b.get("budget_entity_name"),
        "budget_amount": b.get("budget_amount"),
        "blocks_at_cap": bool(b.get("prevent_further_usage")),
    } for b in credit_budgets if b.get("budget_scope") != "user"]

    return _store("copilot_power", {
        "enterprise": ent,
        "users": users,
        "pools": pools,
        "total": len(users),
        "downgrade_candidates": sum(1 for u in users if u["downgrade_candidate"]),
        "usage_available": usage_available,
        "usage_note": (
            None if usage_available else
            "GitHub's premium-request usage report is empty for this enterprise, and the "
            "only Copilot line on the billing report is Copilot Business in user-months, "
            "so no AI credits have been drawn down yet. Until they are, Copilot activity "
            "is the only usable signal for whether a power user needs their budget."
        ),
        "idle_days_threshold": _COPILOT_IDLE_DAYS,
        "error": None,
    })


# ─── Copilot spend by cost center ──────────────────────────────────────────────

# budget_thresholds on a multi_user_cost_center budget is a headcount
# distribution across usage buckets (e.g. {"0": 74, "75": 1, "90": 1, "100": 3}),
# not a single amount, because the budget is shared across every seat the cost
# center covers. "0" is everyone under 75%, so it is the only safe one to
# label "healthy" here.
_SPEND_THRESHOLDS = ("100", "90", "75")


def _spend_status(counts: dict[str, int]) -> str:
    for level, label in zip(_SPEND_THRESHOLDS, ("over", "near", "warning")):
        if counts.get(level, 0) > 0:
            return label
    return "healthy"


def _user_budget_status(pct: float | None) -> str:
    if pct is None:
        return "unknown"
    if pct >= 100:
        return "over"
    if pct >= 90:
        return "near"
    if pct >= 75:
        return "warning"
    return "healthy"


_TEAM_MEMBERS_PAGE = 100
_TEAM_MEMBERS_MAX_PAGES = 5


async def _enterprise_team_logins(client: httpx.AsyncClient, ent: str, team_slug: str) -> set[str]:
    """Logins belonging to an enterprise team (cost-center resources carry
    team slugs prefixed "ent:"; the memberships endpoint wants it bare)."""
    slug = team_slug.removeprefix("ent:")
    logins: set[str] = set()
    try:
        for page in range(1, _TEAM_MEMBERS_MAX_PAGES + 1):
            r = await client.get(f"{_API}/enterprises/{ent}/teams/{slug}/memberships",
                                  params={"per_page": _TEAM_MEMBERS_PAGE, "page": page})
            if r.status_code != 200:
                break
            batch = r.json() or []
            logins.update(u.get("login", "").lower() for u in batch if u.get("login"))
            if len(batch) < _TEAM_MEMBERS_PAGE:
                break
    except Exception as exc:  # noqa: BLE001
        logger.warning("Enterprise team membership read failed for %s: %s", team_slug, exc)
    return logins


async def copilot_spend() -> dict:
    """Copilot AI-credit budgets joined to the cost center / team they cover.

    GitHub enterprise billing has two kinds of ``ai_credits`` budget: one per
    cost center (shared across every seat the center's resources cover, with
    usage reported as a headcount distribution across thresholds) and one per
    individual "power user". Cost centers without a budget configured at all
    are included too, so the view answers "which team is closest to its cap"
    for every cost center, not just the funded ones.
    """
    cached = _cached("spend")
    if cached:
        return cached

    settings = get_settings()
    ent = settings.GITHUB_ENTERPRISE_SLUG
    if not _has_billing_token() or not ent:
        return {"error": "GitHub token or enterprise slug is not configured",
                "cost_centers": [], "unbudgeted_cost_centers": [], "people": []}

    try:
        async with httpx.AsyncClient(timeout=60, headers=_billing_headers()) as client:
            cc_r, bud_r = await asyncio.gather(
                client.get(f"{_API}/enterprises/{ent}/settings/billing/cost-centers"),
                client.get(f"{_API}/enterprises/{ent}/settings/billing/budgets"),
            )
            cc_r.raise_for_status()
            bud_r.raise_for_status()
            centers = cc_r.json().get("costCenters") or []
            budgets = bud_r.json().get("budgets") or []
    except Exception as exc:  # noqa: BLE001
        logger.warning("Copilot spend read failed: %s", exc)
        return {"error": str(exc)[:200], "cost_centers": [], "unbudgeted_cost_centers": [], "people": []}

    by_name = {c.get("name"): c for c in centers}
    ai_credit_budgets = [b for b in budgets if b.get("budget_product_sku") == _AI_CREDIT_SKU]

    cost_centers = []
    for b in ai_credit_budgets:
        if b.get("budget_scope") != "multi_user_cost_center":
            continue
        name = b.get("budget_entity_name")
        cc = by_name.get(name, {})
        counts = {k: int(v) for k, v in (b.get("budget_thresholds") or {}).items()}
        status = _spend_status(counts)
        cost_centers.append({
            "cost_center": name,
            "cost_center_id": cc.get("id"),
            "state": cc.get("state"),
            "resources": cc.get("resources", []),
            "budget_amount": b.get("budget_amount"),
            "prevent_further_usage": bool(b.get("prevent_further_usage")),
            "alerting": bool((b.get("budget_alerting") or {}).get("will_alert")),
            "users_healthy": counts.get("0", 0),
            "users_warning_75": counts.get("75", 0),
            "users_near_90": counts.get("90", 0),
            "users_over_100": counts.get("100", 0),
            "users_total": sum(counts.values()),
            "users_at_risk": counts.get("75", 0) + counts.get("90", 0) + counts.get("100", 0),
            "status": status,
        })
    status_rank = {"over": 3, "near": 2, "warning": 1, "healthy": 0}
    cost_centers.sort(key=lambda r: (-status_rank[r["status"]], -r["users_at_risk"]))

    people = []
    for b in ai_credit_budgets:
        if b.get("budget_scope") != "user":
            continue
        amount = b.get("budget_amount") or 0
        consumed = b.get("consumed_amount")
        pct = round(consumed / amount * 100, 1) if amount and consumed is not None else None
        people.append({
            "login": b.get("user") or b.get("budget_entity_name"),
            "budget_amount": amount,
            "consumed_amount": consumed,
            "pct_used": pct,
            "prevent_further_usage": bool(b.get("prevent_further_usage")),
            "expires_at": b.get("expires_at"),
            "status": _user_budget_status(pct),
        })
    people.sort(key=lambda p: -(p["pct_used"] or -1))
    people_by_login = {p["login"].lower(): p for p in people}

    # A cost center with no pooled budget of its own can still be covered
    # entirely by individual budgets on its members (e.g. "Power Users" has
    # no multi_user_cost_center budget, but several of its team's members
    # each hold their own $39 budget) — that is coverage, not a gap, so it
    # has to be checked against each Team/User resource before calling a
    # cost center unbudgeted.
    budgeted_names = {r["cost_center"] for r in cost_centers}
    candidates = [c for c in centers if c.get("name") not in budgeted_names and c.get("state") == "active"]

    async def covered_logins(cc: dict) -> set[str]:
        resources = cc.get("resources") or []
        found = {r["name"].lower() for r in resources if r.get("type") == "User"} & set(people_by_login)
        teams = [r["name"] for r in resources if r.get("type") == "Team"]
        if teams:
            async with httpx.AsyncClient(timeout=30, headers=_billing_headers()) as client:
                members_lists = await asyncio.gather(
                    *[_enterprise_team_logins(client, ent, t) for t in teams], return_exceptions=True)
            for m in members_lists:
                if isinstance(m, set):
                    found |= m & set(people_by_login)
        return found

    coverage = await asyncio.gather(*[covered_logins(c) for c in candidates])

    cost_centers_individual = []
    unbudgeted_cost_centers = []
    for cc, logins in zip(candidates, coverage):
        if not logins:
            unbudgeted_cost_centers.append({
                "cost_center": cc.get("name"), "cost_center_id": cc.get("id"),
                "state": cc.get("state"), "resources": cc.get("resources", []),
            })
            continue
        members = [people_by_login[l] for l in sorted(logins)]
        at_risk = sum(1 for m in members if m["status"] not in ("healthy", "unknown"))
        cost_centers_individual.append({
            "cost_center": cc.get("name"), "cost_center_id": cc.get("id"),
            "state": cc.get("state"), "resources": cc.get("resources", []),
            "members_with_budget": [m["login"] for m in members],
            "members_with_budget_count": len(members),
            "members_at_risk": at_risk,
            "status": "over" if any(m["status"] == "over" for m in members)
                      else "near" if any(m["status"] == "near" for m in members)
                      else "warning" if any(m["status"] == "warning" for m in members)
                      else "healthy",
        })
    status_rank2 = {"over": 3, "near": 2, "warning": 1, "healthy": 0}
    cost_centers_individual.sort(key=lambda r: (-status_rank2[r["status"]], -r["members_at_risk"]))

    return _store("spend", {
        "enterprise": ent,
        "cost_centers": cost_centers,
        "cost_centers_at_risk": sum(1 for r in cost_centers if r["status"] != "healthy"),
        "cost_centers_individual": cost_centers_individual,
        "unbudgeted_cost_centers": unbudgeted_cost_centers,
        "people": people,
        "people_at_risk": sum(1 for p in people if p["status"] not in ("healthy", "unknown")),
        "error": None,
    })


# ─── Real metered billing spend ────────────────────────────────────────────────

_BILLING_SPEND_MONTHS = 3


async def copilot_billing_spend(months: int = _BILLING_SPEND_MONTHS) -> dict:
    """Actual billed dollars for Copilot, from GitHub's enhanced billing usage
    report (not the credit-pool budgets, which are a different dollar scope).

    This is the enterprise's metered usage report, and for CMS it comes back
    small (tens of dollars a month against ~350 seats) — far below list price
    for that many Copilot Business seats. That almost certainly means the
    bulk seat licensing here is invoiced outside this metered report (a
    separate enterprise agreement), so this number is real but is not "what
    Copilot costs us" — it is only what shows up as metered usage.
    """
    cached = _cached("billing_spend", _REPORT_CACHE_TTL)
    if cached:
        return cached

    settings = get_settings()
    ent = settings.GITHUB_ENTERPRISE_SLUG
    if not _has_billing_token() or not ent:
        return {"error": "GitHub billing token or enterprise slug is not configured",
                "monthly": [], "by_sku": []}

    today = date.today()
    periods = []
    y, m = today.year, today.month
    for i in range(months):
        yy, mm = y, m - i
        while mm <= 0:
            mm += 12
            yy -= 1
        periods.append((yy, mm))

    try:
        async with httpx.AsyncClient(timeout=30, headers=_billing_headers()) as client:
            responses = await asyncio.gather(*[
                client.get(f"{_API}/enterprises/{ent}/settings/billing/usage",
                           params={"year": yy, "month": mm})
                for yy, mm in periods
            ], return_exceptions=True)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Copilot billing usage read failed: %s", exc)
        return {"error": str(exc)[:200], "monthly": [], "by_sku": []}

    monthly = []
    by_sku: dict[str, dict] = {}
    for (yy, mm), r in zip(periods, responses):
        if not hasattr(r, "status_code") or r.status_code != 200:
            continue
        items = [i for i in (r.json().get("usageItems") or []) if i.get("product") == "copilot"]
        total = sum(i.get("netAmount") or 0 for i in items)
        monthly.append({"year": yy, "month": mm, "net_amount": round(total, 2), "line_items": len(items)})
        for item in items:
            sku = item.get("sku") or "unknown"
            e = by_sku.setdefault(sku, {"sku": sku, "net_amount": 0.0, "quantity": 0.0})
            e["net_amount"] += item.get("netAmount") or 0
            e["quantity"] += item.get("quantity") or 0
    monthly.sort(key=lambda row: (row["year"], row["month"]))
    sku_rows = sorted(by_sku.values(), key=lambda row: -row["net_amount"])
    for row in sku_rows:
        row["net_amount"] = round(row["net_amount"], 2)
        row["quantity"] = round(row["quantity"], 4)

    return _store("billing_spend", {
        "enterprise": ent,
        "monthly": monthly,
        "by_sku": sku_rows,
        "total_net_amount": round(sum(row["net_amount"] for row in monthly), 2),
        "error": None,
    })


# ─── Copilot usage & adoption, and per-person activity ────────────────────────

# The metrics-report endpoints hand back short-lived signed download links
# rather than the report body, and the underlying report is a daily rollup
# (the enterprise one carries its own created_at), so these are cached far
# longer than the 5-minute default to avoid re-pulling a multi-MB file on
# every page load.
_REPORT_CACHE_TTL = 1800


async def _fetch_report_rows(path: str) -> list[dict]:
    """Resolve a copilot/metrics/reports/* endpoint to its parsed NDJSON rows."""
    async with httpx.AsyncClient(timeout=60, headers=_billing_headers()) as client:
        meta = await client.get(_API + path)
        meta.raise_for_status()
        links = meta.json().get("download_links") or []

    rows: list[dict] = []
    async with httpx.AsyncClient(timeout=180) as client:  # pre-signed; no auth header
        for link in links:
            r = await client.get(link)
            r.raise_for_status()
            for line in r.text.splitlines():
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
    return rows


async def copilot_usage_adoption() -> dict:
    """Enterprise-wide Copilot adoption over the trailing 28 days.

    Best-effort mapping of GitHub's own "Usage & Adoption" view: active-user
    counts, interaction/generation/acceptance totals, and a breakdown by IDE,
    all read from the enterprise-28-day metrics report.
    """
    cached = _cached("usage_adoption", _REPORT_CACHE_TTL)
    if cached:
        return cached

    settings = get_settings()
    ent = settings.GITHUB_ENTERPRISE_SLUG
    if not _has_billing_token() or not ent:
        return {"error": "GitHub billing token or enterprise slug is not configured"}

    try:
        rows = await _fetch_report_rows(
            f"/enterprises/{ent}/copilot/metrics/reports/enterprise-28-day/latest")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Copilot usage/adoption report read failed: %s", exc)
        return {"error": str(exc)[:200]}

    if not rows:
        return {"error": "No enterprise usage report is available yet"}

    report = rows[0]
    # day_totals is not guaranteed to arrive in day order.
    day_totals = sorted(report.get("day_totals") or [], key=lambda d: d.get("day") or "")
    latest = day_totals[-1] if day_totals else {}

    total_interactions = sum(d.get("user_initiated_interaction_count", 0) for d in day_totals)
    total_generations = sum(d.get("code_generation_activity_count", 0) for d in day_totals)
    total_acceptances = sum(d.get("code_acceptance_activity_count", 0) for d in day_totals)

    by_ide: dict[str, dict] = {}
    for d in day_totals:
        for item in d.get("totals_by_ide") or []:
            e = by_ide.setdefault(item["ide"], {
                "ide": item["ide"], "interactions": 0, "generations": 0,
                "acceptances": 0, "lines_added": 0,
            })
            e["interactions"] += item.get("user_initiated_interaction_count", 0)
            e["generations"] += item.get("code_generation_activity_count", 0)
            e["acceptances"] += item.get("code_acceptance_activity_count", 0)
            e["lines_added"] += item.get("loc_added_sum", 0)
    ide_rows = sorted(by_ide.values(), key=lambda r: -r["interactions"])

    by_model: dict[str, dict] = {}
    for d in day_totals:
        for item in d.get("totals_by_model_feature") or []:
            model = item.get("model") or "unknown"
            e = by_model.setdefault(model, {
                "model": model, "interactions": 0, "generations": 0,
                "acceptances": 0, "lines_added": 0,
            })
            e["interactions"] += item.get("user_initiated_interaction_count", 0)
            e["generations"] += item.get("code_generation_activity_count", 0)
            e["acceptances"] += item.get("code_acceptance_activity_count", 0)
            e["lines_added"] += item.get("loc_added_sum", 0)
    model_rows = sorted(by_model.values(), key=lambda r: -r["interactions"])

    by_language: dict[str, dict] = {}
    for d in day_totals:
        for item in d.get("totals_by_language_feature") or []:
            language = item.get("language") or "unknown"
            e = by_language.setdefault(language, {
                "language": language, "generations": 0, "acceptances": 0,
                "lines_added": 0, "lines_suggested": 0,
            })
            e["generations"] += item.get("code_generation_activity_count", 0)
            e["acceptances"] += item.get("code_acceptance_activity_count", 0)
            e["lines_added"] += item.get("loc_added_sum", 0)
            e["lines_suggested"] += item.get("loc_suggested_to_add_sum", 0)
    language_rows = sorted(by_language.values(), key=lambda r: -r["generations"])

    by_feature: dict[str, dict] = {}
    for d in day_totals:
        for item in d.get("totals_by_feature") or []:
            feature = item.get("feature") or "unknown"
            e = by_feature.setdefault(feature, {
                "feature": feature, "interactions": 0, "generations": 0, "acceptances": 0,
            })
            e["interactions"] += item.get("user_initiated_interaction_count", 0)
            e["generations"] += item.get("code_generation_activity_count", 0)
            e["acceptances"] += item.get("code_acceptance_activity_count", 0)
    feature_rows = sorted(
        ({**v, "label": _feature_label(k)} for k, v in by_feature.items()),
        key=lambda r: -r["interactions"],
    )
    chat_rows = [r for r in feature_rows if r["feature"].startswith("chat_")]
    chat_interactions = sum(r["interactions"] for r in chat_rows)
    chat_generations = sum(r["generations"] for r in chat_rows)
    chat_acceptances = sum(r["acceptances"] for r in chat_rows)

    return _store("usage_adoption", {
        "enterprise": ent,
        "report_start_day": report.get("report_start_day"),
        "report_end_day": report.get("report_end_day"),
        "latest_day": latest.get("day"),
        "daily_active_users": latest.get("daily_active_users", 0),
        "weekly_active_users": latest.get("weekly_active_users", 0),
        "monthly_active_users": latest.get("monthly_active_users", 0),
        "monthly_active_chat_users": latest.get("monthly_active_chat_users", 0),
        "monthly_active_agent_users": latest.get("monthly_active_agent_users", 0),
        "total_interactions": total_interactions,
        "total_generations": total_generations,
        "total_acceptances": total_acceptances,
        "acceptance_rate": round(total_acceptances / total_generations * 100, 1) if total_generations else None,
        "daily_active_users_trend": [
            {"day": d.get("day"), "active_users": d.get("daily_active_users", 0)} for d in day_totals
        ],
        "by_ide": ide_rows,
        "by_model": model_rows,
        "by_language": language_rows,
        "by_feature": feature_rows,
        "chat_interactions": chat_interactions,
        "chat_generations": chat_generations,
        "chat_acceptances": chat_acceptances,
        "chat_acceptance_rate": round(chat_acceptances / chat_generations * 100, 1) if chat_generations else None,
        "error": None,
    })


_PEOPLE_PAGE = 100


async def _people_raw_rows() -> list[dict]:
    """The parsed users-28-day report rows, shared by copilot_people() and
    copilot_person() so a single person lookup doesn't re-download the
    (multi-MB) report that copilot_people() already cached."""
    cached = _cached("people_raw", _REPORT_CACHE_TTL)
    if cached is not None:
        return cached

    settings = get_settings()
    ent = settings.GITHUB_ENTERPRISE_SLUG
    if not _has_billing_token() or not ent:
        return []

    try:
        rows = await _fetch_report_rows(
            f"/enterprises/{ent}/copilot/metrics/reports/users-28-day/latest")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Copilot people report read failed: %s", exc)
        return []
    return _store("people_raw", rows)


async def copilot_people() -> dict:
    """Per-person Copilot activity over the trailing 28 days, most active first.

    Best-effort mapping of GitHub's own "People" view. GitHub does not expose
    acceptance rate or lines-of-code figures the way any particular dashboard
    chooses to present them, so these are this app's own aggregation of the
    enterprise's users-28-day metrics report, not a reproduction of any other
    tool's exact numbers.
    """
    cached = _cached("people", _REPORT_CACHE_TTL)
    if cached:
        return cached

    settings = get_settings()
    ent = settings.GITHUB_ENTERPRISE_SLUG
    if not _has_billing_token() or not ent:
        return {"error": "GitHub billing token or enterprise slug is not configured", "people": []}

    rows = await _people_raw_rows()
    if not rows:
        return {"error": "No per-user usage report is available yet", "people": []}

    by_user: dict[str, dict] = {}
    report_start = report_end = None
    for r in rows:
        login = r.get("user_login") or str(r.get("user_id") or "unknown")
        report_start = report_start or r.get("report_start_day")
        report_end = report_end or r.get("report_end_day")
        e = by_user.setdefault(login, {
            "login": login, "interactions": 0, "generations": 0,
            "acceptances": 0, "lines_added": 0, "lines_suggested": 0, "active_days": 0,
            "ai_credits_used": 0.0,
            "_models": {},  # model -> interaction count, for picking top_model below
        })
        e["interactions"] += r.get("user_initiated_interaction_count", 0)
        e["generations"] += r.get("code_generation_activity_count", 0)
        e["acceptances"] += r.get("code_acceptance_activity_count", 0)
        e["ai_credits_used"] += r.get("ai_credits_used") or 0.0
        e["active_days"] += 1
        for item in r.get("totals_by_ide") or []:
            e["lines_added"] += item.get("loc_added_sum", 0)
            e["lines_suggested"] += item.get("loc_suggested_to_add_sum", 0)
        for item in r.get("totals_by_model_feature") or []:
            model = item.get("model") or "unknown"
            e["_models"][model] = e["_models"].get(model, 0) + item.get("user_initiated_interaction_count", 0)

    people = list(by_user.values())
    for p in people:
        p["acceptance_rate"] = round(p["acceptances"] / p["generations"] * 100, 1) if p["generations"] else None
        p["line_acceptance_rate"] = (
            round(p["lines_added"] / p["lines_suggested"] * 100, 1) if p["lines_suggested"] else None
        )
        p["ai_credits_used"] = round(p["ai_credits_used"], 1)
        models = p.pop("_models")
        p["models_used"] = sorted(models, key=lambda m: -models[m])
        p["top_model"] = p["models_used"][0] if p["models_used"] else None
    people.sort(key=lambda p: -p["interactions"])

    return _store("people", {
        "enterprise": ent,
        "report_start_day": report_start,
        "report_end_day": report_end,
        "total_users": len(people),
        "total_ai_credits_used": round(sum(p["ai_credits_used"] for p in people), 1),
        "people": people[:_PEOPLE_PAGE],
        "error": None,
    })


# ─── Model x feature matrix (ported from pradofernando/copilot-usage-dashboard,
# src/webapp/insights.py, under its MIT license) ───────────────────────────────

_FEATURE_LABELS = {
    "code_completion": "Code completion",
    "chat_panel_ask_mode": "Chat · Ask",
    "chat_panel_edit_mode": "Chat · Edit",
    "chat_panel_agent_mode": "Chat · Agent",
    "chat_panel_custom_mode": "Chat · Custom",
    "chat_panel_plan_mode": "Chat · Plan",
    "chat_inline": "Inline chat",
    "agent_edit": "Agent edits",
    "code_review_active": "Code review",
    "code_review_passive": "Code review (auto)",
    "cloud_agent": "Cloud agent",
    "copilot_cli": "Copilot CLI",
    "github_app": "GitHub app",
    "copilot_app": "Copilot app",
}
_FEATURE_ORDER = list(_FEATURE_LABELS)


def _feature_label(feature: str) -> str:
    return _FEATURE_LABELS.get(feature) or feature.replace("_", " ").capitalize()


def _usage_value(cell: dict) -> float:
    """Prompts where there are any, otherwise suggestions shown (completions)."""
    return cell.get("user_initiated_interaction_count") or cell.get("code_generation_activity_count") or 0


def _model_feature_rows(cells: list[dict], limit: int = 15) -> list[dict]:
    """The exact counts behind the matrix, most-prompted pairs first."""
    busy = [c for c in cells if _usage_value(c) > 0]
    busy.sort(
        key=lambda c: (c.get("user_initiated_interaction_count") or 0,
                        c.get("code_generation_activity_count") or 0),
        reverse=True,
    )
    return [
        {
            "model": c["row"],
            "feature": _feature_label(c["col"]),
            "prompts": c.get("user_initiated_interaction_count") or 0,
            "suggestions": c.get("code_generation_activity_count") or 0,
            "acceptances": c.get("code_acceptance_activity_count") or 0,
            "lines": c.get("loc_added_sum") or 0,
        }
        for c in busy[:limit]
    ]


def _build_model_feature_matrix(cells: list[dict], max_models: int = 8) -> dict:
    """Model x feature grid. Each cell is a share of its feature's usage.

    Comparing models within a feature is what answers "which model for what",
    and it keeps prompts and suggestions (different units) from being mixed.
    """
    value_of: dict[tuple[str, str], float] = {}
    feature_total: dict[str, float] = {}
    prompt_based: set[str] = set()
    for cell in cells:
        value = _usage_value(cell)
        if value <= 0:
            continue
        pair = (cell["row"], cell["col"])
        value_of[pair] = value_of.get(pair, 0) + value
        feature_total[cell["col"]] = feature_total.get(cell["col"], 0) + value
        if cell.get("user_initiated_interaction_count"):
            prompt_based.add(cell["col"])

    if not value_of:
        return {"empty": True, "columns": [], "rows": [], "favourites": [],
                "top_model": "", "top_feature": ""}

    rank = {name: position for position, name in enumerate(_FEATURE_ORDER)}
    features = sorted(feature_total, key=lambda name: (rank.get(name, len(rank)), -feature_total[name]))

    # Models that hold the biggest share across the features come first.
    strength: dict[str, float] = {}
    for (model, feature), value in value_of.items():
        strength[model] = strength.get(model, 0) + (value / feature_total[feature] * 100 if feature_total[feature] else 0)
    models = [m for m, _ in sorted(strength.items(), key=lambda kv: -kv[1])[:max_models]]

    # "Most used" counts prompts the person actually sent; suggestions shown by
    # code completion only decide it when there are no prompts at all.
    counted = prompt_based or set(feature_total)
    by_model: dict[str, float] = {}
    for (model, feature), value in value_of.items():
        if feature in counted:
            by_model[model] = by_model.get(model, 0) + value
    top_model = max(by_model, key=by_model.get) if by_model else ""
    top_feature = max(counted, key=lambda name: feature_total[name])

    rows = []
    for model in models:
        entries = []
        for feature in features:
            value = value_of.get((model, feature), 0)
            share = (value / feature_total[feature] * 100) if feature_total[feature] else 0
            entries.append({"value": value, "share": round(share, 0) if value else None})
        rows.append({"model": model, "cells": entries})

    favourites = []
    for feature in features:
        candidates = [m for m in strength if (m, feature) in value_of]
        leader = max(candidates, key=lambda m: value_of[(m, feature)])
        favourites.append({
            "feature": _feature_label(feature),
            "model": leader,
            "share": round(value_of[(leader, feature)] / feature_total[feature] * 100, 0) if feature_total[feature] else 0,
            "value": value_of[(leader, feature)],
            "unit": "prompts" if feature in prompt_based else "suggestions",
        })

    return {
        "empty": False,
        "columns": [
            {"id": feature, "label": _feature_label(feature), "total": feature_total[feature],
             "unit": "prompts" if feature in prompt_based else "suggestions"}
            for feature in features
        ],
        "rows": rows,
        "favourites": favourites,
        "top_model": top_model,
        "top_feature": _feature_label(top_feature),
    }


# ─── Budget pacing against the calendar month (ported from the same project) ──

_OVER_AT = 100
_AHEAD_GAP, _BEHIND_GAP, _FAR_BEHIND_GAP = 10, -10, -25


def _month_elapsed_pct(as_of: date) -> float:
    days_in_month = calendar.monthrange(as_of.year, as_of.month)[1]
    return as_of.day / days_in_month * 100


def _month_day_reached(as_of: date, used_pct: float) -> date | None:
    """Day the budget runs out if the month-to-date pace simply continues."""
    days_in_month = calendar.monthrange(as_of.year, as_of.month)[1]
    if used_pct <= 0:
        return None
    day = math.ceil(as_of.day * 100 / used_pct)
    if day > days_in_month:
        return None
    return as_of.replace(day=1) + timedelta(days=day - 1)


def _pace_status(used_pct: float, as_of: date) -> dict:
    """How a budget stands against the calendar, as of today."""
    elapsed = _month_elapsed_pct(as_of)
    gap = used_pct - elapsed
    runs_out = _month_day_reached(as_of, used_pct)
    if used_pct >= _OVER_AT:
        label, tone = "over_budget", "bad"
    elif runs_out or gap >= _AHEAD_GAP:
        label, tone = "ahead_of_pace", "warn"
    elif gap <= _FAR_BEHIND_GAP:
        label, tone = "well_behind_pace", "neutral"
    elif gap <= _BEHIND_GAP:
        label, tone = "behind_pace", "neutral"
    else:
        label, tone = "on_pace", "good"
    note = None
    if used_pct < _OVER_AT and runs_out:
        note = f"Runs out ~{runs_out.isoformat()}"
    return {"label": label, "tone": tone, "gap": round(gap, 1), "note": note,
            "month_elapsed_pct": round(elapsed, 1)}


async def copilot_person(login: str) -> dict:
    """One person's Copilot activity, model choice and budget pacing.

    Mirrors GitHub support's demoed "person page" (seat, activity totals,
    model x feature matrix, budget this month), built from the same reads
    the rest of this module already makes against this enterprise.
    """
    rows = await _people_raw_rows()
    login_lower = login.lower()
    mine = [r for r in rows if (r.get("user_login") or "").lower() == login_lower]
    if not mine:
        return {"error": f"No usage report rows for {login}", "login": login}

    interactions = sum(r.get("user_initiated_interaction_count", 0) for r in mine)
    generations = sum(r.get("code_generation_activity_count", 0) for r in mine)
    acceptances = sum(r.get("code_acceptance_activity_count", 0) for r in mine)
    ai_credits_used = round(sum(r.get("ai_credits_used") or 0.0 for r in mine), 1)
    lines_added = lines_suggested = 0
    for r in mine:
        for item in r.get("totals_by_ide") or []:
            lines_added += item.get("loc_added_sum", 0)
            lines_suggested += item.get("loc_suggested_to_add_sum", 0)

    cells = [
        {
            "row": item.get("model") or "unknown",
            "col": item.get("feature") or "unknown",
            "user_initiated_interaction_count": item.get("user_initiated_interaction_count", 0),
            "code_generation_activity_count": item.get("code_generation_activity_count", 0),
            "code_acceptance_activity_count": item.get("code_acceptance_activity_count", 0),
            "loc_added_sum": item.get("loc_added_sum", 0),
        }
        for r in mine
        for item in (r.get("totals_by_model_feature") or [])
    ]
    # One raw cell per day per (model, feature) pair; merge across the 28
    # days before handing them to the matrix/rows builders, which expect one
    # entry per pair already totalled for the period.
    merged: dict[tuple[str, str], dict] = {}
    for c in cells:
        key = (c["row"], c["col"])
        m = merged.setdefault(key, {
            "row": c["row"], "col": c["col"],
            "user_initiated_interaction_count": 0, "code_generation_activity_count": 0,
            "code_acceptance_activity_count": 0, "loc_added_sum": 0,
        })
        m["user_initiated_interaction_count"] += c["user_initiated_interaction_count"]
        m["code_generation_activity_count"] += c["code_generation_activity_count"]
        m["code_acceptance_activity_count"] += c["code_acceptance_activity_count"]
        m["loc_added_sum"] += c["loc_added_sum"]
    cells = list(merged.values())

    cp = await copilot_seats()
    seat = (cp.get("activity_by_login") or {}).get(login_lower)

    spend = await copilot_spend()
    budget = next((p for p in spend.get("people", []) if p["login"].lower() == login_lower), None)
    pacing = None
    if budget and budget.get("pct_used") is not None:
        pacing = _pace_status(budget["pct_used"], date.today())

    return {
        "login": login,
        "report_start_day": mine[0].get("report_start_day"),
        "report_end_day": mine[0].get("report_end_day"),
        "active_days": len(mine),
        "interactions": interactions,
        "generations": generations,
        "acceptances": acceptances,
        "acceptance_rate": round(acceptances / generations * 100, 1) if generations else None,
        "lines_added": lines_added,
        "lines_suggested": lines_suggested,
        "line_acceptance_rate": round(lines_added / lines_suggested * 100, 1) if lines_suggested else None,
        "ai_credits_used": ai_credits_used,
        "seat": seat,
        "budget": budget,
        "budget_pacing": pacing,
        "model_feature_matrix": _build_model_feature_matrix(cells),
        "model_feature_rows": _model_feature_rows(cells),
        "error": None,
    }



# ─── Team Copilot reporting ───────────────────────────────────────────────────

# Column order for the CSV, and the labels the report is read with.
TEAM_REPORT_COLUMNS = [
    ("login", "GitHub login"),
    ("name", "Name"),
    ("email", "Email"),
    ("eua", "EUA"),
    ("organization", "Organization"),
    ("status", "Copilot status"),
    ("idle_days", "Days since last Copilot use"),
    ("editor", "Editor"),
    ("credit_budget", "Dedicated credit budget"),
    ("blocks_at_cap", "Blocks at cap"),
]


async def enterprise_teams() -> dict:
    """The enterprise teams, with how many members each has.

    These are what the billing cost centers point at, so they are the unit a
    Copilot report is worth running over.
    """
    cached = _cached("ent_teams")
    if cached is not None:
        return cached

    settings = get_settings()
    ent = settings.GITHUB_ENTERPRISE_SLUG
    if not _has_billing_token() or not ent:
        return {"error": "GitHub token or enterprise slug is not configured", "teams": []}

    try:
        async with httpx.AsyncClient(timeout=90, headers=_billing_headers()) as client:
            teams: list[dict] = []
            for page in range(1, 6):
                r = await client.get(f"{_API}/enterprises/{ent}/teams",
                                     params={"per_page": 100, "page": page})
                if r.status_code != 200:
                    raise RuntimeError(f"GitHub returned {r.status_code}")
                batch = r.json()
                teams.extend(batch)
                if len(batch) < 100:
                    break

            async def count(slug: str) -> int:
                total = 0
                for page in range(1, 12):
                    r = await client.get(
                        f"{_API}/enterprises/{ent}/teams/{slug}/memberships",
                        params={"per_page": 100, "page": page})
                    if r.status_code != 200:
                        return total
                    batch = r.json()
                    total += len(batch)
                    if len(batch) < 100:
                        break
                return total

            rows = []
            for t in teams:
                slug = (t.get("slug") or "").replace("ent:", "")
                rows.append({"slug": slug, "name": t.get("name"),
                             "members": await count(slug),
                             "created_at": t.get("created_at")})
    except Exception as exc:  # noqa: BLE001
        logger.warning("Enterprise team list failed: %s", exc)
        return {"error": str(exc)[:200], "teams": []}

    rows.sort(key=lambda r: -r["members"])
    return _store("ent_teams", {"enterprise": ent, "teams": rows, "error": None})


def _copilot_status(row: dict, threshold: int) -> str:
    if not row["has_seat"]:
        return "No Copilot seat"
    if row["never_used"]:
        return "Never used"
    if row["idle_days"] is None:
        return "Unknown"
    if row["idle_days"] >= threshold:
        return f"Idle {row['idle_days']}d"
    return "Active"


async def team_copilot_report(team_slug: str) -> dict:
    """Copilot adoption for one enterprise team, a row per member.

    Joins three sources: the team's membership, each seat's last activity, and
    the per-user AI-credit budgets. Identity comes from the enterprise
    consumed-licenses report mapped through AD, because a Copilot seat carries
    only a GitHub login and those are largely vendor handles.

    Rows are ordered so the ones needing attention come first: no seat, then
    never used, then longest idle, then active.
    """
    settings = get_settings()
    ent = settings.GITHUB_ENTERPRISE_SLUG
    slug = (team_slug or "").replace("ent:", "").strip()
    if not _has_billing_token() or not ent:
        return {"error": "GitHub token or enterprise slug is not configured", "rows": []}
    if not slug:
        return {"error": "No team was named.", "rows": []}

    try:
        async with httpx.AsyncClient(timeout=120, headers=_billing_headers()) as client:
            members: list[dict] = []
            for page in range(1, 12):
                r = await client.get(f"{_API}/enterprises/{ent}/teams/{slug}/memberships",
                                     params={"per_page": 100, "page": page})
                if r.status_code == 404:
                    return {"error": f"No enterprise team called {slug!r}.", "rows": []}
                if r.status_code != 200:
                    raise RuntimeError(f"GitHub returned {r.status_code}")
                batch = r.json()
                members.extend(batch)
                if len(batch) < 100:
                    break
            logins = [m["login"] for m in members if m.get("login")]

            br = await client.get(f"{_API}/enterprises/{ent}/settings/billing/budgets")
            budgets = br.json().get("budgets", []) if br.status_code == 200 else []
    except Exception as exc:  # noqa: BLE001
        logger.warning("Team Copilot report failed for %s: %s", slug, exc)
        return {"error": str(exc)[:200], "rows": []}

    cp = await copilot_seats()
    activity = cp.get("activity_by_login") or {}
    threshold = cp.get("idle_days_threshold", _COPILOT_IDLE_DAYS)
    identities = (await copilot_identities(logins))["identities"] if logins else {}
    budget_by_login = {
        (b.get("budget_entity_name") or "").lower(): b for b in budgets
        if b.get("budget_product_sku") == _AI_CREDIT_SKU and b.get("budget_scope") == "user"
    }

    rows = []
    for login in logins:
        seat = activity.get(login.lower())
        ident = identities.get(login, {})
        budget = budget_by_login.get(login.lower())
        row = {
            "login": login,
            "name": ident.get("name"),
            "email": ident.get("email"),
            "eua": (ident.get("eua") or "").upper() or None,
            "organization": (seat or {}).get("organization"),
            "has_seat": seat is not None,
            "never_used": bool(seat and seat.get("never_used")),
            "idle_days": (seat or {}).get("idle_days"),
            "editor": (seat or {}).get("editor"),
            "credit_budget": (budget or {}).get("budget_amount"),
            "blocks_at_cap": bool(budget and budget.get("prevent_further_usage")),
        }
        row["status"] = _copilot_status(row, threshold)
        rows.append(row)

    rank = {"No Copilot seat": 0, "Never used": 1, "Unknown": 2}
    rows.sort(key=lambda r: (
        rank.get(r["status"], 3 if r["status"].startswith("Idle") else 4),
        -(r["idle_days"] or 0) if r["status"].startswith("Idle") else 0,
        r["login"].lower(),
    ))

    return {
        "enterprise": ent,
        "team": f"ent:{slug}",
        "members": len(rows),
        "idle_days_threshold": threshold,
        "with_seat": sum(1 for r in rows if r["has_seat"]),
        "no_seat": sum(1 for r in rows if not r["has_seat"]),
        "active": sum(1 for r in rows if r["status"] == "Active"),
        "never_used": sum(1 for r in rows if r["never_used"]),
        "idle": sum(1 for r in rows if r["status"].startswith("Idle")),
        "with_budget": sum(1 for r in rows if r["credit_budget"]),
        "identities_resolved": sum(1 for r in rows if r["email"]),
        "rows": rows,
        "error": None,
    }


def team_report_csv(report: dict) -> str:
    """Render a report as CSV, in TEAM_REPORT_COLUMNS order."""
    import csv
    import io
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([label for _, label in TEAM_REPORT_COLUMNS])
    for row in report.get("rows", []):
        out = []
        for key, _ in TEAM_REPORT_COLUMNS:
            v = row.get(key)
            if key == "blocks_at_cap":
                v = "yes" if v else ""
            out.append("" if v is None else v)
        w.writerow(out)
    return buf.getvalue()


# ─── Enterprise license consumption ───────────────────────────────────────────

async def license_usage() -> dict:
    """Seats purchased against seats consumed across the enterprise."""
    cached = _cached("licenses")
    if cached:
        return cached

    settings = get_settings()
    ent = settings.GITHUB_ENTERPRISE_SLUG
    if not _has_billing_token() or not ent:
        return {"error": "GitHub token or enterprise slug is not configured"}

    try:
        async with httpx.AsyncClient(timeout=40, headers=_billing_headers()) as client:
            r = await client.get(f"{_API}/enterprises/{ent}/consumed-licenses",
                                 params={"per_page": 1})
            r.raise_for_status()
            d = r.json()
    except Exception as exc:  # noqa: BLE001
        logger.warning("License usage read failed: %s", exc)
        return {"error": str(exc)[:200]}

    purchased = d.get("total_seats_purchased") or 0
    consumed = d.get("total_seats_consumed") or 0
    return _store("licenses", {
        "enterprise": ent,
        "purchased": purchased,
        "consumed": consumed,
        "available": max(purchased - consumed, 0),
        "used_pct": round(consumed / purchased * 100, 1) if purchased else 0.0,
        "error": None,
    })
