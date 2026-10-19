"""Bulk GitHub repo creation with the team's standard baseline access, sent
with the creating engineer's own PAT (never the shared service account),
per the runbook "How to create a GitHub Repository"
(confluenceent.cms.gov/spaces/COM/pages/1503987924): create it private,
grant the 3 baseline teams and the GitHub/Jira service account Admin, then
the repo's own requestor (and any extra admins) Admin.

Unlike the desktop script this is ported from, which takes one requestor
for the whole batch, this accepts one requestor (+ optional extra admins)
*per repo*, since a single dashboard batch may genuinely be "x, y, z for
Jane" one time and "x for John, y for Sam" the next.
"""
from __future__ import annotations

import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor

import httpx

from app.config import get_settings
from app.services import audit, bulk_job, bulk_report, cldspt_tickets, github_auth
from app.services.github_copilot_seats import MEMBER_ACTIVE, get_membership_state
from app.services.github_http import GH_API, auth_headers, error_detail, request_with_retry

logger = logging.getLogger(__name__)

BASELINE_TEAMS = [
    "cms-cloud-internal",
    "cms-enterprise-allrepo-access-serviceaccounts",
    "cms-security-managers",
]

# The GitHub/Jira integration service account -- an individual user, not a
# team, despite the runbook listing it as a 4th "team" grant (confirmed
# live: no team by that name exists).
BASELINE_USER = "cms-enterprise-githubjira"

REPO_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def user_confirmed_missing(token: str, handle: str) -> bool:
    """True only for a real, confirmed 404 -- a network error, rate limit,
    or any other non-200/404 status is inconclusive and must not be treated
    the same as "doesn't exist": that would wrongly block every repo for a
    requestor/admin sharing that handle on a transient GitHub hiccup, with
    no retry (an invalid-handle result is explicitly not retried). When
    inconclusive, the handle is left alone and the real grant call later is
    what actually decides, rather than a guess made here."""
    try:
        r = httpx.get(f"{GH_API}/users/{handle}", headers=auth_headers(token), timeout=15)
    except httpx.RequestError:
        return False
    return r.status_code == 404


def repo_exists(token: str, org: str, name: str) -> bool:
    try:
        r = httpx.get(f"{GH_API}/repos/{org}/{name}", headers=auth_headers(token), timeout=15)
    except httpx.RequestError:
        return False
    return r.status_code == 200


def _create_repo(token: str, org: str, name: str) -> dict:
    try:
        r = request_with_retry(
            "POST", f"{GH_API}/orgs/{org}/repos",
            headers=auth_headers(token),
            json={"name": name, "private": True},
            timeout=20,
        )
    except httpx.RequestError as exc:
        return {"created": False, "error": f"could not reach GitHub: {exc}"}
    if r.status_code not in (200, 201):
        return {"created": False, "error": f"GitHub {r.status_code}: {error_detail(r)}"}
    return {"created": True, "error": None}


def _grant_admin(token: str, org: str, path: str) -> dict:
    """PUT an admin-permission grant at `path` (a team-repo or collaborator
    URL). Returns {ok, error}."""
    try:
        r = request_with_retry(
            "PUT", f"{GH_API}/{path}", headers=auth_headers(token), json={"permission": "admin"}, timeout=15,
        )
    except httpx.RequestError as exc:
        return {"ok": False, "error": f"could not reach GitHub: {exc}"}
    if r.status_code in (200, 201, 204):
        return {"ok": True, "error": None}
    return {"ok": False, "error": f"GitHub {r.status_code}: {error_detail(r)}"}


def _verify_team_admin(token: str, org: str, team_slug: str, name: str) -> bool:
    """Reads back whether `team_slug` actually holds Admin on the repo now,
    rather than trusting the grant PUT's 204 as proof it took effect.

    This endpoint only returns the repository body (with the `permissions`
    object checked below) when asked for the `vnd.github.v3.repository+json`
    media type; with the plain Accept header every other call in this file
    uses, a successful check returns 204 with no body instead of 200, which
    would otherwise make every real grant look unverified."""
    headers = {**auth_headers(token), "Accept": "application/vnd.github.v3.repository+json"}
    try:
        r = httpx.get(f"{GH_API}/orgs/{org}/teams/{team_slug}/repos/{org}/{name}", headers=headers, timeout=15)
    except httpx.RequestError:
        return False
    if r.status_code != 200:
        return False
    try:
        return bool(r.json().get("permissions", {}).get("admin"))
    except Exception:  # noqa: BLE001
        return False


def _verify_collaborator_admin(token: str, org: str, name: str, username: str) -> bool:
    """Reads back whether `username` actually holds Admin on the repo now."""
    try:
        r = httpx.get(f"{GH_API}/repos/{org}/{name}/collaborators/{username}/permission",
                      headers=auth_headers(token), timeout=15)
    except httpx.RequestError:
        return False
    if r.status_code != 200:
        return False
    try:
        return r.json().get("permission") == "admin"
    except Exception:  # noqa: BLE001
        return False


