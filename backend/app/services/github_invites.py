"""Bulk GitHub org invitations (POST /orgs/{org}/invitations), sent with the
inviting engineer's own PAT -- GitHub attributes "Invited by" to whichever
credential makes the call, so this requires a personal PAT (source == "user")
and refuses to fall back to the shared service account.

There's no bulk-invite endpoint on GitHub's side -- one call per email --
so a batch of any real size runs as a background job (bulk_job) instead of
blocking the request: start_bulk_invite validates and kicks it off, the
worker sends each email and reports progress as it goes, then does one
more pass over whatever failed before finishing, so a transient run of
failures near the end of a long batch gets a second try after things have
had a chance to cool down."""
from __future__ import annotations

import logging
import time

import httpx

from app.config import get_settings
from app.services import audit, bulk_job, bulk_report, github_auth
from app.services.github_http import GH_API, auth_headers, error_detail, request_with_retry

logger = logging.getLogger(__name__)

# cms-enterprise-all-users, matching the desktop script's default. Resolved
# by slug via resolve_team_id() below rather than a hardcoded numeric id --
# a team recreated under the same name gets a new id, which would silently
# break every default-team invite until someone noticed and updated a
# hardcoded constant.
DEFAULT_TEAM_SLUG = "cms-enterprise-all-users"

_ROLE_MAP = {"member": "direct_member", "owner": "admin"}


def resolve_team_id(token: str, org: str, team_slug: str) -> dict:
    """Look up a team's numeric id from its slug."""
    try:
        r = httpx.get(f"{GH_API}/orgs/{org}/teams/{team_slug}", headers=auth_headers(token), timeout=15)
    except httpx.RequestError as exc:
        return {"ok": False, "error": f"Could not reach GitHub: {exc}"}
    if r.status_code != 200:
        return {"ok": False, "error": f"No team '{team_slug}' in {org} (GitHub returned {r.status_code})."}
    return {"ok": True, "id": r.json()["id"], "slug": r.json()["slug"]}


def _send_one(token: str, org: str, email: str, role: str, team_ids: list[int]) -> dict:
    try:
        r = request_with_retry(
            "POST", f"{GH_API}/orgs/{org}/invitations",
            headers=auth_headers(token),
            json={"email": email, "role": role, "team_ids": team_ids},
            timeout=15,
        )
    except httpx.RequestError as exc:
        return {"email": email, "ok": False, "error": f"Could not reach GitHub: {exc}"}

    if r.status_code in (200, 201):
        body = r.json()
        return {"email": email, "ok": True, "invitation_id": body.get("id"), "role": body.get("role")}
    return {"email": email, "ok": False, "error": f"GitHub {r.status_code}: {error_detail(r)}"}


def start_bulk_invite(
    username: str,
    emails: list[str],
    role: str = "member",
    team_slug: str | None = None,
    approval_note: str = "",
    org: str | None = None,
) -> str:
    """Validates eligibility and resolves the team synchronously (fast),
    then hands the actual sends to a background job and returns its id.
    Raises ValueError when the caller has no personal PAT on file, or the
    named team doesn't resolve.

    `org` defaults to the configured GITHUB_ORG. The default team id is
    specific to that org, so on any other org an invite goes out without a
    team grant unless `team_slug` is given explicitly."""
    auth = github_auth.resolve_github_auth(username)
    if auth["source"] != "user":
        raise ValueError(
            "No usable GitHub PAT on file for you. Save one with org-invite "
            "permission (classic PAT scope admin:org, or a fine-grained PAT "
            "with the Members: write org permission) under Profile -> GitHub PAT, "
            "then try again."
        )

    settings = get_settings()
    org = (org or settings.GITHUB_ORG).strip()
    is_default_org = org.casefold() == settings.GITHUB_ORG.casefold()
    token = auth["token"]

    team_id: int | None = None
    team_label: str | None = None
    effective_slug = team_slug or (DEFAULT_TEAM_SLUG if is_default_org else None)
    if effective_slug:
        looked_up = resolve_team_id(token, org, effective_slug)
        if not looked_up["ok"]:
            raise ValueError(looked_up["error"])
        team_id, team_label = looked_up["id"], looked_up["slug"]

    gh_role = _ROLE_MAP.get(role, "direct_member")
    team_ids = [team_id] if team_id else []

    job_id = bulk_job.new_job("org_invite", username, len(emails))
    bulk_job.set_extra(job_id, invited_by=auth.get("login"), org=org, team=team_label, role=role)
    bulk_job.run_in_background(
        _invite_worker, job_id, username, auth.get("login"),
        token, org, emails, gh_role, team_ids, team_label, role, approval_note,
    )
    return job_id


def _invite_worker(
    job_id: str, username: str, login: str | None, token: str, org: str,
    emails: list[str], gh_role: str, team_ids: list[int], team_label: str | None,
    role: str, approval_note: str,
) -> None:
    try:
        results = []
        for email in emails:
            bulk_job.set_current(job_id, email)
            result = _send_one(token, org, email, gh_role, team_ids)
            results.append(result)
            bulk_job.append_result(job_id, result)

        failed = [r for r in results if not r["ok"]]
        if failed:
            time.sleep(5)  # let any sustained rate limit cool off before the retry pass
            for i, r in enumerate(results):
                if not r["ok"]:
                    bulk_job.set_current(job_id, f"retrying {r['email']}")
                    results[i] = _send_one(token, org, r["email"], gh_role, team_ids)
            bulk_job.replace_results(job_id, results)

        sent = [r for r in results if r["ok"]]
        failed_final = [r for r in results if not r["ok"]]

        audit.log_event(
            "github.org_invite",
            username,
            details={
                "org": org, "role": role, "team": team_label, "approval_note": approval_note,
                "requested": len(emails), "sent": len(sent), "failed": len(failed_final), "emails": emails,
            },
        )
        logger.info(
            "Org invite by %s (%s): %d/%d sent, team=%s, role=%s",
            username, login or username, len(sent), len(emails), team_label, role,
        )
        bulk_job.finish(job_id)
        bulk_report.send_completion_report(
            title=f"GitHub org invite batch finished — {org}",
            by=login or username,
            lines=[
                f"*Sent:* {len(sent)}/{len(emails)}",
                f"*Failed:* {len(failed_final)}",
                f"*Role:* {role}  *Team:* {team_label or '(none)'}",
            ],
            failures=[(r["email"], r["error"] or "unknown error") for r in failed_final],
        )
    except Exception as exc:  # noqa: BLE001 -- never let the worker thread die silently
        logger.exception("Org invite job %s failed", job_id)
        bulk_job.finish(job_id, error=str(exc))
        bulk_report.send_crash_report("org invite", username, str(exc))


def can_send(username: str) -> dict:
    """Whether this user has a personal PAT on file to send invites with --
    used by the UI to show/hide the invite form before anyone fills it out."""
    return github_auth.has_personal_pat(username)
