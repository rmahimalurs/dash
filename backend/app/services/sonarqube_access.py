"""SonarQube user-access lookup.

Answers "does this user have access to SonarQube, and to what projects?" using the
admin Basic-auth credentials already configured for the license check.

CMS SonarQube grants project access by GROUP, not by direct user→project
permission (users carry empty project permissions; access flows through
`<app>-users` / `<app>-administrators` groups, one pair per application, created
per Jira ticket). Every authenticated user is also in the default `sonar-users`
group. So a user's group memberships map directly to the applications/projects
they can reach and whether they are a member or an administrator of each.
"""
from __future__ import annotations

import logging

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

_TIMEOUT = 25.0
_BASELINE_GROUP = "sonar-users"  # default group every authenticated user is in
_ROLE_RANK = {"member": 0, "user": 1, "admin": 2}


def _env_conf(env: str) -> tuple[str, str, str]:
    """Return (base_url, user, password) for the given SonarQube env."""
    s = get_settings()
    if env == "prod":
        return s.SONARQUBE_PROD_URL.rstrip("/"), s.SONARQUBE_PROD_USER, s.SONARQUBE_PROD_PASSWORD
    if env == "dev":
        return s.SONARQUBE_DEV_URL.rstrip("/"), s.SONARQUBE_DEV_USER, s.SONARQUBE_DEV_PASSWORD
    raise ValueError("env must be 'dev' or 'prod'")


def _applications_from_groups(groups: list[str]) -> list[dict]:
    """Collapse `<app>-users` / `<app>-administrators` group names into a list of
    {application, role} entries (admin outranks user). Non-conforming groups are
    surfaced as role 'member'. The baseline `sonar-users` group is excluded."""
    apps: dict[str, str] = {}
    for g in groups:
        if g == _BASELINE_GROUP:
            continue
        if g.endswith("-administrators"):
            app, role = g[: -len("-administrators")], "admin"
        elif g.endswith("-users"):
            app, role = g[: -len("-users")], "user"
        else:
            app, role = g, "member"
        cur = apps.get(app)
        if cur is None or _ROLE_RANK[role] > _ROLE_RANK[cur]:
            apps[app] = role
    return [{"application": a, "role": apps[a]} for a in sorted(apps)]


def _search_users(base: str, auth: tuple[str, str], q: str, ps: int = 50) -> list[dict]:
    """Free-text SonarQube user search — matches login, name, and email (NOT the
    externalIdentity/EUA)."""
    r = httpx.get(
        f"{base}/api/users/search", auth=auth, params={"q": q, "ps": ps}, timeout=_TIMEOUT
    )
    r.raise_for_status()
    return r.json().get("users", [])


def _scan_by_eua(base: str, auth: tuple[str, str], eua: str) -> dict | None:
    """Find a user whose externalIdentity (the CMS EUA, e.g. 'sbs2') equals `eua`.
    SonarQube's q param does NOT search externalIdentity, so this paginates the
    full user list (ps=500) and matches locally. Returns the first match."""
    eua_l = eua.lower()
    page = 1
    while True:
        r = httpx.get(
            f"{base}/api/users/search", auth=auth, params={"ps": 500, "p": page}, timeout=_TIMEOUT
        )
        r.raise_for_status()
        data = r.json()
        for u in data.get("users", []):
            if (u.get("externalIdentity") or "").lower() == eua_l:
                return u
        paging = data.get("paging", {})
        if paging.get("pageIndex", page) * paging.get("pageSize", 500) >= paging.get("total", 0):
            return None
        page += 1


def _candidate(u: dict) -> dict:
    return {
        "login": u.get("login"),
        "name": u.get("name"),
        "email": u.get("email"),
        "eua": u.get("externalIdentity"),
        "active": bool(u.get("active", False)),
    }


def _users_by_email(base: str, auth: tuple[str, str], email: str, exclude_login: str | None = None) -> list[dict]:
    """SonarQube accounts whose email exactly matches `email` (case-insensitive),
    excluding `exclude_login`. Used to detect the shared-email collisions that
    silently block LDAP auto-provisioning (SonarQube requires unique emails)."""
    if not email:
        return []
    users = _search_users(base, auth, email, ps=25)
    el = email.lower()
    return [
        {"login": u.get("login"), "name": u.get("name"), "eua": u.get("externalIdentity"),
         "active": bool(u.get("active", False))}
        for u in users
        if (u.get("email") or "").lower() == el and u.get("login") != exclude_login
    ]


def _ad_identity(sam: str) -> dict | None:
    """Best-effort AD lookup of an EUA → {email, name}. Single service-account
    bind (no lockout risk); returns None if AD is unreachable or the EUA isn't
    found. Used to diagnose why a not-yet-provisioned user can't log in."""
    import re

    if not sam or not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", sam):
        return None
    try:
        import ldap3
        from app.services import ad_unlock as au

        s = get_settings()
        conn = au._connect(s, au._unlock_url(s))
        try:
            base = s.AD_UNLOCK_SEARCH_BASE or au._domain_root(s.LDAP_BASE_DN)
            conn.search(base, f"(sAMAccountName={sam})", ldap3.SUBTREE, attributes=["mail", "displayName"])
            if not conn.entries:
                return None
            e = conn.entries[0]
            return {"email": (e.mail.value or None), "name": (e.displayName.value or None)}
        finally:
            conn.unbind()
    except Exception as exc:  # noqa: BLE001 — diagnostics only, never block the lookup
        logger.warning("AD email lookup failed for %s: %s", sam, exc)
        return None