def _add_team(token: str, org: str, team_slug: str, name: str) -> dict:
    grant = _grant_admin(token, org, f"orgs/{org}/teams/{team_slug}/repos/{org}/{name}")
    verified = _verify_team_admin(token, org, team_slug, name) if grant["ok"] else False
    return {"team": team_slug, **grant, "verified": verified}


def _add_collaborator(token: str, org: str, name: str, username: str, role: str) -> dict:
    grant = _grant_admin(token, org, f"repos/{org}/{name}/collaborators/{username}")
    verified = _verify_collaborator_admin(token, org, name, username) if grant["ok"] else False
    return {"username": username, "role": role, **grant, "verified": verified}


def _empty_result(name: str, requestor: str, extra_admins: list[str], **overrides) -> dict:
    base = {
        "name": name, "requestor": requestor, "extra_admins": extra_admins,
        "ok": False, "repo_created": False, "repo_already_existed": False,
        "repo_error": None, "teams": [], "collaborators": [], "invalid_handles": [],
        "skipped_non_members": [],
    }
    base.update(overrides)
    return base


def _create_one(
    token: str, org: str, spec: dict, known_bad_handles: set[str], member_handles: set[str], force_existing: bool,
    created_this_run: set[str] | None = None,
) -> dict:
    name = spec["name"]
    requestor = spec["requestor"]
    extra_admins = spec.get("extra_admins") or []
    created_this_run = created_this_run if created_this_run is not None else set()

    if not REPO_NAME_RE.match(name):
        return _empty_result(name, requestor, extra_admins,
                              repo_error="invalid repo name (letters/digits/._- only)")

    # A handle GitHub doesn't recognize at all is almost certainly a typo in
    # the request itself -- that blocks the whole repo, same as before.
    invalid_handles = [h for h in [requestor, *extra_admins] if h in known_bad_handles]
    if invalid_handles:
        return _empty_result(name, requestor, extra_admins, invalid_handles=invalid_handles)

    # A handle that's a real GitHub user but not a *confirmed active* org
    # member is different: adding them as a repo collaborator would have
    # GitHub send them a direct invite, skipping the org's own access-request
    # approval process entirely. That's never attempted here -- the repo and
    # everyone who *is* a confirmed member still go through; whoever isn't
    # gets reported separately so they can be added once they're approved
    # into the org through the normal process, instead of blocking the repo
    # on an org-membership decision that isn't this feature's to make.
    # Pending invites and a lookup that couldn't confirm membership either
    # way are treated the same as "not a member" here, not as "probably
    # fine" -- the risk of wrongly sending an invite outside the approval
    # process outweighs the inconvenience of a conservative skip.
    skipped_non_members = [
        h for h in [requestor, *extra_admins] if h not in known_bad_handles and h not in member_handles
    ]

    # A name this very job already created (e.g. the repo succeeded but a
    # grant failed, and this is the retry pass) is never a real collision --
    # only treat a pre-existing name found for the first time as one.
    already_existed = name not in created_this_run and repo_exists(token, org, name)
    if already_existed and not force_existing:
        return _empty_result(
            name, requestor, extra_admins, repo_already_existed=True,
            repo_error=(
                f"A repo named '{name}' already exists in {org}. Nothing was changed -- pick a "
                "different name, or re-run with this one checked to confirm you want to re-apply "
                "the baseline access to the existing repo."
            ),
        )

    if not already_existed and name not in created_this_run:
        repo_result = _create_repo(token, org, name)
        if repo_result["error"]:
            return _empty_result(name, requestor, extra_admins, repo_error=repo_result["error"])
        created_this_run.add(name)

    teams = [_add_team(token, org, slug, name) for slug in BASELINE_TEAMS]
    collaborators = [_add_collaborator(token, org, name, BASELINE_USER, "baseline_service_account")]
    if requestor in member_handles:
        collaborators.append(_add_collaborator(token, org, name, requestor, "requestor"))
    for admin in extra_admins:
        if admin in member_handles:
            collaborators.append(_add_collaborator(token, org, name, admin, "extra_admin"))

    ok = all(t["ok"] and t["verified"] for t in teams) and all(c["ok"] and c["verified"] for c in collaborators)
    return {
        "name": name, "requestor": requestor, "extra_admins": extra_admins,
        "ok": ok,
        "repo_created": not already_existed,
        "repo_already_existed": already_existed,
        "repo_error": None,
        "teams": teams,
        "collaborators": collaborators,
        "invalid_handles": [],
        "skipped_non_members": skipped_non_members,
    }


def _is_retryable(r: dict) -> bool:
    """Worth another attempt: a real GitHub failure on create or a grant.
    Not worth it: an invalid name/handle (won't change on retry), or a
    deliberate "already exists, not forced" stop (retrying just reproduces
    the same stop)."""
    if r["ok"] or r["invalid_handles"]:
        return False
    return not (r["repo_already_existed"] and r["repo_error"])


