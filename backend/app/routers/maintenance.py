import asyncio
import logging
import re as _re
import time as _time
import xml.etree.ElementTree as _ET
from datetime import date, datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from fastapi import Request

from app.auth.jwt import get_current_user
from app.config import get_settings
from app.services import audit
from app.services import github_auth
from app.services.jenkins import get_build_info, get_job_params, trigger_job
from app.services.jira_service import (
    create_itc_maintenance_ticket,
    create_mggd_maintenance_ticket,
    create_ticket,
    find_this_month_maintenance_tickets,
    get_next_maintenance_date,
    get_dmsc_sprints,
    get_maint_prep_rotation,
    get_maint_prep_status,
    create_maint_prep_tickets,
    ON_CALL_TEAM,
    create_on_call_tickets,
    close_itc_ticket,
    close_mggd_ticket,
    create_dmsc_sprint,
    get_mggd_ticket_tasks,
)
from app.services.jfrog_maintenance import (
    HELM_RELEASES,
    OCI_REPOS,
    EKS_VERSION,
    artifactory_app_version,
    extract_ami_from_nodeclass,
    extract_ami_from_tfvars,
    extract_helm_version,
    extract_oci_tag,
    fetch_ami_release_notes,
    fetch_artifacthub_version,
    fetch_dockerhub_latest,
    fetch_karpenter_latest,
    fetch_latest_ami,
    fetch_release_notes,
    get_branch_or_none,
    get_file,
    get_or_create_branch,
    merge_main_into_branch,
    is_minor_or_major_bump,
    maint_branch_name,
    patch_ami_in_nodeclass,
    patch_ami_in_tfvars,
    patch_helm_version,
    patch_oci_tag,
    put_file,
    JFROG_DEV_TFVARS_PATH,
    KARPENTER_NODECLASS_PATH,
    KARPENTER_NODECLASS_PROD_PATH,
    JFROG_PROD_TFVARS_PATH,
    PROD_ONLY_HELM_RELEASES,
    PROD_ONLY_OCI_REPOS,
    get_jfrog_env_params,
    apply_jfrog_env_changes,
    get_base_charts_params,
    apply_base_charts_changes,
)
from app.services.slack import send_message
from app.services import cloudbees_maintenance as cb
from app.services.victorops_service import get_sprint_oncall_assignments
from app.services.confluence_service import (
    preview_retro_titles,
    create_maintenance_retro_page,
    create_sprint_retro_page,
)
from app.services import oe_readiness
from app.services import eks_upgrade

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/maintenance", tags=["maintenance"])


def _gh_write_token(current_user: dict) -> str:
    """Resolve the GitHub token for a write on this engineer's behalf: their
    stored PAT when the vault is unlocked, else the service account. Commits made
    with a user PAT are attributed to that engineer by GitHub; the service token
    keeps the flow working when no PAT is saved or the vault is locked."""
    return github_auth.resolve_github_auth(current_user.get("username"))["token"]


# --------------------------------------------------------------------------- #
# Request body models                                                           #
# --------------------------------------------------------------------------- #


class ITCMaintenanceRequest(BaseModel):
    maintenance_date: str    # "MM-DD-YYYY" — used in the ticket summary
    description: str         # Full Jira wiki-markup description body
    start_dt: str            # ISO datetime e.g. "2026-10-17T09:00:00.000-0400"
    end_dt: str              # ISO datetime for maintenance window close
    confluence_url: str = ""
    mggd_url: str = ""


class MGGDMaintenanceRequest(BaseModel):
    maintenance_date: str    # "MM-DD-YYYY" — used in the ticket summary
    description: str         # Full Jira wiki-markup description body
    start_dt: str            # ISO datetime e.g. "2026-10-17T09:00:00.000-0400"
    end_dt: str              # ISO datetime for maintenance window close
    go_nogo_review_date: str # "YYYY-MM-DD" — Go/No-Go review date (typically Friday before)
    release_number: str      # e.g. "Cloudbees_2.528.2.xx"
    downtime: bool = True
    impl_rollback_plan_attached: bool = True
    itc_key: str = ""        # Optional ITC ticket # for the IR Plan Excel attachment


class BranchRequest(BaseModel):
    repo: str
    branch_name: str


class CloseTicketRequest(BaseModel):
    key: str


class DatadogDowntimeRequest(BaseModel):
    scope: str
    start: int              # Unix timestamp
    end: int                # Unix timestamp
    message: str
    monitor_tags: list[str] = []


class SlackNotifyRequest(BaseModel):
    message: str
    maintenance_window: str


class SonarQubeDeployRequest(BaseModel):
    params: dict[str, str]   # parameter name → value as supplied by the engineer


class JFrogDevApplyRequest(BaseModel):
    branch: str              # maintenance branch to commit to
    new_ami: str             # new AMI ID to apply
    new_ami_name: str = ""   # AMI Name for the identifying inline comment
    helm_versions: dict[str, str]  # chart key → new version
    oci_versions: dict[str, str]   # oci key → new tag
    rebase_from_main: bool = False # merge main into the branch before committing


class EksUpgradeApplyRequest(BaseModel):
    branch: str
    cluster: str                    # key in eks_upgrade.EKS_CLUSTERS
    target_version: str             # e.g. "1.35"
    new_ami: str = ""               # gold image for the target version
    new_ami_name: str = ""          # AMI Name for the identifying inline comment
    rebase_from_main: bool = False
    confirm_prod: bool = False      # required for a prod cluster


class BaseChartsApplyRequest(BaseModel):
    branch: str
    helm_versions: dict[str, str]   # chart key → new version
    rebase_from_main: bool = False  # merge main into the branch before committing


class CloudBeesDevApplyRequest(BaseModel):
    branch: str
    new_chart_version: str | None = None   # e.g. 3.36984.0+814fd3fcf17b
    new_chart_tag: str | None = None       # e.g. 2.555.3.36983
    dev_east_controller_ami: str | None = None
    dev_east_controller_ami_name: str | None = None
    dev_east_agent_ami: str | None = None
    dev_east_agent_ami_name: str | None = None
    gc_dev_west_controller_ami: str | None = None
    gc_dev_west_controller_ami_name: str | None = None
    gc_dev_west_agent_ami: str | None = None
    gc_dev_west_agent_ami_name: str | None = None
    karpenter_version: str | None = None       # new Karpenter chart tag (shared base)
    karpenter_crd_version: str | None = None   # new Karpenter-CRD chart tag (shared base)
    rebase_from_main: bool = False


class CloudBeesProdApplyRequest(BaseModel):
    branch: str
    new_chart_version: str | None = None
    new_chart_tag: str | None = None
    prod_east_controller_ami: str | None = None
    prod_east_controller_ami_name: str | None = None
    prod_east_agent_ami: str | None = None
    prod_east_agent_ami_name: str | None = None
    gc_prod_west_controller_ami: str | None = None
    gc_prod_west_controller_ami_name: str | None = None
    gc_prod_west_agent_ami: str | None = None
    gc_prod_west_agent_ami_name: str | None = None
    karpenter_version: str | None = None       # new Karpenter chart tag (shared base)
    karpenter_crd_version: str | None = None   # new Karpenter-CRD chart tag (shared base)
    rebase_from_main: bool = False


class MaintPrepCreateRequest(BaseModel):
    sprint_id: int | None = None          # existing sprint; None = create a new one
    new_sprint_name: str | None = None    # required when sprint_id is None
    new_sprint_start: str | None = None
    new_sprint_end: str | None = None
    maint_date_str: str       # e.g. "July 19, 2026"
    jfrog_assignee: str
    cloudbees_assignee: str
    sonarqube_assignee: str


class OnCallWeek(BaseModel):
    week: int
    assignee: str


class OnCallCreateRequest(BaseModel):
    sprint_id: int | None = None          # existing sprint; None = create new one
    new_sprint_name: str | None = None    # required when sprint_id is None
    new_sprint_start: str | None = None
    new_sprint_end: str | None = None
    weeks: list[OnCallWeek]


# --------------------------------------------------------------------------- #
# Routes                                                                        #
# --------------------------------------------------------------------------- #


def _is_itc_authorized(current_user: dict) -> bool:
    """Return True if the user is allowed to perform ITC/MGGD ticket actions."""
    settings = get_settings()
    authorized_emails = {e.strip().lower() for e in settings.ITC_AUTHORIZED_EMAIL.split(",") if e.strip()}
    authorized_users = {u.strip().lower() for u in settings.ITC_AUTHORIZED_USERS.split(",") if u.strip()}
    return (
        current_user.get("email", "").lower() in authorized_emails
        or current_user.get("username", "").lower() in authorized_users
    )


def _require_itc_author(current_user: dict) -> None:
    """Raise 403 if the logged-in user is not in the ITC authorized list."""
    if not _is_itc_authorized(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="ITC/MGGD ticket actions are restricted to authorized users.",
        )


class NewsletterAppendRequest(BaseModel):
    itc_key: str = ""
    maint_date_mdy: str          # "M/D/YYYY"
    start_dt: str                # ISO
    end_dt: str                  # ISO
    tool_bullets: list[str] = []
    page_id: str | None = None
    dry_run: bool = True         # default: preview only, no live edit


@router.get("/window")
async def get_maintenance_window(current_user: dict = Depends(get_current_user)):
    """The maintenance date and window every flow should use.

    Read by the ITC, MGGD and Datadog forms so they pre-fill the same values
    the tickets are created with. Computing it in the browser cannot see the
    admin override, which is how the Datadog modal ended up able to pre-fill a
    date the tickets would not use.
    """
    from app.services import maint_date_override
    return maint_date_override.effective_window()