def _fetch_user_groups(base: str, auth: tuple[str, str], login: str) -> list[str]:
    """All groups the user belongs to (paginated, selected only)."""
    names: list[str] = []
    page = 1
    while True:
        r = httpx.get(
            f"{base}/api/users/groups",
            auth=auth,
            params={"login": login, "selected": "selected", "ps": 500, "p": page},
            timeout=_TIMEOUT,
        )
        r.raise_for_status()
        data = r.json()
        names.extend(g.get("name") for g in data.get("groups", []) if g.get("name"))
        paging = data.get("paging", {})
        if paging.get("pageIndex", page) * paging.get("pageSize", 500) >= paging.get("total", 0):
            break
        page += 1
    return names


def get_user_access(env: str, login: str) -> dict:
    """Look up a user's SonarQube access. Never raises for a missing user —
    returns {found: False} with lookalike logins to help typo diagnosis."""
    base, user, password = _env_conf(env)
    if not user or not password:
        return {
            "configured": False,
            "env": env,
            "login": login,
            "message": f"SonarQube {env} admin credentials are not configured on the dashboard.",
        }

    query = login.strip()
    auth = (user, password)

    # Text search matches login/name/email. Accept the query as a login OR an EUA
    # (externalIdentity): SonarQube logins are inconsistent — some are the EUA
    # (a1hr), some are a full-name form (srikanth-rao-sharikar82151) whose EUA
    # lives in externalIdentity.
    users = _search_users(base, auth, query)
    ql = query.lower()
    match = next(
        (u for u in users
         if (u.get("login") or "").lower() == ql or (u.get("externalIdentity") or "").lower() == ql),
        None,
    )

    # No exact hit in the text results — the query may be an EUA the q param can't
    # see. Scan the full user list by externalIdentity.
    if not match:
        match = _scan_by_eua(base, auth, query)

    if not match:
        # Multiple/near matches from the text search → let the caller disambiguate.
        if users:
            return {
                "configured": True,
                "found": False,
                "ambiguous": True,
                "env": env,
                "login": query,
                "candidates": [_candidate(u) for u in users[:15]],
                "message": (
                    f'No exact match for "{query}". {len(users)} similar user(s) found — '
                    "pick one (search by login, EUA, name, or email)."
                ),
            }
        # Not provisioned in SonarQube. A common cause is an email collision: the
        # user authenticates fine against LDAP, but SonarQube can't create their
        # account because another account already owns their AD email (SonarQube
        # requires unique emails). Resolve their AD email and check for it.
        collision = None
        ad = _ad_identity(query)
        if ad and ad.get("email"):
            conflicting = _users_by_email(base, auth, ad["email"])
            if conflicting:
                collision = {
                    "ad_email": ad["email"],
                    "ad_name": ad.get("name"),
                    "conflicting": conflicting,
                }
        if collision:
            who = ", ".join(c["login"] for c in collision["conflicting"])
            msg = (
                f'{collision.get("ad_name") or query} is not provisioned in SonarQube. Their AD '
                f'email {collision["ad_email"]} is already used by account(s) {who} — SonarQube '
                "requires unique emails, so this blocks their login. Free the email on that "
                "account to let them sign in."
            )
        else:
            msg = f'No SonarQube user found matching "{query}" (login, EUA, name, or email).'
        return {
            "configured": True,
            "found": False,
            "ambiguous": False,
            "env": env,
            "login": query,
            "similar": [],
            "email_collision": collision,
            "message": msg,
        }

    groups = sorted(_fetch_user_groups(base, auth, match["login"]))
    applications = _applications_from_groups(groups)
    admin_apps = [a["application"] for a in applications if a["role"] == "admin"]
    email_shared_with = _users_by_email(base, auth, match.get("email"), exclude_login=match.get("login"))

    return {
        "configured": True,
        "found": True,
        "env": env,
        "login": match.get("login"),
        "name": match.get("name"),
        "email": match.get("email"),
        "email_shared_with": email_shared_with,
        "eua": match.get("externalIdentity"),
        "active": bool(match.get("active", False)),
        "local": bool(match.get("local", False)),
        "external_provider": match.get("externalProvider"),
        "external_identity": match.get("externalIdentity"),
        "last_connection": match.get("lastConnectionDate"),
        "tokens_count": match.get("tokensCount"),
        "in_baseline_group": _BASELINE_GROUP in groups,
        "groups": groups,
        "applications": applications,
        "application_count": len(applications),
        "admin_count": len(admin_apps),
        "message": (
            f"{match.get('login')} is provisioned and has access to "
            f"{len(applications)} application project(s)"
            + (f" ({len(admin_apps)} as administrator)" if admin_apps else "")
            + "."
            if applications
            else f"{match.get('login')} is provisioned but has no application project access "
            f"beyond the baseline sonar-users group."
        ),
    }