def _failure_reason(r: dict) -> str:
    """repo_error is None for an invalid-handle result (nothing was ever
    attempted), the same as it is when every grant actually ran but one
    failed -- checking invalid_handles first keeps those two from being
    reported with the same "grant failed" wording when nothing was
    attempted in the first case."""
    if r["invalid_handles"]:
        return f"unknown GitHub handle(s), nothing attempted: {', '.join(r['invalid_handles'])}"
    return r["repo_error"] or "grant failed or unverified"


def start_bulk_create(username: str, specs: list[dict], force_existing: bool = False) -> str:
    """Validates eligibility synchronously (fast), then hands the per-repo
    create+grant+verify work to a background job and returns its id.
    Raises ValueError when the caller has no personal PAT on file.

    `force_existing` controls what happens when a name already exists in
    the org: by default this stops and reports it rather than granting
    access to a repo that might not even be the one the requestor meant --
    pass True only when re-applying access to a repo you already know is
    yours (e.g. retrying after a prior run partly failed)."""
    auth = github_auth.resolve_github_auth(username)
    if auth["source"] != "user":
        raise ValueError(
            "No usable GitHub PAT on file for you. Save one with org-admin and "
            "repo permission (classic PAT scopes admin:org, repo) under Profile "
            "-> GitHub PAT, then try again."
        )
    token = auth["token"]
    org = get_settings().GITHUB_ORG

    job_id = bulk_job.new_job("repo_create", username, total=len(specs))
    bulk_job.set_extra(job_id, created_by=auth.get("login"), org=org)
    bulk_job.run_in_background(_repo_create_worker, job_id, username, auth.get("login"), token, org, specs, force_existing)
    return job_id


def _repo_create_worker(
    job_id: str, username: str, login: str | None, token: str, org: str,
    specs: list[dict], force_existing: bool,
) -> None:
    try:
        all_handles = sorted({h for s in specs for h in [s["requestor"], *(s.get("extra_admins") or [])]})
        with ThreadPoolExecutor(max_workers=8) as ex:
            missing = dict(ex.map(lambda h: (h, user_confirmed_missing(token, h)), all_handles))
            membership = dict(ex.map(lambda h: (h, get_membership_state(token, org, h)[0]), all_handles))
        known_bad_handles = {h for h, is_missing in missing.items() if is_missing}
        member_handles = {h for h, state in membership.items() if state == MEMBER_ACTIVE}

        created_this_run: set[str] = set()
        results = []
        for spec in specs:
            bulk_job.set_current(job_id, spec["name"])
            result = _create_one(token, org, spec, known_bad_handles, member_handles, force_existing, created_this_run)
            results.append(result)
            bulk_job.append_result(job_id, result)

        retryable = [i for i, r in enumerate(results) if _is_retryable(r)]
        if retryable:
            time.sleep(5)  # let any sustained rate limit cool off before the retry pass
            for i in retryable:
                spec = specs[i]
                bulk_job.set_current(job_id, f"retrying {spec['name']}")
                results[i] = _create_one(token, org, spec, known_bad_handles, member_handles, force_existing, created_this_run)
            bulk_job.replace_results(job_id, results)

        for spec, result in zip(specs, results):
            ticket_key = (spec.get("ticket_key") or "").strip()
            if ticket_key and result["skipped_non_members"]:
                try:
                    cldspt_tickets.notify_ticket_non_member_admins(
                        ticket_key, result["skipped_non_members"], result["name"],
                    )
                except Exception as exc:  # noqa: BLE001 -- a failed comment never blocks the repo result
                    logger.warning("Non-member ticket notice for %s (%s) failed: %s", ticket_key, spec["name"], exc)

        audit.log_event(
            "github.repo_create",
            username,
            details={
                "org": org,
                "requested": [{"name": s["name"], "requestor": s["requestor"],
                               "extra_admins": s.get("extra_admins") or []} for s in specs],
                "succeeded": [r["name"] for r in results if r["ok"]],
                "failed": [r["name"] for r in results if not r["ok"]],
            },
        )
        succeeded = [r for r in results if r["ok"]]
        skip_count = sum(len(r["skipped_non_members"]) for r in results)
        logger.info(
            "Repo create by %s (%s): %d/%d succeeded, %d admin grant(s) skipped for non-membership",
            username, login or username, len(succeeded), len(results), skip_count,
        )
        bulk_job.finish(job_id)
        lines = [f"*Succeeded:* {len(succeeded)}/{len(results)}"]
        if skip_count:
            lines.append(
                f"*Skipped (not org members yet):* {skip_count} -- repo(s) created, but not granted "
                "admin until they're approved into the org"
            )
        bulk_report.send_completion_report(
            title=f"GitHub repo creation batch finished — {org}",
            by=login or username,
            lines=lines,
            failures=[(r["name"], _failure_reason(r)) for r in results if not r["ok"]],
        )
    except Exception as exc:  # noqa: BLE001 -- never let the worker thread die silently
        logger.exception("Repo create job %s failed", job_id)
        bulk_job.finish(job_id, error=str(exc))
        bulk_report.send_crash_report("repo creation", username, str(exc))