@router.post("/newsletter-append")
async def newsletter_append(
    request: Request,
    body: NewsletterAppendRequest,
    current_user: dict = Depends(get_current_user),
):
    """Append the DevOps maintenance change to the weekly change newsletter (COC).
    Defaults to a dry-run (returns the target page + proposed section without
    editing). dry_run=false performs the surgical live append."""
    _require_itc_author(current_user)
    from app.services import confluence_newsletter
    bullets = body.tool_bullets or [
        "JFrog Artifactory / Xray upgrade",
        "CloudBees Jenkins chart + node AMI update",
        "SonarQube upgrade and re-index",
    ]
    try:
        result = await asyncio.to_thread(
            confluence_newsletter.append_maintenance_change,
            body.itc_key, body.maint_date_mdy, body.start_dt, body.end_dt,
            bullets, body.page_id, body.dry_run,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Newsletter append failed: {exc}")
    if not body.dry_run:
        audit.log_event(
            "maintenance.newsletter_append",
            current_user["username"],
            details={"page_id": result.get("page_id"), "change_number": result.get("change_number"),
                     "itc_key": body.itc_key},
            ip=request.client.host if request.client else None,
        )
    return result


@router.post("/itc-ticket", status_code=status.HTTP_201_CREATED)
async def create_itc_ticket(
    request: Request,
    body: ITCMaintenanceRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    Clone the latest DevOps Service Maintenance ITC ticket with the new maintenance details.
    Restricted to the authorized ITC author (Patrick Hendren).
    """
    _require_itc_author(current_user)
    try:
        result = create_itc_maintenance_ticket(
            maintenance_date=body.maintenance_date,
            description=body.description,
            start_dt=body.start_dt,
            end_dt=body.end_dt,
            confluence_url=body.confluence_url,
            mggd_url=body.mggd_url,
        )
    except Exception as exc:
        logger.error("Failed to create ITC ticket: %s", exc)
        raise HTTPException(status_code=500, detail=f"Jira error: {exc}") from exc

    audit.log_event(
        "maintenance.itc_ticket",
        current_user["username"],
        details={"maintenance_date": body.maintenance_date, "ticket_key": result.get("key")},
        ip=request.client.host if request.client else None,
    )
    try:
        from app.services.maint_notify import send_confirmation
        await asyncio.to_thread(send_confirmation, "ITC", [result], body.maintenance_date)
    except Exception as exc:  # noqa: BLE001
        logging.getLogger(__name__).warning("ITC confirmation email failed: %s", exc)
    return {"ticket": result}


@router.post("/mggd-ticket", status_code=status.HTTP_201_CREATED)
async def create_mggd_ticket(
    request: Request,
    body: MGGDMaintenanceRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    Create a PROD Deployment ticket in MGGD (jira.cms.gov) for a DevOps maintenance window.
    Restricted to the authorized ITC author (Patrick Hendren).
    """
    _require_itc_author(current_user)
    try:
        result = create_mggd_maintenance_ticket(
            maintenance_date=body.maintenance_date,
            description=body.description,
            start_dt=body.start_dt,
            end_dt=body.end_dt,
            go_nogo_review_date=body.go_nogo_review_date,
            release_number=body.release_number,
            downtime=body.downtime,
            impl_rollback_plan_attached=body.impl_rollback_plan_attached,
            itc_key=body.itc_key,
        )
    except Exception as exc:
        logger.error("Failed to create MGGD ticket: %s", exc)
        raise HTTPException(status_code=500, detail=f"MGGD Jira error: {exc}") from exc

    audit.log_event(
        "maintenance.mggd_ticket",
        current_user["username"],
        details={"maintenance_date": body.maintenance_date, "ticket_key": result.get("key")},
        ip=request.client.host if request.client else None,
    )
    try:
        from app.services.maint_notify import send_confirmation
        await asyncio.to_thread(send_confirmation, "MGGD", [result], body.maintenance_date)
    except Exception as exc:  # noqa: BLE001
        logging.getLogger(__name__).warning("MGGD confirmation email failed: %s", exc)
    return {"ticket": result}


@router.post("/close-itc")
async def close_itc(
    request: Request,
    body: CloseTicketRequest,
    current_user: dict = Depends(get_current_user),
):
    """Add completion comment and transition ITC ticket to Implemented."""
    _require_itc_author(current_user)
    try:
        result = await asyncio.to_thread(close_itc_ticket, body.key)
    except Exception as exc:
        logger.error("Failed to close ITC ticket %s: %s", body.key, exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    audit.log_event(
        "maintenance.close_itc",
        current_user["username"],
        details={"key": body.key},
        ip=request.client.host if request.client else None,
    )
    return {"ticket": result}


@router.post("/close-mggd")
async def close_mggd(
    request: Request,
    body: CloseTicketRequest,
    current_user: dict = Depends(get_current_user),
):
    """Add completion comment to MGGD ticket."""
    _require_itc_author(current_user)
    try:
        result = await asyncio.to_thread(close_mggd_ticket, body.key)
    except Exception as exc:
        logger.error("Failed to close MGGD ticket %s: %s", body.key, exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    audit.log_event(
        "maintenance.close_mggd",
        current_user["username"],
        details={"key": body.key},
        ip=request.client.host if request.client else None,
    )
    return {"ticket": result}


@router.get("/mggd-tasks")
async def get_mggd_tasks(
    key: str,
    current_user: dict = Depends(get_current_user),
):
    """
    Fetch an MGGD ticket and return parsed per-tool task bullets so the ITC
    form can pre-populate JFrog / CB Jenkins / SonarQube task fields.
    """
    _require_itc_author(current_user)
    try:
        result = await asyncio.to_thread(get_mggd_ticket_tasks, key)
    except Exception as exc:
        logger.error("Failed to fetch MGGD tasks for %s: %s", key, exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return result


@router.get("/branch-defaults")
async def get_branch_defaults(current_user: dict = Depends(get_current_user)):
    """Return GitHub org and default repo so the frontend can pre-fill the branch form."""
    settings = get_settings()
    return {
        "org": settings.GITHUB_ORG,
        "default_repo": settings.GITHUB_DEFAULT_REPO,
    }


@router.post("/branch")
async def cut_maintenance_branch(
    request: Request,
    body: BranchRequest,
    current_user: dict = Depends(get_current_user),
):
    """Cut a branch from main — idempotent: returns existing branch if it already exists."""
    settings = get_settings()
    gh_token = _gh_write_token(current_user)
    if not gh_token:
        raise HTTPException(status_code=500, detail="GITHUB_TOKEN is not configured")

    if "/" in body.repo:
        full_repo = body.repo
    else:
        full_repo = f"{settings.GITHUB_ORG}/{body.repo}"

    api_base = f"https://api.github.com/repos/{full_repo}"
    headers = {
        "Authorization": f"Bearer {gh_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    async with httpx.AsyncClient(timeout=15) as client:
        # Check if the branch already exists
        existing_resp = await client.get(f"{api_base}/git/ref/heads/{body.branch_name}", headers=headers)
        if existing_resp.status_code == 200:
            sha = existing_resp.json()["object"]["sha"]
            return {
                "repo": full_repo,
                "branch": body.branch_name,
                "sha": sha,
                "url": f"https://github.com/{full_repo}/tree/{body.branch_name}",
                "already_existed": True,
            }

        # Get the SHA of main to branch from
        ref_resp = await client.get(f"{api_base}/git/ref/heads/main", headers=headers)
        if ref_resp.status_code == 404:
            raise HTTPException(status_code=404, detail=f"Repo or main branch not found: {full_repo}")
        ref_resp.raise_for_status()
        main_sha = ref_resp.json()["object"]["sha"]

        # Create the branch
        create_resp = await client.post(
            f"{api_base}/git/refs",
            headers=headers,
            json={"ref": f"refs/heads/{body.branch_name}", "sha": main_sha},
        )
        create_resp.raise_for_status()

    audit.log_event(
        "maintenance.branch_cut",
        current_user["username"],
        details={"repo": full_repo, "branch": body.branch_name},
        ip=request.client.host if request.client else None,
    )
    return {
        "repo": full_repo,
        "branch": body.branch_name,
        "sha": main_sha,
        "url": f"https://github.com/{full_repo}/tree/{body.branch_name}",
        "already_existed": False,
    }


def _dd_headers(settings) -> dict:
    return {
        "DD-API-KEY": settings.DATADOG_API_KEY,
        "DD-APPLICATION-KEY": settings.DATADOG_APP_KEY,
        "Content-Type": "application/json",
    }


def _dd_url(settings, path: str) -> str:
    return f"{settings.DATADOG_API_BASE.rstrip('/')}{path}"


import json as _json
import pathlib as _pathlib


def _dd_save_id(settings, downtime_id: str) -> None:
    path = _pathlib.Path(settings.DATADOG_STATE_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_json.dumps({"id": downtime_id}))


def _dd_load_id(settings) -> str | None:
    path = _pathlib.Path(settings.DATADOG_STATE_FILE)
    if not path.exists():
        return None
    try:
        return _json.loads(path.read_text()).get("id")
    except Exception:
        return None


def _dd_clear_id(settings) -> None:
    path = _pathlib.Path(settings.DATADOG_STATE_FILE)
    if path.exists():
        path.unlink(missing_ok=True)


def _unix_to_iso(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _iso_to_unix(iso: str | None) -> int | None:
    if not iso:
        return None
    try:
        return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())
    except (ValueError, TypeError):
        return None


@router.post("/datadog-downtime")
async def create_datadog_downtime(
    request: Request,
    body: DatadogDowntimeRequest,
    current_user: dict = Depends(get_current_user),
):
    """Create a Datadog monitor downtime for the specified scope and window."""
    settings = get_settings()
    if not settings.DATADOG_API_KEY or not settings.DATADOG_APP_KEY:
        raise HTTPException(status_code=500, detail="Datadog API credentials are not configured")

    payload = {
        "data": {
            "type": "downtime",
            "attributes": {
                "message": body.message,
                "scope": body.scope,
                "schedule": {
                    "start": _unix_to_iso(body.start),
                    "end": _unix_to_iso(body.end),
                },
                "monitor_identifier": {
                    "monitor_tags": body.monitor_tags,
                },
            },
        }
    }

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            _dd_url(settings, "/api/v2/downtime"),
            json=payload,
            headers=_dd_headers(settings),
        )
        if not resp.is_success:
            logger.error("Datadog downtime creation failed: %s %s", resp.status_code, resp.text)
            raise HTTPException(status_code=502, detail=f"Datadog API error: {resp.text}")
        d = resp.json()["data"]

    attrs = d.get("attributes", {})
    schedule = attrs.get("schedule", {})
    _dd_save_id(settings, d["id"])
    audit.log_event(
        "maintenance.datadog_downtime_create",
        current_user["username"],
        details={"scope": body.scope, "downtime_id": d["id"]},
        ip=request.client.host if request.client else None,
    )
    return {
        "downtime_id": d["id"],
        "scope": attrs.get("scope", ""),
        "start": _iso_to_unix(schedule.get("start")),
        "end": _iso_to_unix(schedule.get("end")),
        "message": attrs.get("message", ""),
    }


@router.get("/datadog-active")
async def get_active_datadog_downtime(current_user: dict = Depends(get_current_user)):
    """Return the DevOps downtime we created (active or scheduled), or null if none/canceled."""
    settings = get_settings()
    if not settings.DATADOG_API_KEY or not settings.DATADOG_APP_KEY:
        raise HTTPException(status_code=500, detail="Datadog API credentials are not configured")

    downtime_id = _dd_load_id(settings)
    if not downtime_id:
        return {"downtime": None}

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            _dd_url(settings, f"/api/v2/downtime/{downtime_id}"),
            headers=_dd_headers(settings),
        )

    if resp.status_code == 404:
        _dd_clear_id(settings)
        return {"downtime": None}
    if not resp.is_success:
        raise HTTPException(status_code=502, detail=f"Datadog API error: {resp.text}")

    d = resp.json()["data"]
    attrs = d.get("attributes", {})
    status = attrs.get("status")
    if status not in ("active", "scheduled"):
        _dd_clear_id(settings)
        return {"downtime": None}

    schedule = attrs.get("schedule", {})
    return {
        "downtime": {
            "id": d["id"],
            "scope": attrs.get("scope", ""),
            "message": attrs.get("message", ""),
            "start": _iso_to_unix(schedule.get("start")),
            "end": _iso_to_unix(schedule.get("end")),
            "status": status,
        }
    }


@router.post("/datadog-downtime/{downtime_id}/extend")
async def extend_datadog_downtime(
    downtime_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Extend an active Datadog downtime by 2 hours."""
    settings = get_settings()
    if not settings.DATADOG_API_KEY or not settings.DATADOG_APP_KEY:
        raise HTTPException(status_code=500, detail="Datadog API credentials are not configured")

    async with httpx.AsyncClient(timeout=15) as client:
        get_resp = await client.get(
            _dd_url(settings, f"/api/v2/downtime/{downtime_id}"),
            headers=_dd_headers(settings),
        )
        if not get_resp.is_success:
            raise HTTPException(status_code=502, detail=f"Datadog API error: {get_resp.text}")
        current_attrs = get_resp.json()["data"].get("attributes", {})
        current_end_iso = current_attrs.get("schedule", {}).get("end")
        current_end_ts = _iso_to_unix(current_end_iso) or int(_time.time())
        new_end_iso = _unix_to_iso(current_end_ts + 7200)

        patch_resp = await client.patch(
            _dd_url(settings, f"/api/v2/downtime/{downtime_id}"),
            json={"data": {"type": "downtime", "id": downtime_id, "attributes": {"schedule": {"end": new_end_iso}}}},
            headers=_dd_headers(settings),
        )
        if not patch_resp.is_success:
            raise HTTPException(status_code=502, detail=f"Datadog API error: {patch_resp.text}")
        d = patch_resp.json()["data"]

    schedule = d.get("attributes", {}).get("schedule", {})
    return {"downtime_id": d["id"], "end": _iso_to_unix(schedule.get("end"))}


@router.delete("/datadog-downtime/{downtime_id}")
async def cancel_datadog_downtime(
    request: Request,
    downtime_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Cancel (end) an active Datadog downtime immediately."""
    settings = get_settings()
    if not settings.DATADOG_API_KEY or not settings.DATADOG_APP_KEY:
        raise HTTPException(status_code=500, detail="Datadog API credentials are not configured")

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.delete(
            _dd_url(settings, f"/api/v2/downtime/{downtime_id}"),
            headers=_dd_headers(settings),
        )
        if not resp.is_success and resp.status_code != 404:
            raise HTTPException(status_code=502, detail=f"Datadog API error: {resp.text}")

    _dd_clear_id(settings)
    audit.log_event(
        "maintenance.datadog_downtime_cancel",
        current_user["username"],
        details={"downtime_id": downtime_id},
        ip=request.client.host if request.client else None,
    )
    return {"cancelled": True, "downtime_id": downtime_id}


@router.get("/xoceoc-preview")
async def get_xoceoc_preview(current_user: dict = Depends(get_current_user)):
    """
    Return this month's ITC and MGGD ticket links so the frontend can render
    copy-paste Slack messages for EOC and XOC.
    """
    try:
        tickets = find_this_month_maintenance_tickets()
    except Exception as exc:
        logger.error("Failed to fetch maintenance tickets for XOC/EOC preview: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))
    return tickets


def _jenkins_auth(current_user: dict, settings) -> tuple[str, str]:
    """Use the engineer's persistent prod-east token; retain the configured
    controller credential as a fallback for sessions without a user token.
    """
    user_token = current_user.get("jenkins_token")
    if user_token:
        return (current_user["username"], user_token)
    return (settings.JENKINS_USER, settings.SONARQUBE_JENKINS_TOKEN)


_SQ_S3_URL = "https://binaries.sonarsource.com/s3api"
_SQ_S3_NS  = "http://s3.amazonaws.com/doc/2006-03-01/"
_SQ_VER_RE = _re.compile(r"sonarqube-datacenter-(\d+)\.(\d+)\.(\d+)\.(\d+)\.zip$")


async def _fetch_sonarqube_versions() -> list[str]:
    params = {"prefix": "CommercialDistribution/sonarqube-datacenter/", "delimiter": "/"}
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(_SQ_S3_URL, params=params)
        resp.raise_for_status()
    root = _ET.fromstring(resp.text)
    seen: set[str] = set()
    for el in root.findall(f".//{{{_SQ_S3_NS}}}Key"):
        m = _SQ_VER_RE.search(el.text or "")
        if not m:
            continue
        year, minor = int(m.group(1)), int(m.group(2))
        if (year, minor) < (2026, 2):
            continue
        seen.add(f"{m.group(1)}.{m.group(2)}.{m.group(3)}.{m.group(4)}")
    return sorted(seen, key=lambda v: tuple(int(x) for x in v.split(".")), reverse=True)


@router.get("/sonarqube-versions")
async def get_sonarqube_versions(current_user: dict = Depends(get_current_user)):
    """Return available SonarQube datacenter versions >= 2026.2 from binaries.sonarsource.com."""
    try:
        versions = await _fetch_sonarqube_versions()
        return {"versions": versions}
    except Exception as exc:
        logger.error("Failed to fetch SonarQube versions: %s", exc)
        raise HTTPException(status_code=502, detail=f"Failed to fetch SonarQube versions: {exc}")


@router.get("/sonarqube-release-notes")
async def get_sonarqube_release_notes(version: str, current_user: dict = Depends(get_current_user)):
    """Return SonarQube release notes (resolved Jira issues) for a build version.

    Read-only lookup against SonarSource's public Jira; best-effort so the modal
    degrades gracefully if it's unavailable."""
    from app.services.sonarqube_maintenance import fetch_sonarqube_release_notes
    return await asyncio.to_thread(fetch_sonarqube_release_notes, version)


@router.get("/sonarqube-params")
async def get_sonarqube_params(current_user: dict = Depends(get_current_user)):
    """Return the deploy-sonarqube Jenkins job parameter definitions."""
    settings = get_settings()
    auth = _jenkins_auth(current_user, settings)
    try:
        params = get_job_params(settings.SONARQUBE_JOB_URL, auth=auth)
    except Exception as exc:
        logger.error("Failed to fetch SonarQube job params: %s", exc)
        raise HTTPException(status_code=502, detail=f"Jenkins error: {exc}") from exc
    return {"params": params, "job_url": settings.SONARQUBE_JOB_URL}


@router.post("/sonarqube-dev")
async def sonarqube_dev_maintenance(
    request: Request,
    body: SonarQubeDeployRequest,
    current_user: dict = Depends(get_current_user),
):
    """Trigger the deploy-sonarqube Jenkins job with the supplied parameters."""
    settings = get_settings()
    auth = _jenkins_auth(current_user, settings)
    try:
        queue_info = trigger_job(job_url=settings.SONARQUBE_JOB_URL, params=body.params, auth=auth)
    except Exception as exc:
        logger.error("Failed to trigger SonarQube deploy job: %s", exc)
        raise HTTPException(status_code=502, detail=f"Jenkins error: {exc}") from exc

    build_url = queue_info.get("build_url") or f"{settings.SONARQUBE_JOB_URL}/lastBuild"
    audit.log_event(
        "maintenance.sonarqube_deploy",
        current_user["username"],
        details={"job_url": settings.SONARQUBE_JOB_URL, "params": body.params},
        ip=request.client.host if request.client else None,
    )
    return {
        "job_url": settings.SONARQUBE_JOB_URL,
        "build_url": build_url,
        "build_number": queue_info.get("build_number"),
        "status": queue_info.get("status", "queued"),
    }


# ─── JFrog Artifactory Dev Maintenance ────────────────────────────────────────

@router.get("/jfrog-dev-params")
async def get_jfrog_dev_params(current_user: dict = Depends(get_current_user)):
    """
    Find-or-create the maintenance branch, then fetch current versions from the
    branch and latest versions from upstream registries.  Returns a complete diff
    the engineer can review before applying.
    """
    settings = get_settings()
    if not settings.GITHUB_TOKEN:
        raise HTTPException(status_code=500, detail="GITHUB_TOKEN is not configured")

    org = settings.GITHUB_ORG
    repo = settings.GITHUB_DEFAULT_REPO or "cmscloud-devops"

    try:
        return await get_jfrog_env_params(
            settings.GITHUB_TOKEN, org, repo,
            JFROG_DEV_TFVARS_PATH, KARPENTER_NODECLASS_PATH,
            eks_cluster="jfrog-dev",
            # Dev floats its chart versions (e.g. 107.x) in this overlay; read the
            # current version from here so we don't compare against the base pin.
            helm_overlay_dir="kubernetes/envs/jfrog/dev/releases",
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"GitHub error: {exc}") from exc


@router.post("/jfrog-dev-apply")
async def apply_jfrog_dev_changes(
    request: Request,
    body: JFrogDevApplyRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    Commit AMI and chart version updates to the maintenance branch.
    Re-reads each file from the branch immediately before writing to get a fresh SHA.
    """
    settings = get_settings()
    gh_token = _gh_write_token(current_user)
    if not gh_token:
        raise HTTPException(status_code=500, detail="GITHUB_TOKEN is not configured")

    org = settings.GITHUB_ORG
    repo = settings.GITHUB_DEFAULT_REPO or "cmscloud-devops"

    try:
        result = await apply_jfrog_env_changes(
            gh_token, org, repo,
            body.branch, body.new_ami, body.helm_versions, body.oci_versions,
            JFROG_DEV_TFVARS_PATH, KARPENTER_NODECLASS_PATH,
            env_label="jfrog-dev",
            eks_cluster="jfrog-dev",
            rebase_from_main=body.rebase_from_main,
            new_ami_name=body.new_ami_name,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    audit.log_event(
        "maintenance.jfrog_dev_apply",
        current_user["username"],
        details={"branch": body.branch, "committed_files": result["committed_files"]},
        ip=request.client.host if request.client else None,
    )
    branch_url = f"https://github.com/{org}/{repo}/tree/{body.branch}"
    return {"committed_files": result["committed_files"], "branch": body.branch, "branch_url": branch_url}


# ─── EKS Control Plane Upgrade ─────────────────────────────────────────────────

@router.get("/eks-upgrade-params")
async def get_eks_upgrade(current_user: dict = Depends(get_current_user)):
    """Declared control-plane version per cluster plus the targets AWS offers."""
    settings = get_settings()
    if not settings.GITHUB_TOKEN:
        raise HTTPException(status_code=500, detail="GITHUB_TOKEN is not configured")

    org = settings.GITHUB_ORG
    repo = settings.GITHUB_DEFAULT_REPO or "cmscloud-devops"
    try:
        return await eks_upgrade.get_eks_upgrade_params(settings.GITHUB_TOKEN, org, repo, settings)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"EKS upgrade preview failed: {exc}") from exc


@router.get("/eks-upgrade-preview")
async def get_eks_upgrade_preview(
    cluster: str,
    target_version: str,
    current_user: dict = Depends(get_current_user),
):
    """Release notes, the pluto deprecated-API report, and the gold image for one
    cluster and target version. The pluto scan reads the maintenance branch when
    it exists, otherwise main."""
    settings = get_settings()
    if not settings.GITHUB_TOKEN:
        raise HTTPException(status_code=500, detail="GITHUB_TOKEN is not configured")
    if cluster not in eks_upgrade.EKS_CLUSTERS:
        raise HTTPException(status_code=400, detail=f"Unknown cluster: {cluster}")
    if not _re.fullmatch(r"\d+\.\d+", target_version):
        raise HTTPException(status_code=400, detail="target_version must look like 1.35")

    org = settings.GITHUB_ORG
    repo = settings.GITHUB_DEFAULT_REPO or "cmscloud-devops"
    try:
        return await eks_upgrade.get_upgrade_preview(
            settings.GITHUB_TOKEN, org, repo, settings, cluster, target_version
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Upgrade preview failed: {exc}") from exc


@router.post("/eks-upgrade-apply")
async def apply_eks_upgrade_changes(
    request: Request,
    body: EksUpgradeApplyRequest,
    current_user: dict = Depends(get_current_user),
):
    """Commit the eks_version bump and the matching gold-image realign."""
    settings = get_settings()
    gh_token = _gh_write_token(current_user)
    if not gh_token:
        raise HTTPException(status_code=500, detail="GITHUB_TOKEN is not configured")

    cfg = eks_upgrade.EKS_CLUSTERS.get(body.cluster)
    if not cfg:
        raise HTTPException(status_code=400, detail=f"Unknown cluster: {body.cluster}")
    if not _re.fullmatch(r"\d+\.\d+", body.target_version):
        raise HTTPException(status_code=400, detail="target_version must look like 1.35")
    if cfg.get("is_prod") and not body.confirm_prod:
        raise HTTPException(status_code=400, detail="confirm_prod is required for a prod cluster")

    org = settings.GITHUB_ORG
    repo = settings.GITHUB_DEFAULT_REPO or "cmscloud-devops"
    try:
        result = await eks_upgrade.apply_eks_upgrade(
            gh_token, org, repo, body.branch, body.cluster, body.target_version,
            new_ami=body.new_ami, new_ami_name=body.new_ami_name,
            rebase_from_main=body.rebase_from_main,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    audit.log_event(
        "maintenance.eks_upgrade_apply",
        current_user["username"],
        details={
            "branch": body.branch,
            "cluster": body.cluster,
            "target_version": body.target_version,
            "new_ami": body.new_ami,
            "committed_files": result["committed_files"],
        },
        ip=request.client.host if request.client else None,
    )
    return {
        "committed_files": result["committed_files"],
        "errors": result["errors"],
        "branch": body.branch,
        "branch_url": f"https://github.com/{org}/{repo}/tree/{body.branch}",
    }


# ─── Shared Base Helm Charts ───────────────────────────────────────────────────

@router.get("/base-charts-params")
async def get_base_charts(current_user: dict = Depends(get_current_user)):
    """Preview the shared kubernetes/base/releases charts that both the JFrog and
    CBJ clusters pull. Read-only; does not cut the maintenance branch."""
    settings = get_settings()
    if not settings.GITHUB_TOKEN:
        raise HTTPException(status_code=500, detail="GITHUB_TOKEN is not configured")

    org = settings.GITHUB_ORG
    repo = settings.GITHUB_DEFAULT_REPO or "cmscloud-devops"
    try:
        return await get_base_charts_params(settings.GITHUB_TOKEN, org, repo)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"GitHub error: {exc}") from exc


@router.post("/base-charts-apply")
async def apply_base_charts(
    request: Request,
    body: BaseChartsApplyRequest,
    current_user: dict = Depends(get_current_user),
):
    """Commit shared base chart bumps to the maintenance branch."""
    settings = get_settings()
    gh_token = _gh_write_token(current_user)
    if not gh_token:
        raise HTTPException(status_code=500, detail="GITHUB_TOKEN is not configured")

    org = settings.GITHUB_ORG
    repo = settings.GITHUB_DEFAULT_REPO or "cmscloud-devops"
    try:
        result = await apply_base_charts_changes(
            gh_token, org, repo, body.branch, body.helm_versions,
            rebase_from_main=body.rebase_from_main,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    audit.log_event(
        "maintenance.base_charts_apply",
        current_user["username"],
        details={"branch": body.branch, "committed_files": result["committed_files"]},
        ip=request.client.host if request.client else None,
    )
    return {
        "committed_files": result["committed_files"],
        "errors": result["errors"],
        "branch": body.branch,
        "branch_url": f"https://github.com/{org}/{repo}/tree/{body.branch}",
    }


# ─── JFrog Artifactory Prod Maintenance ───────────────────────────────────────

@router.get("/jfrog-prod-params")
async def get_jfrog_prod_params(current_user: dict = Depends(get_current_user)):
    """
    Find-or-create the maintenance branch, then fetch current prod versions from
    the branch and latest versions from upstream registries.
    """
    settings = get_settings()
    if not settings.GITHUB_TOKEN:
        raise HTTPException(status_code=500, detail="GITHUB_TOKEN is not configured")

    org = settings.GITHUB_ORG
    repo = settings.GITHUB_DEFAULT_REPO or "cmscloud-devops"

    try:
        return await get_jfrog_env_params(
            settings.GITHUB_TOKEN, org, repo,
            JFROG_PROD_TFVARS_PATH,
            # Prod does not inherit the base nodeclass AMI: its overlay lists
            # cluster-ops/karpenter-node-class.yaml under kustomize patches, so it
            # overrides the base and has to be read and bumped on its own.
            nodeclass_path=KARPENTER_NODECLASS_PROD_PATH,
            eks_cluster="jfrog-prod",
            # Snyk broker is prod-only (its manifests live in the prod overlay,
            # not the shared base), so it is tracked by the prod modal alone.
            extra_helm_releases=PROD_ONLY_HELM_RELEASES,
            extra_oci_repos=PROD_ONLY_OCI_REPOS,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"GitHub error: {exc}") from exc


@router.post("/jfrog-prod-apply")
async def apply_jfrog_prod_changes(
    request: Request,
    body: JFrogDevApplyRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    Commit AMI and chart version updates to the maintenance branch for prod.
    Re-reads each file from the branch immediately before writing to get a fresh SHA.
    """
    settings = get_settings()
    gh_token = _gh_write_token(current_user)
    if not gh_token:
        raise HTTPException(status_code=500, detail="GITHUB_TOKEN is not configured")

    org = settings.GITHUB_ORG
    repo = settings.GITHUB_DEFAULT_REPO or "cmscloud-devops"

    try:
        result = await apply_jfrog_env_changes(
            gh_token, org, repo,
            body.branch, body.new_ami, body.helm_versions, body.oci_versions,
            JFROG_PROD_TFVARS_PATH,
            nodeclass_path=KARPENTER_NODECLASS_PROD_PATH,
            env_label="jfrog-prod",
            eks_cluster="jfrog-prod",
            rebase_from_main=body.rebase_from_main,
            new_ami_name=body.new_ami_name,
            # Snyk broker is prod-only; commit its chart/tag bumps against the
            # prod overlay paths.
            extra_helm_releases=PROD_ONLY_HELM_RELEASES,
            extra_oci_repos=PROD_ONLY_OCI_REPOS,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    audit.log_event(
        "maintenance.jfrog_prod_apply",
        current_user["username"],
        details={"branch": body.branch, "committed_files": result["committed_files"]},
        ip=request.client.host if request.client else None,
    )
    branch_url = f"https://github.com/{org}/{repo}/tree/{body.branch}"
    return {"committed_files": result["committed_files"], "branch": body.branch, "branch_url": branch_url}


def _cb_env_section(env_key: str, tfvars_file, nodeclass_file, latest_ctrl: dict, latest_agent: dict) -> dict:
    """Build a CBJ env AMI section.

    The tfvars `eks_ami` (which Terraform maps to worker_node_ami) must always equal
    the controller nodeclass AMI. So we compute a single controller *target* AMI and
    treat it as an update whenever either the tfvars or the nodeclass differs from it
    — that way an Apply rewrites BOTH the tfvars and the controller nodeclass together
    and they can never silently drift (the prod-east tfvars-left-behind bug). If the
    latest-AMI lookup fails, we fall back to the nodeclass AMI so tfvars still reconciles
    to it rather than the row silently reading "up to date".
    """
    cfg = cb.CB_ENVS[env_key]
    ctrl_tfvars = cb.extract_eks_ami_from_tfvars(tfvars_file["content"]) if tfvars_file else None
    ctrl_nodeclass = cb.extract_controller_ami(nodeclass_file["content"]) if nodeclass_file else None
    agent_current = cb.extract_agent_ami(nodeclass_file["content"]) if nodeclass_file else None

    ctrl_latest = latest_ctrl.get("ami_id")
    ctrl_error = latest_ctrl.get("error")
    # Prefer the resolved latest gold image; on lookup failure fall back to the
    # nodeclass AMI so tfvars is at least reconciled to the controller nodeclass.
    ctrl_target = ctrl_latest or ctrl_nodeclass
    controller_drift = bool(ctrl_tfvars and ctrl_nodeclass and ctrl_tfvars != ctrl_nodeclass)
    controller_has_update = bool(
        ctrl_target and (ctrl_tfvars != ctrl_target or ctrl_nodeclass != ctrl_target)
    )

    agent_latest = latest_agent.get("ami_id")
    return {
        "label": cfg["label"],
        "current_controller_ami": ctrl_tfvars,
        "current_controller_ami_nodeclass": ctrl_nodeclass,
        "latest_controller_ami": ctrl_latest,
        "latest_controller_ami_name": latest_ctrl.get("ami_name"),
        # AMI the Apply will write to BOTH tfvars and the controller nodeclass.
        "controller_target_ami": ctrl_target,
        "controller_has_update": controller_has_update,
        "controller_drift": controller_drift,
        "current_agent_ami": agent_current,
        "latest_agent_ami": agent_latest,
        "latest_agent_ami_name": latest_agent.get("ami_name"),
        "agent_has_update": bool(agent_current and agent_latest and agent_current != agent_latest),
        "controller_error": ctrl_error,
        "agent_error": latest_agent.get("error"),
    }


# ─── CloudBees CI Dev Maintenance ─────────────────────────────────────────────

async def _cb_karpenter_rows(safe_get) -> list[dict]:
    """Build Karpenter + Karpenter-CRD OCI rows for the CBJ modals, shaped exactly
    like the JFrog oci_repos rows. Reads the shared base/jenkins OCIRepository tags
    and compares to the true semver-latest from kubernetes-sigs/karpenter."""
    kfile, kcrd_file, latest = await asyncio.gather(
        safe_get(cb.CB_OCI_REPOS["karpenter"]["file"]),
        safe_get(cb.CB_OCI_REPOS["karpenter-crd"]["file"]),
        fetch_karpenter_latest(),
        return_exceptions=True,
    )
    latest_ver = None if isinstance(latest, Exception) else latest
    err = str(latest) if isinstance(latest, Exception) else None

    rows: list[dict] = []
    for key, fdata in (("karpenter", kfile), ("karpenter-crd", kcrd_file)):
        meta = cb.CB_OCI_REPOS[key]
        fdata = None if isinstance(fdata, Exception) else fdata
        current = cb.extract_oci_tag(fdata["content"]) if fdata else None
        has_update = bool(current and latest_ver and current != latest_ver)
        notes = {"available": False}
        if has_update:
            try:
                notes = await fetch_release_notes(key, current, latest_ver)
            except Exception as exc:  # best-effort
                notes = {"available": False, "error": str(exc)}
        rows.append({
            "key": key,
            "label": meta["label"],
            "file": meta["file"],
            "current_version": current,
            "latest_version": latest_ver,
            "has_update": has_update,
            "is_breaking": is_minor_or_major_bump(current, latest_ver) if (current and latest_ver) else False,
            "changelog_url": meta["changelog_url"],
            "error": err,
            "release_notes": notes,
        })
    return rows


@router.get("/cloudbees-dev-params")
async def get_cloudbees_dev_params(current_user: dict = Depends(get_current_user)):
    """
    Fetch current CloudBees Core chart version, image tag, and AMIs from the
    maintenance branch.  Also fetches latest versions from upstream.
    """
    settings = get_settings()
    if not settings.GITHUB_TOKEN:
        raise HTTPException(status_code=500, detail="GITHUB_TOKEN is not configured")

    org = settings.GITHUB_ORG
    repo = settings.GITHUB_DEFAULT_REPO or "cmscloud-devops"
    branch = maint_branch_name()

    # Look up the maintenance branch WITHOUT creating it — opening the modal must
    # not cut the branch. Preview against the branch if it exists, else main.
    try:
        branch_info = await get_branch_or_none(settings.GITHUB_TOKEN, org, repo, branch)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"GitHub branch error: {exc}") from exc

    branch_exists = branch_info is not None
    branch_url = f"https://github.com/{org}/{repo}/tree/{branch}"
    ref = branch if branch_exists else "main"

    async def safe_get(path: str):
        try:
            return await get_file(settings.GITHUB_TOKEN, org, repo, path, ref)
        except Exception as e:
            logger.warning("Could not read %s from ref %s: %s", path, ref, e)
            return None

    # Read all relevant files concurrently
    (
        cb_core_file,
        de_tfvars_file, de_nodeclass_file,
        gc_tfvars_file, gc_nodeclass_file,
    ) = await asyncio.gather(
        safe_get(cb.CB_CORE_BASE_PATH),
        safe_get(cb.CB_ENVS["dev-east"]["tfvars_path"]),
        safe_get(cb.CB_ENVS["dev-east"]["nodeclass_path"]),
        safe_get(cb.CB_ENVS["gc-dev-west"]["tfvars_path"]),
        safe_get(cb.CB_ENVS["gc-dev-west"]["nodeclass_path"]),
    )

    gc_role_arn = settings.GOVCLOUD_DEV_ROLE_ARN or None
    gc_key_id = settings.GOVCLOUD_AWS_ACCESS_KEY_ID or None
    gc_secret = settings.GOVCLOUD_AWS_SECRET_ACCESS_KEY or None

    # Fetch latest versions + release notes concurrently (best-effort)
    # Gold images are named for a Kubernetes minor, so the image offered has to
    # follow what the cluster is running. tfvars can be bumped well before the
    # apply, and selecting by that offers nodes an image for a control plane that
    # does not exist yet. The declared value stays as the fallback.
    de_eks = await eks_upgrade.running_version(
        "cbj-dev-east", settings,
        eks_upgrade.extract_eks_version(de_tfvars_file["content"]) if de_tfvars_file else None)
    gc_eks = await eks_upgrade.running_version(
        "cbj-gc-dev-west", settings,
        eks_upgrade.extract_eks_version(gc_tfvars_file["content"]) if gc_tfvars_file else None)

    (
        latest_cb, latest_de_ctrl, latest_gc_ctrl,
        latest_de_agent, latest_gc_agent,
    ) = await asyncio.gather(
        cb.fetch_latest_cb_version(),
        cb.fetch_latest_controller_ami("dev-east", eks_version=de_eks),
        cb.fetch_latest_controller_ami("gc-dev-west", assume_role_arn=gc_role_arn, aws_access_key_id=gc_key_id, aws_secret_access_key=gc_secret, eks_version=gc_eks),
        cb.fetch_latest_agent_ami("dev-east", eks_version=de_eks),
        cb.fetch_latest_agent_ami("gc-dev-west", assume_role_arn=gc_role_arn, aws_access_key_id=gc_key_id, aws_secret_access_key=gc_secret, eks_version=gc_eks),
        return_exceptions=True,
    )

    def _safe(result, fallback=None):
        return result if not isinstance(result, Exception) else (fallback or {"error": str(result)})

    latest_cb = _safe(latest_cb, {})
    latest_de_ctrl = _safe(latest_de_ctrl, {})
    latest_gc_ctrl = _safe(latest_gc_ctrl, {})
    latest_de_agent = _safe(latest_de_agent, {})
    latest_gc_agent = _safe(latest_gc_agent, {})

    # Chart section
    current_version = cb.extract_chart_version(cb_core_file["content"]) if cb_core_file else None
    current_tag = cb.extract_image_tag(cb_core_file["content"]) if cb_core_file else None
    latest_version = latest_cb.get("version")
    latest_tag = latest_cb.get("app_version")
    has_chart_update = bool(current_version and latest_version and current_version != latest_version)

    # Fetch release notes if there's an update (best-effort, runs concurrently)
    release_notes: dict = {"available": False}
    if has_chart_update and current_tag and latest_tag:
        try:
            release_notes = await cb.fetch_cb_release_notes(current_tag, latest_tag)
        except Exception as exc:
            logger.warning("CB release notes fetch failed: %s", exc)

    chart_section = {
        "file": cb.CB_CORE_BASE_PATH,
        "current_version": current_version,
        "current_tag": current_tag,
        "latest_version": latest_version,
        "latest_tag": latest_tag,
        "has_update": has_chart_update,
        "changelog_url": "https://docs.cloudbees.com/docs/release-notes/latest/cloudbees-ci/",
        "release_notes": release_notes,
    }

    # Per-env AMI sections
    def _env_section(env_key: str, tfvars_file, nodeclass_file, latest_ctrl: dict, latest_agent: dict) -> dict:
        return _cb_env_section(env_key, tfvars_file, nodeclass_file, latest_ctrl, latest_agent)

    karpenter_rows = await _cb_karpenter_rows(safe_get)

    return {
        "branch": branch,
        "branch_created": False,
        "branch_exists": branch_exists,
        "branch_url": branch_url,
        "chart": chart_section,
        "oci_repos": karpenter_rows,
        "envs": {
            "dev-east": _env_section("dev-east", de_tfvars_file, de_nodeclass_file, latest_de_ctrl, latest_de_agent),
            "gc-dev-west": _env_section("gc-dev-west", gc_tfvars_file, gc_nodeclass_file, latest_gc_ctrl, latest_gc_agent),
        },
    }


@router.post("/cloudbees-dev-apply")
async def apply_cloudbees_dev_changes(
    request: Request,
    body: CloudBeesDevApplyRequest,
    current_user: dict = Depends(get_current_user),
):
    """Commit CloudBees chart and AMI updates to the maintenance branch."""
    settings = get_settings()
    gh_token = _gh_write_token(current_user)
    if not gh_token:
        raise HTTPException(status_code=500, detail="GITHUB_TOKEN is not configured")

    org = settings.GITHUB_ORG
    repo = settings.GITHUB_DEFAULT_REPO or "cmscloud-devops"
    branch = body.branch
    committed: list[str] = []
    errors: list[str] = []

    # Preview is read-only; ensure the branch exists here on the explicit Apply
    # action (idempotent — reuses a pre-existing branch, never re-creates).
    try:
        await get_or_create_branch(gh_token, org, repo, branch)
        # Optionally bring a pre-existing (possibly stale) branch up to date with main.
        if body.rebase_from_main:
            merged = await merge_main_into_branch(gh_token, org, repo, branch)
            if merged["updated"]:
                committed.append(f"(merged main into {branch})")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"GitHub branch error: {exc}") from exc

    async def commit_file(path: str, transform, message: str) -> None:
        try:
            f = await get_file(gh_token, org, repo, path, branch)
            new_content = transform(f["content"])
            if new_content == f["content"]:
                return
            await put_file(gh_token, org, repo, path, new_content, f["sha"], message, branch)
            committed.append(path)
        except Exception as e:
            logger.error("Failed to commit %s: %s", path, e)
            errors.append(f"{path}: {e}")

    # CloudBees Core chart version + tag (shared base)
    if body.new_chart_version or body.new_chart_tag:
        async def _patch_core(content: str) -> str:
            if body.new_chart_version:
                content = cb.patch_chart_version(content, body.new_chart_version)
            if body.new_chart_tag:
                content = cb.patch_image_tag(content, body.new_chart_tag)
            return content

        await commit_file(
            cb.CB_CORE_BASE_PATH,
            lambda c: (cb.patch_image_tag(cb.patch_chart_version(c, body.new_chart_version) if body.new_chart_version else c, body.new_chart_tag) if body.new_chart_tag else (cb.patch_chart_version(c, body.new_chart_version) if body.new_chart_version else c)),
            f"chore(cbj-dev): update CloudBees Core to {body.new_chart_version or 'current'} / {body.new_chart_tag or 'current'}",
        )

    # Karpenter OCI chart tags (shared base for all jenkins clusters)
    if body.karpenter_version:
        await commit_file(
            cb.CB_OCI_REPOS["karpenter"]["file"],
            lambda c, v=body.karpenter_version: cb.patch_oci_tag(c, v),
            f"chore(cbj): update Karpenter chart to {body.karpenter_version}",
        )
    if body.karpenter_crd_version:
        await commit_file(
            cb.CB_OCI_REPOS["karpenter-crd"]["file"],
            lambda c, v=body.karpenter_crd_version: cb.patch_oci_tag(c, v),
            f"chore(cbj): update Karpenter CRD chart to {body.karpenter_crd_version}",
        )

    # dev-east AMIs
    if body.dev_east_controller_ami:
        ami, name = body.dev_east_controller_ami, body.dev_east_controller_ami_name or ""
        creg = cb.CB_ENVS["dev-east"]["controller_ami_region"]
        await commit_file(
            cb.CB_ENVS["dev-east"]["tfvars_path"],
            lambda c, a=ami, n=name, r=creg: cb.patch_eks_ami_in_tfvars(c, a, n, r),
            f"chore(cbj-dev-east): update controller AMI to {ami}",
        )
        await commit_file(
            cb.CB_ENVS["dev-east"]["nodeclass_path"],
            lambda c, a=ami, n=name, r=creg: cb.patch_controller_ami(c, a, n, r),
            f"chore(cbj-dev-east): update Karpenter controller nodeclass AMI to {ami}",
        )

    if body.dev_east_agent_ami:
        ami, name = body.dev_east_agent_ami, body.dev_east_agent_ami_name or ""
        areg = cb.CB_ENVS["dev-east"]["agent_ami_region"]
        await commit_file(
            cb.CB_ENVS["dev-east"]["nodeclass_path"],
            lambda c, a=ami, n=name, r=areg: cb.patch_agent_ami(c, a, n, r),
            f"chore(cbj-dev-east): update Karpenter agent nodeclass AMI to {ami}",
        )

    # gc-dev-west AMIs
    if body.gc_dev_west_controller_ami:
        ami, name = body.gc_dev_west_controller_ami, body.gc_dev_west_controller_ami_name or ""
        creg = cb.CB_ENVS["gc-dev-west"]["controller_ami_region"]
        await commit_file(
            cb.CB_ENVS["gc-dev-west"]["tfvars_path"],
            lambda c, a=ami, n=name, r=creg: cb.patch_eks_ami_in_tfvars(c, a, n, r),
            f"chore(cbj-gc-dev-west): update controller AMI to {ami}",
        )
        await commit_file(
            cb.CB_ENVS["gc-dev-west"]["nodeclass_path"],
            lambda c, a=ami, n=name, r=creg: cb.patch_controller_ami(c, a, n, r),
            f"chore(cbj-gc-dev-west): update Karpenter controller nodeclass AMI to {ami}",
        )

    if body.gc_dev_west_agent_ami:
        ami, name = body.gc_dev_west_agent_ami, body.gc_dev_west_agent_ami_name or ""
        areg = cb.CB_ENVS["gc-dev-west"]["agent_ami_region"]
        await commit_file(
            cb.CB_ENVS["gc-dev-west"]["nodeclass_path"],
            lambda c, a=ami, n=name, r=areg: cb.patch_agent_ami(c, a, n, r),
            f"chore(cbj-gc-dev-west): update Karpenter agent nodeclass AMI to {ami}",
        )

    if errors:
        raise HTTPException(
            status_code=502,
            detail=f"Some commits failed: {'; '.join(errors)}. Succeeded: {committed}",
        )

    audit.log_event(
        "maintenance.cloudbees_dev_apply",
        current_user["username"],
        details={"branch": branch, "committed_files": committed},
        ip=request.client.host if request.client else None,
    )
    branch_url = f"https://github.com/{org}/{repo}/tree/{branch}"
    return {"committed_files": committed, "branch": branch, "branch_url": branch_url}


# ─── CloudBees CI Prod Maintenance ────────────────────────────────────────────

@router.get("/cloudbees-prod-params")
async def get_cloudbees_prod_params(current_user: dict = Depends(get_current_user)):
    """
    Fetch current CloudBees Core chart version, image tag, and AMIs for prod
    environments from the maintenance branch.
    """
    settings = get_settings()
    if not settings.GITHUB_TOKEN:
        raise HTTPException(status_code=500, detail="GITHUB_TOKEN is not configured")

    org = settings.GITHUB_ORG
    repo = settings.GITHUB_DEFAULT_REPO or "cmscloud-devops"
    branch = maint_branch_name()

    # Read-only branch lookup — do not create the branch on preview/open.
    try:
        branch_info = await get_branch_or_none(settings.GITHUB_TOKEN, org, repo, branch)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"GitHub branch error: {exc}") from exc

    branch_exists = branch_info is not None
    branch_url = f"https://github.com/{org}/{repo}/tree/{branch}"
    ref = branch if branch_exists else "main"

    async def safe_get(path: str):
        try:
            return await get_file(settings.GITHUB_TOKEN, org, repo, path, ref)
        except Exception as e:
            logger.warning("Could not read %s from branch %s: %s", path, ref, e)
            return None

    (
        cb_core_file,
        pe_tfvars_file, pe_nodeclass_file,
        gc_tfvars_file, gc_nodeclass_file,
    ) = await asyncio.gather(
        safe_get(cb.CB_CORE_BASE_PATH),
        safe_get(cb.CB_ENVS["prod-east"]["tfvars_path"]),
        safe_get(cb.CB_ENVS["prod-east"]["nodeclass_path"]),
        safe_get(cb.CB_ENVS["gc-prod-west"]["tfvars_path"]),
        safe_get(cb.CB_ENVS["gc-prod-west"]["nodeclass_path"]),
    )

    # Commercial AMI is the same across all accounts — fetch via dev-east (JFrog Dev Pod Identity).
    # GovCloud prod shares the same AMI as GovCloud dev — use the same GovCloud credentials for both.
    gc_role_arn = settings.GOVCLOUD_DEV_ROLE_ARN or None
    gc_key_id = settings.GOVCLOUD_AWS_ACCESS_KEY_ID or None
    gc_secret = settings.GOVCLOUD_AWS_SECRET_ACCESS_KEY or None

    # See the dev note: the image follows the running version, not the declared one.
    pe_eks = await eks_upgrade.running_version(
        "cbj-prod-east", settings,
        eks_upgrade.extract_eks_version(pe_tfvars_file["content"]) if pe_tfvars_file else None)
    gcp_eks = await eks_upgrade.running_version(
        "cbj-gc-prod-west", settings,
        eks_upgrade.extract_eks_version(gc_tfvars_file["content"]) if gc_tfvars_file else None)

    (
        latest_cb, latest_pe_ctrl, latest_gc_ctrl,
        latest_pe_agent, latest_gc_agent,
    ) = await asyncio.gather(
        cb.fetch_latest_cb_version(),
        cb.fetch_latest_controller_ami("dev-east", eks_version=pe_eks),
        cb.fetch_latest_controller_ami("gc-dev-west", assume_role_arn=gc_role_arn, aws_access_key_id=gc_key_id, aws_secret_access_key=gc_secret, eks_version=gcp_eks),
        cb.fetch_latest_agent_ami("dev-east", eks_version=pe_eks),
        cb.fetch_latest_agent_ami("gc-dev-west", assume_role_arn=gc_role_arn, aws_access_key_id=gc_key_id, aws_secret_access_key=gc_secret, eks_version=gcp_eks),
        return_exceptions=True,
    )

    def _safe(result, fallback=None):
        return result if not isinstance(result, Exception) else (fallback or {"error": str(result)})

    latest_cb       = _safe(latest_cb, {})
    latest_pe_ctrl  = _safe(latest_pe_ctrl, {})
    latest_gc_ctrl  = _safe(latest_gc_ctrl, {})
    latest_pe_agent = _safe(latest_pe_agent, {})
    latest_gc_agent = _safe(latest_gc_agent, {})

    current_version = cb.extract_chart_version(cb_core_file["content"]) if cb_core_file else None
    current_tag     = cb.extract_image_tag(cb_core_file["content"]) if cb_core_file else None
    latest_version  = latest_cb.get("version")
    latest_tag      = latest_cb.get("app_version")
    has_chart_update = bool(current_version and latest_version and current_version != latest_version)

    release_notes: dict = {"available": False}
    if has_chart_update and current_tag and latest_tag:
        try:
            release_notes = await cb.fetch_cb_release_notes(current_tag, latest_tag)
        except Exception as exc:
            logger.warning("CB release notes fetch failed: %s", exc)

    chart_section = {
        "file": cb.CB_CORE_BASE_PATH,
        "current_version": current_version,
        "current_tag": current_tag,
        "latest_version": latest_version,
        "latest_tag": latest_tag,
        "has_update": has_chart_update,
        "changelog_url": "https://docs.cloudbees.com/docs/release-notes/latest/cloudbees-ci/",
        "release_notes": release_notes,
    }

    def _env_section(env_key: str, tfvars_file, nodeclass_file, latest_ctrl: dict, latest_agent: dict) -> dict:
        cfg = cb.CB_ENVS[env_key]
        ctrl_current   = cb.extract_eks_ami_from_tfvars(tfvars_file["content"]) if tfvars_file else None
        ctrl_nodeclass = cb.extract_controller_ami(nodeclass_file["content"]) if nodeclass_file else None
        agent_current  = cb.extract_agent_ami(nodeclass_file["content"]) if nodeclass_file else None
        return {
            "label": cfg["label"],
            "current_controller_ami": ctrl_current,
            "current_controller_ami_nodeclass": ctrl_nodeclass,
            "latest_controller_ami": latest_ctrl.get("ami_id"),
            "latest_controller_ami_name": latest_ctrl.get("ami_name"),
            "controller_has_update": bool(ctrl_current and latest_ctrl.get("ami_id") and ctrl_current != latest_ctrl.get("ami_id")),
            "current_agent_ami": agent_current,
            "latest_agent_ami": latest_agent.get("ami_id"),
            "latest_agent_ami_name": latest_agent.get("ami_name"),
            "agent_has_update": bool(agent_current and latest_agent.get("ami_id") and agent_current != latest_agent.get("ami_id")),
            "controller_error": latest_ctrl.get("error"),
            "agent_error": latest_agent.get("error"),
        }

    karpenter_rows = await _cb_karpenter_rows(safe_get)

    return {
        "branch": branch,
        "branch_created": False,
        "branch_exists": branch_exists,
        "branch_url": branch_url,
        "chart": chart_section,
        "oci_repos": karpenter_rows,
        "envs": {
            "prod-east":    _env_section("prod-east",    pe_tfvars_file, pe_nodeclass_file, latest_pe_ctrl, latest_pe_agent),
            "gc-prod-west": _env_section("gc-prod-west", gc_tfvars_file, gc_nodeclass_file, latest_gc_ctrl, latest_gc_agent),
        },
    }


@router.post("/cloudbees-prod-apply")
async def apply_cloudbees_prod_changes(
    request: Request,
    body: CloudBeesProdApplyRequest,
    current_user: dict = Depends(get_current_user),
):
    """Commit CloudBees chart and AMI updates for prod to the maintenance branch."""
    settings = get_settings()
    gh_token = _gh_write_token(current_user)
    if not gh_token:
        raise HTTPException(status_code=500, detail="GITHUB_TOKEN is not configured")

    org = settings.GITHUB_ORG
    repo = settings.GITHUB_DEFAULT_REPO or "cmscloud-devops"
    branch = body.branch
    committed: list[str] = []
    errors: list[str] = []

    # Preview is read-only; ensure the branch exists here on the explicit Apply
    # action (idempotent — reuses a pre-existing branch, never re-creates).
    try:
        await get_or_create_branch(gh_token, org, repo, branch)
        # Optionally bring a pre-existing (possibly stale) branch up to date with main.
        if body.rebase_from_main:
            merged = await merge_main_into_branch(gh_token, org, repo, branch)
            if merged["updated"]:
                committed.append(f"(merged main into {branch})")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"GitHub branch error: {exc}") from exc

    async def commit_file(path: str, transform, message: str) -> None:
        try:
            f = await get_file(gh_token, org, repo, path, branch)
            new_content = transform(f["content"])
            if new_content == f["content"]:
                return
            await put_file(gh_token, org, repo, path, new_content, f["sha"], message, branch)
            committed.append(path)
        except Exception as e:
            logger.error("Failed to commit %s: %s", path, e)
            errors.append(f"{path}: {e}")

    if body.new_chart_version or body.new_chart_tag:
        await commit_file(
            cb.CB_CORE_BASE_PATH,
            lambda c: (cb.patch_image_tag(cb.patch_chart_version(c, body.new_chart_version) if body.new_chart_version else c, body.new_chart_tag) if body.new_chart_tag else (cb.patch_chart_version(c, body.new_chart_version) if body.new_chart_version else c)),
            f"chore(cbj-prod): update CloudBees Core to {body.new_chart_version or 'current'} / {body.new_chart_tag or 'current'}",
        )

    # Karpenter OCI chart tags (shared base for all jenkins clusters)
    if body.karpenter_version:
        await commit_file(
            cb.CB_OCI_REPOS["karpenter"]["file"],
            lambda c, v=body.karpenter_version: cb.patch_oci_tag(c, v),
            f"chore(cbj): update Karpenter chart to {body.karpenter_version}",
        )
    if body.karpenter_crd_version:
        await commit_file(
            cb.CB_OCI_REPOS["karpenter-crd"]["file"],
            lambda c, v=body.karpenter_crd_version: cb.patch_oci_tag(c, v),
            f"chore(cbj): update Karpenter CRD chart to {body.karpenter_crd_version}",
        )

    if body.prod_east_controller_ami:
        ami, name = body.prod_east_controller_ami, body.prod_east_controller_ami_name or ""
        creg = cb.CB_ENVS["prod-east"]["controller_ami_region"]
        await commit_file(
            cb.CB_ENVS["prod-east"]["tfvars_path"],
            lambda c, a=ami, n=name, r=creg: cb.patch_eks_ami_in_tfvars(c, a, n, r),
            f"chore(cbj-prod-east): update controller AMI to {ami}",
        )
        await commit_file(
            cb.CB_ENVS["prod-east"]["nodeclass_path"],
            lambda c, a=ami, n=name, r=creg: cb.patch_controller_ami(c, a, n, r),
            f"chore(cbj-prod-east): update Karpenter controller nodeclass AMI to {ami}",
        )

    if body.prod_east_agent_ami:
        ami, name = body.prod_east_agent_ami, body.prod_east_agent_ami_name or ""
        areg = cb.CB_ENVS["prod-east"]["agent_ami_region"]
        await commit_file(
            cb.CB_ENVS["prod-east"]["nodeclass_path"],
            lambda c, a=ami, n=name, r=areg: cb.patch_agent_ami(c, a, n, r),
            f"chore(cbj-prod-east): update Karpenter agent nodeclass AMI to {ami}",
        )

    if body.gc_prod_west_controller_ami:
        ami, name = body.gc_prod_west_controller_ami, body.gc_prod_west_controller_ami_name or ""
        creg = cb.CB_ENVS["gc-prod-west"]["controller_ami_region"]
        await commit_file(
            cb.CB_ENVS["gc-prod-west"]["tfvars_path"],
            lambda c, a=ami, n=name, r=creg: cb.patch_eks_ami_in_tfvars(c, a, n, r),
            f"chore(cbj-gc-prod-west): update controller AMI to {ami}",
        )
        await commit_file(
            cb.CB_ENVS["gc-prod-west"]["nodeclass_path"],
            lambda c, a=ami, n=name, r=creg: cb.patch_controller_ami(c, a, n, r),
            f"chore(cbj-gc-prod-west): update Karpenter controller nodeclass AMI to {ami}",
        )

    if body.gc_prod_west_agent_ami:
        ami, name = body.gc_prod_west_agent_ami, body.gc_prod_west_agent_ami_name or ""
        areg = cb.CB_ENVS["gc-prod-west"]["agent_ami_region"]
        await commit_file(
            cb.CB_ENVS["gc-prod-west"]["nodeclass_path"],
            lambda c, a=ami, n=name, r=areg: cb.patch_agent_ami(c, a, n, r),
            f"chore(cbj-gc-prod-west): update Karpenter agent nodeclass AMI to {ami}",
        )

    if errors:
        raise HTTPException(
            status_code=502,
            detail=f"Some commits failed: {'; '.join(errors)}. Succeeded: {committed}",
        )

    audit.log_event(
        "maintenance.cloudbees_prod_apply",
        current_user["username"],
        details={"branch": branch, "committed_files": committed},
        ip=request.client.host if request.client else None,
    )
    branch_url = f"https://github.com/{org}/{repo}/tree/{branch}"
    return {"committed_files": committed, "branch": branch, "branch_url": branch_url}


# ─── Maintenance Prep ─────────────────────────────────────────────────────────

def _sprint_covering_date(sprints: list[dict], target: date) -> dict | None:
    """Return the sprint whose [startDate, endDate] window contains `target`, else None."""
    from datetime import datetime as _dt
    for s in sprints:
        sd, ed = s.get("startDate"), s.get("endDate")
        if not sd or not ed:
            continue
        try:
            start = _dt.fromisoformat(sd.replace("Z", "+00:00")).date()
            end   = _dt.fromisoformat(ed.replace("Z", "+00:00")).date()
        except ValueError:
            continue
        if start <= target <= end:
            return s
    return None


def _project_sprint_covering(sprints: list[dict], target: date) -> dict | None:
    """Project future sprints forward (following the latest sprint's cadence) until
    one covers `target`; return that projected sprint (id=None, state="projected")
    so the UI can offer to create it. Returns None if no dated sprints exist."""
    from datetime import datetime as _dt, timedelta as _td
    import re as _re

    dated = [s for s in sprints if s.get("startDate") and s.get("endDate")]
    if not dated:
        return None
    try:
        anchor  = max(dated, key=lambda s: _dt.fromisoformat(s["endDate"].replace("Z", "+00:00")))
        a_start = _dt.fromisoformat(anchor["startDate"].replace("Z", "+00:00"))
        a_end   = _dt.fromisoformat(anchor["endDate"].replace("Z", "+00:00"))
    except ValueError:
        return None

    duration = a_end - a_start
    if duration.total_seconds() <= 0:
        duration = _td(days=21)  # sensible default 3-week sprint
    base_name = _re.sub(r'\s*\d+$', '', anchor["name"]).strip()
    m = _re.search(r'(\d+)$', anchor["name"])
    num = int(m.group(1)) if m else None

    p_start, p_end = a_start, a_end
    for _ in range(12):  # cap the projection horizon
        p_start = p_end
        p_end   = p_start + duration
        if num is not None:
            num += 1
        if p_start.date() <= target <= p_end.date():
            name = f"{base_name} {num}" if num is not None else f"{anchor['name']} (next)"
            return {
                "id":        None,
                "name":      name,
                "state":     "projected",
                "startDate": p_start.isoformat(),
                "endDate":   p_end.isoformat(),
            }
    return None


@router.get("/maint-prep-params")
async def get_maint_prep_params(current_user: dict = Depends(get_current_user)):
    """Return the next maintenance date, rotation assignees, and available sprints.
    Also detects the sprint that overlaps the maintenance window (recommended_sprint_id);
    if none overlaps, includes a projected sprint the engineer can create."""
    _require_itc_author(current_user)
    maint_date = get_next_maintenance_date()
    maint_date_str = maint_date.strftime("%B %-d, %Y")

    rotation, sprints = await asyncio.gather(
        asyncio.to_thread(get_maint_prep_rotation),
        asyncio.to_thread(get_dmsc_sprints),
        return_exceptions=True,
    )

    if isinstance(rotation, Exception):
        raise HTTPException(status_code=502, detail=f"Could not fetch rotation: {rotation}")
    if isinstance(sprints, Exception):
        raise HTTPException(status_code=502, detail=f"Could not fetch sprints: {sprints}")

    # Detect the sprint whose window contains the maintenance date. If one exists,
    # recommend it; otherwise project a new sprint that would cover it so the UI
    # can suggest creating one.
    covering = _sprint_covering_date(sprints, maint_date)
    projected = None if covering else _project_sprint_covering(sprints, maint_date)
    all_sprints = sprints + ([projected] if projected else [])

    return {
        "maint_date": maint_date.isoformat(),
        "maint_date_str": maint_date_str,
        "rotation": rotation,
        "sprints": all_sprints,
        "recommended_sprint_id": covering["id"] if covering else None,
        "projected_sprint": projected,
    }


@router.get("/ticket-readiness")
async def ticket_readiness(current_user: dict = Depends(get_current_user)):
    """Days until maintenance + whether it's time to create tickets (bell source)."""
    from app.services.maint_notify import ticket_readiness as _readiness
    return await asyncio.to_thread(_readiness)


@router.post("/notify-test")
async def notify_test(current_user: dict = Depends(get_current_user)):
    """Send a TEST maintenance reminder email to the configured recipients."""
    _require_itc_author(current_user)
    from app.services.maint_notify import send_reminder
    return await asyncio.to_thread(send_reminder, True)


@router.get("/prep-status")
async def maint_prep_status(current_user: dict = Depends(get_current_user)):
    """Report whether this window's maintenance prep tickets exist (read-only).
    Used to gate ITC/MGGD creation (prep is a prerequisite) and to source the
    per-tool assignees for the IR plan."""
    maint_date = get_next_maintenance_date()
    maint_date_str = maint_date.strftime("%B %-d, %Y")
    status_info = await asyncio.to_thread(get_maint_prep_status, maint_date_str)
    return {"maint_date": maint_date.isoformat(), "maint_date_str": maint_date_str, **status_info}


@router.post("/maint-prep-create", status_code=status.HTTP_201_CREATED)
async def create_maint_prep(
    request: Request,
    body: MaintPrepCreateRequest,
    current_user: dict = Depends(get_current_user),
):
    """Create the 3 monthly maintenance prep tickets and add them to the sprint.
    If sprint_id is None, creates a new sprint first from the supplied name/dates."""
    _require_itc_author(current_user)

    sprint_id = body.sprint_id
    if sprint_id is None:
        if not body.new_sprint_name or not body.new_sprint_start or not body.new_sprint_end:
            raise HTTPException(
                status_code=422,
                detail="new_sprint_name, new_sprint_start and new_sprint_end are required when sprint_id is not provided.",
            )
        try:
            new_sprint = await asyncio.to_thread(
                create_dmsc_sprint,
                body.new_sprint_name,
                body.new_sprint_start,
                body.new_sprint_end,
            )
            sprint_id = new_sprint["id"]
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Failed to create sprint: {exc}")

    try:
        tickets = await asyncio.to_thread(
            create_maint_prep_tickets,
            sprint_id,
            body.maint_date_str,
            body.jfrog_assignee,
            body.cloudbees_assignee,
            body.sonarqube_assignee,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    audit.log_event(
        "maintenance.maint_prep_create",
        current_user["username"],
        details={"sprint_id": sprint_id, "tickets": [t["key"] for t in tickets]},
        ip=request.client.host if request.client else None,
    )
    try:
        from app.services.maint_notify import send_confirmation
        await asyncio.to_thread(send_confirmation, "Prep", tickets, body.maint_date_str)
    except Exception as exc:  # noqa: BLE001 — confirmation email is best-effort
        logging.getLogger(__name__).warning("prep confirmation email failed: %s", exc)
    return {"tickets": tickets}


# ─── On-Call Tickets ──────────────────────────────────────────────────────────

@router.get("/on-call-params")
async def get_on_call_params(current_user: dict = Depends(get_current_user)):
    """
    Return available sprints, the on-call team roster, and VictorOps-sourced
    per-week on-call assignments for the first active/future sprint.
    """
    _require_itc_author(current_user)

    try:
        sprints = await asyncio.to_thread(get_dmsc_sprints)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not fetch sprints: {exc}")

    # Use the future sprint if it exists; otherwise project dates from the active sprint
    from datetime import datetime, timedelta, timezone as _tz
    future_sprint = next((s for s in sprints if s["state"] == "future"), None)
    active_sprint = next((s for s in sprints if s["state"] == "active"), None)

    projected_sprint: dict | None = None
    if not future_sprint and active_sprint and active_sprint.get("startDate") and active_sprint.get("endDate"):
        try:
            a_start = datetime.fromisoformat(active_sprint["startDate"].replace("Z", "+00:00"))
            a_end   = datetime.fromisoformat(active_sprint["endDate"].replace("Z", "+00:00"))
            duration = a_end - a_start
            p_start  = a_end
            p_end    = a_end + duration
            # Parse sprint number from name e.g. "Cloud Sprint 33" → "Cloud Sprint 34"
            import re as _re
            m = _re.search(r'(\d+)$', active_sprint["name"])
            next_num   = int(m.group(1)) + 1 if m else ""
            base_name  = _re.sub(r'\s*\d+$', '', active_sprint["name"]).strip()
            proj_name  = f"{base_name} {next_num}" if next_num else f"{active_sprint['name']} (next)"
            projected_sprint = {
                "id":        None,
                "name":      proj_name,
                "state":     "projected",
                "startDate": p_start.isoformat(),
                "endDate":   p_end.isoformat(),
            }
        except Exception as exc:
            logger.warning("Could not project next sprint dates: %s", exc)

    target = future_sprint or projected_sprint
    suggestions: list[dict] = []
    if target and target.get("startDate") and target.get("endDate"):
        try:
            suggestions = await asyncio.to_thread(
                get_sprint_oncall_assignments,
                target["startDate"],
                target["endDate"],
            )
        except Exception as exc:
            logger.warning("VictorOps on-call lookup failed: %s", exc)

    # Combine real sprints + projected sprint for the frontend
    all_sprints = sprints + ([projected_sprint] if projected_sprint else [])

    return {
        "sprints":     all_sprints,
        "team":        ON_CALL_TEAM,
        "suggestions": suggestions,
    }


@router.post("/on-call-create", status_code=status.HTTP_201_CREATED)
async def create_on_call(
    request: Request,
    body: OnCallCreateRequest,
    current_user: dict = Depends(get_current_user),
):
    """Create on-call Story tickets for each week and add them to the sprint.
    If sprint_id is None, creates a new sprint first using the supplied name/dates."""
    _require_itc_author(current_user)

    sprint_id = body.sprint_id
    sprint_name = None

    if sprint_id is None:
        if not body.new_sprint_name or not body.new_sprint_start or not body.new_sprint_end:
            raise HTTPException(status_code=422, detail="new_sprint_name, new_sprint_start and new_sprint_end are required when sprint_id is not provided.")
        try:
            new_sprint = await asyncio.to_thread(
                create_dmsc_sprint,
                body.new_sprint_name,
                body.new_sprint_start,
                body.new_sprint_end,
            )
            sprint_id = new_sprint["id"]
            sprint_name = new_sprint["name"]
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Failed to create sprint: {exc}")

    try:
        tickets = await asyncio.to_thread(
            create_on_call_tickets,
            sprint_id,
            [{"week": w.week, "assignee": w.assignee} for w in body.weeks],
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    audit.log_event(
        "maintenance.on_call_create",
        current_user["username"],
        details={"sprint_id": sprint_id, "sprint_name": sprint_name, "tickets": [t["key"] for t in tickets]},
        ip=request.client.host if request.client else None,
    )
    return {"tickets": tickets, "sprint_id": sprint_id, "sprint_name": sprint_name}


# ─── Retro Pages ──────────────────────────────────────────────────────────────


@router.get("/retro-preview")
async def get_retro_preview(current_user: dict = Depends(get_current_user)):
    """Return the titles the two retro widgets would create, plus existence checks."""
    _require_itc_author(current_user)
    try:
        return await asyncio.to_thread(preview_retro_titles)
    except Exception as exc:
        logger.error("Failed to preview retro titles: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/retro-maintenance", status_code=status.HTTP_201_CREATED)
async def create_maint_retro(
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """Create a maintenance retro page under COM/Maintenance Retros."""
    _require_itc_author(current_user)
    try:
        result = await asyncio.to_thread(create_maintenance_retro_page)
    except Exception as exc:
        logger.error("Failed to create maintenance retro page: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    audit.log_event(
        "maintenance.retro_maintenance",
        current_user["username"],
        details={"title": result.get("title"), "already_existed": result.get("already_existed")},
        ip=request.client.host if request.client else None,
    )
    return result


@router.post("/retro-sprint", status_code=status.HTTP_201_CREATED)
async def create_sprint_retro(
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """Create a sprint retro page under COM/DevOps Sprint Retros."""
    _require_itc_author(current_user)
    try:
        result = await asyncio.to_thread(create_sprint_retro_page)
    except Exception as exc:
        logger.error("Failed to create sprint retro page: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    audit.log_event(
        "maintenance.retro_sprint",
        current_user["username"],
        details={"title": result.get("title"), "already_existed": result.get("already_existed")},
        ip=request.client.host if request.client else None,
    )
    return result


# ─── OE (Open Enrollment) DevOps Readiness ────────────────────────────────────

class OEApplyRequest(BaseModel):
    year: int
    selections: dict[str, list[str]]   # {"cbj": [...keys...], "jfrog_sonar": [...]}
    overwrite: bool = False


class OECloseCcoeRequest(BaseModel):
    year: int
    kind: str   # 'cbj' | 'jfrog_sonar'


@router.get("/oe-readiness/preview")
async def oe_readiness_preview(
    year: int,
    current_user: dict = Depends(get_current_user),
):
    """Discover the year's OE readiness page(s) and return the best-effort fill plan."""
    try:
        return await oe_readiness.build_preview(year)
    except Exception as exc:
        logger.error("OE readiness preview failed for %s: %s", year, exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/oe-readiness/apply")
async def oe_readiness_apply(
    body: OEApplyRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """Create the SRE tickets, then inject the selected sections into the OE page(s).

    SRE (CLDSRE) tickets are created first (idempotent) so their links land in the
    page's Monitoring section.
    """
    try:
        result = await oe_readiness.apply(
            body.year, body.selections, overwrite=body.overwrite,
            engineer=current_user["username"],
        )
    except Exception as exc:
        logger.error("OE readiness apply failed for %s: %s", body.year, exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    written = {r["kind"]: r["written"] for r in result.get("results", [])}
    audit.log_event(
        "maintenance.oe_readiness_apply",
        current_user["username"],
        details={"year": body.year, "written": written, "overwrite": body.overwrite,
                 "sre_tickets": [t.get("key") for t in result.get("sre", []) if t.get("key")]},
        ip=request.client.host if request.client else None,
    )
    return result


@router.post("/oe-readiness/close-ccoe")
async def oe_readiness_close_ccoe(
    body: OECloseCcoeRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """Transition the page's assigned CCOE ticket to Done (after verification)."""
    try:
        result = await oe_readiness.close_ccoe_for(body.year, body.kind)
    except Exception as exc:
        logger.error("OE readiness close-ccoe failed for %s/%s: %s", body.year, body.kind, exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    audit.log_event(
        "maintenance.oe_readiness_close_ccoe",
        current_user["username"],
        details={"year": body.year, "kind": body.kind, "result": result},
        ip=request.client.host if request.client else None,
    )
    return result
