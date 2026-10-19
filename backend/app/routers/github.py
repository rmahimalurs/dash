import asyncio
import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field

from app.auth.jwt import get_current_user
from app.routers.admin import require_admin
from app.services import (
    audit,
    bulk_job,
    copilot_notify,
    github_analytics,
    github_auth,
    github_copilot_seats,
    github_invites,
    github_repo_create,
    github_status,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/github", tags=["github"])


class CopilotLogins(BaseModel):
    logins: list[str] = Field(default_factory=list, max_length=100)


class OrgInviteBody(BaseModel):
    # 500 is a blast-radius ceiling against a paste accident, not a
    # practical cap -- CopilotLogins/extra_admins already cap lower, this
    # just brings the previously-uncapped lists in line with that.
    emails: list[str] = Field(..., min_length=1, max_length=500)
    role: str = Field("member", pattern="^(member|owner)$")
    team: str = Field("", max_length=120)
    approval_note: str = Field(..., min_length=1, max_length=500)
    org: str = Field("", max_length=120)


class CopilotSeatAssignBody(BaseModel):
    handles: list[str] = Field(..., min_length=1, max_length=500)  # blast-radius ceiling, see OrgInviteBody
    org: str = Field("", max_length=120)


class RepoCreateSpec(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    requestor: str = Field(..., min_length=1, max_length=39)
    extra_admins: list[str] = Field(default_factory=list, max_length=20)
    # Optional: when this repo request came from a CLDSPT ticket, and
    # someone gets skipped for not being a confirmed org member yet, a
    # comment is posted there so the follow-up isn't only relying on memory.
    ticket_key: str = Field("", pattern=r"^$|^CLDSPT-\d+$")


class RepoCreateBody(BaseModel):
    specs: list[RepoCreateSpec] = Field(..., min_length=1, max_length=500)  # blast-radius ceiling, see OrgInviteBody
    force_existing: bool = False


@router.get("/capabilities")
async def get_capabilities(current_user: dict = Depends(get_current_user)):
    """Token identity, granted scopes, and which GitHub areas are reachable."""
    return await github_analytics.capabilities()


@router.get("/pull-requests")
async def get_pull_requests(
    scope: str = Query("team", pattern="^(team|org)$"),
    current_user: dict = Depends(get_current_user),
):
    """Open pull requests with review state, bucketed for the review board."""
    return await github_analytics.pull_requests(scope)


@router.get("/repos")
async def get_repos(
    limit: int = Query(15, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
):
    """Most recently pushed org repos."""
    return await github_analytics.repo_activity(limit)


@router.get("/copilot")
async def get_copilot(current_user: dict = Depends(get_current_user)):
    """Enterprise Copilot seats with the idle and never-used ones called out."""
    return await github_analytics.copilot_seats()


@router.get("/licenses")
async def get_licenses(current_user: dict = Depends(get_current_user)):
    """Enterprise seats purchased against seats consumed."""
    return await github_analytics.license_usage()


@router.post("/copilot/identities")
async def get_copilot_identities(
    body: CopilotLogins,
    current_user: dict = Depends(get_current_user),
):
    """Resolve Copilot logins to an email address so a reminder can be addressed."""
    resolved = await github_analytics.copilot_identities(body.logins)
    resolved["reminders"] = copilot_notify.reminder_history(list(resolved["identities"]))
    return resolved


@router.get("/copilot/power-users")
async def get_copilot_power_users(current_user: dict = Depends(get_current_user)):
    """Users with their own AI-credit budget, and whether they are using Copilot."""
    return await github_analytics.copilot_power_users()


@router.get("/copilot/spend")
async def get_copilot_spend(current_user: dict = Depends(get_current_user)):
    """Copilot AI-credit budgets by cost center/team, and individuals near their cap."""
    return await github_analytics.copilot_spend()


@router.get("/copilot/usage-adoption")
async def get_copilot_usage_adoption(current_user: dict = Depends(get_current_user)):
    """Enterprise-wide Copilot adoption over the trailing 28 days."""
    return await github_analytics.copilot_usage_adoption()


@router.get("/copilot/billing-spend")
async def get_copilot_billing_spend(current_user: dict = Depends(get_current_user)):
    """Actual metered billing spend for Copilot, by month and by SKU."""
    return await github_analytics.copilot_billing_spend()


@router.get("/copilot/people")
async def get_copilot_people(current_user: dict = Depends(get_current_user)):
    """Per-person Copilot activity over the trailing 28 days, most active first."""
    return await github_analytics.copilot_people()


@router.get("/copilot/people/{login}")
async def get_copilot_person(login: str, current_user: dict = Depends(get_current_user)):
    """One person's activity, model choice and budget pacing."""
    return await github_analytics.copilot_person(login)


@router.post("/copilot/remind")
async def remind_copilot_seats(
    body: CopilotLogins,
    current_user: dict = Depends(get_current_user),
):
    """Nudge the named seat holders to start using the Copilot license they hold."""
    cp = await github_analytics.copilot_seats()
    seats = {s["login"].lower(): s for s in cp.get("seats", [])}
    wanted = [l for l in body.logins if l.lower() in seats]
    if not wanted:
        raise HTTPException(status_code=400, detail="None of those logins hold an under-used seat.")

    resolved = await github_analytics.copilot_identities(wanted)
    identities = resolved["identities"]
    sender = current_user.get("display_name") or current_user.get("username", "?")

    results = []
    for login in wanted:
        ident = identities.get(login, {})
        seat = seats[login.lower()]
        results.append(await asyncio.to_thread(
            copilot_notify.send_usage_nudge,
            login, ident.get("email") or "", ident.get("name") or login,
            never_used=seat["never_used"],
            idle_days=seat.get("idle_days"),
            threshold=cp.get("idle_days_threshold", 30),
            sender=sender,
        ))

    sent = [r for r in results if r["sent"]]
    audit.log_event(
        "github.copilot_reminder",
        current_user.get("username", "?"),
        details={"requested": len(wanted), "sent": len(sent),
                 "logins": [r["login"] for r in sent]},
    )
    return {"sent": len(sent), "requested": len(wanted), "results": results}


@router.get("/teams")
async def get_enterprise_teams(current_user: dict = Depends(get_current_user)):
    """Enterprise teams and their member counts, for the reporting picker."""
    return await github_analytics.enterprise_teams()


@router.get("/reports/team-copilot")
async def get_team_copilot_report(
    team: str = Query(..., min_length=1, max_length=120),
    current_user: dict = Depends(get_current_user),
):
    """Copilot adoption for one enterprise team, as JSON (for the on-screen summary)."""
    report = await github_analytics.team_copilot_report(team)
    if report.get("error"):
        raise HTTPException(status_code=400, detail=report["error"])
    return report


@router.get("/reports/team-copilot.csv")
async def download_team_copilot_report(
    team: str = Query(..., min_length=1, max_length=120),
    current_user: dict = Depends(get_current_user),
):
    """The same report as a CSV download.

    Rendered server-side so the file matches what the summary shows and the
    browser does not have to reimplement the column order or the escaping.
    """
    report = await github_analytics.team_copilot_report(team)
    if report.get("error"):
        raise HTTPException(status_code=400, detail=report["error"])

    slug = report["team"].replace("ent:", "").replace("/", "-")
    filename = f"CMS-GitHub-{slug}-Copilot-{date.today().isoformat()}.csv"
    audit.log_event(
        "github.team_copilot_report",
        current_user.get("username", "?"),
        details={"team": report["team"], "members": report["members"]},
    )
    return Response(
        content=github_analytics.team_report_csv(report),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/refresh")
async def refresh(current_user: dict = Depends(get_current_user)):
    """Drop the cached reads so the next request hits GitHub."""
    github_analytics.invalidate()
    return {"refreshed": True}


@router.get("/status")
async def get_github_status(current_user: dict = Depends(get_current_user)):
    """GitHub's own service health (githubstatus.com), not our enterprise."""
    return await asyncio.to_thread(github_status.current_status)


@router.get("/orgs")
async def get_accessible_orgs(current_user: dict = Depends(get_current_user)):
    """Orgs the caller's own PAT currently has access to, for an org picker
    on actions not locked to the configured default org."""
    return await asyncio.to_thread(github_auth.list_accessible_orgs, current_user["username"])


@router.get("/jobs/{job_id}")
async def get_bulk_job(job_id: str, current_user: dict = Depends(get_current_user)):
    """Poll a background bulk job (org invite / Copilot seat / repo create)
    started by this user -- for the progress bar while it runs and the
    final per-item results once it's done."""
    job = bulk_job.get_job(job_id)
    if not job or job["username"] != current_user["username"]:
        raise HTTPException(status_code=404, detail="No such job.")
    return job


@router.get("/org-invites/can-send")
async def get_org_invite_eligibility(current_user: dict = Depends(get_current_user)):
    """Whether this user has a personal PAT on file to send invites with."""
    return github_invites.can_send(current_user["username"])


@router.post("/org-invites")
async def send_org_invites(
    body: OrgInviteBody,
    current_user: dict = Depends(get_current_user),
):
    """Starts a background job sending GitHub org invitations, attributed to
    the caller's own PAT (never the shared service account) so GitHub's own
    "Invited by" names the engineer who actually sent it. There's no bulk
    endpoint on GitHub's side -- one call per email -- so this returns a
    job id immediately; poll GET /github/jobs/{job_id} for progress."""
    emails = [e.strip() for e in body.emails if e.strip()]
    if not emails:
        raise HTTPException(status_code=400, detail="At least one email is required.")
    try:
        job_id = await asyncio.to_thread(
            github_invites.start_bulk_invite,
            current_user["username"],
            emails,
            role=body.role,
            team_slug=body.team.strip() or None,
            approval_note=body.approval_note,
            org=body.org.strip() or None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"job_id": job_id}


@router.get("/copilot/seats/can-assign")
async def get_copilot_seat_eligibility(current_user: dict = Depends(get_current_user)):
    """Whether this user has a personal PAT on file to assign seats with."""
    return github_auth.has_personal_pat(current_user["username"])


@router.post("/copilot/seats/assign")
async def assign_copilot_seats(
    body: CopilotSeatAssignBody,
    current_user: dict = Depends(get_current_user),
):
    """Starts a background job bulk-assigning Copilot seats, attributed to
    the caller's own PAT (never the shared service account). Returns a job
    id immediately; poll GET /github/jobs/{job_id} for progress."""
    handles = [h.strip() for h in body.handles if h.strip()]
    if not handles:
        raise HTTPException(status_code=400, detail="At least one GitHub handle is required.")
    try:
        job_id = await asyncio.to_thread(
            github_copilot_seats.start_bulk_assign,
            current_user["username"],
            handles,
            org=body.org.strip() or None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"job_id": job_id}


@router.get("/repos/can-create")
async def get_repo_create_eligibility(current_user: dict = Depends(get_current_user)):
    """Whether this user has a personal PAT on file to create repos with."""
    return github_auth.has_personal_pat(current_user["username"])


@router.post("/repos/create")
async def create_repos(
    body: RepoCreateBody,
    current_user: dict = Depends(get_current_user),
):
    """Starts a background job bulk-creating repos with the team's standard
    baseline access (3 baseline teams + the GitHub/Jira service account as
    Admin, plus each repo's own requestor and any extra admins), attributed
    to the caller's own PAT. Returns a job id immediately; poll
    GET /github/jobs/{job_id} for progress."""
    specs = [
        {"name": s.name.strip(), "requestor": s.requestor.strip().lstrip("@"),
         "extra_admins": [a.strip().lstrip("@") for a in s.extra_admins if a.strip()],
         "ticket_key": s.ticket_key.strip()}
        for s in body.specs
    ]
    try:
        job_id = await asyncio.to_thread(
            github_repo_create.start_bulk_create, current_user["username"], specs, body.force_existing,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"job_id": job_id}
