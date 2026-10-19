import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.auth.jwt import get_current_user
from app.services import (
    audit,
    rbac,
    maintenance_mode,
    slack_directory,
    maint_date_override,
    admin_notify,
    release_announce,
    release_notes,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


def require_admin(current_user: dict = Depends(get_current_user)) -> dict:
    """FastAPI dependency: allow only users with admin role (checked against roles file, not JWT)."""
    username = current_user.get("username", "")
    if rbac.get_role(username) != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return current_user


class RoleUpdate(BaseModel):
    role: Literal["admin", "user"]


class MaintenanceModeUpdate(BaseModel):
    enabled: bool
    message: str | None = None


class MaintDateOverrideUpdate(BaseModel):
    enabled: bool
    date: str | None = None               # "YYYY-MM-DD"
    start_time: str | None = None         # 24-hour "HH:MM"
    end_time: str | None = None
    downtime_end_time: str | None = None
    go_nogo_date: str | None = None       # "YYYY-MM-DD"


@router.get("/maintenance-mode")
async def get_maintenance_mode(current_user: dict = Depends(require_admin)):
    """Return the full maintenance-mode state (admin view)."""
    return maintenance_mode.get_state()


@router.post("/maintenance-mode")
async def set_maintenance_mode(
    body: MaintenanceModeUpdate,
    current_user: dict = Depends(require_admin),
):
    """Enable or disable site-wide maintenance mode."""
    state = maintenance_mode.set_state(body.enabled, current_user.get("username", "?"), body.message)
    audit.log_event(
        "admin.maintenance_mode",
        current_user.get("username", "?"),
        details={"enabled": state["enabled"]},
    )
    return state


@router.get("/maint-date-override")
async def get_maint_date_override(current_user: dict = Depends(require_admin)):
    """Return the maintenance-date override state (admin view)."""
    return maint_date_override.get_state()


@router.post("/maint-date-override")
async def set_maint_date_override(
    body: MaintDateOverrideUpdate,
    current_user: dict = Depends(require_admin),
):
    """Set or clear the maintenance date and window override.

    When enabled, `date` replaces the computed 3rd-Saturday date and the times
    replace the standard 9 AM to 1 PM window. Date and times override
    independently, so either alone is a valid override.
    """
    try:
        state = maint_date_override.set_state(
            body.enabled, body.date, current_user.get("username", "?"),
            start_time=body.start_time, end_time=body.end_time,
            downtime_end_time=body.downtime_end_time,
            go_nogo_date=body.go_nogo_date,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    audit.log_event(
        "admin.maint_date_override",
        current_user.get("username", "?"),
        details={"enabled": state["enabled"], "date": state["date"],
                 "start_time": state["start_time"], "end_time": state["end_time"],
                 "downtime_end_time": state["downtime_end_time"],
                 "go_nogo_date": state["go_nogo_date"]},
    )
    return state


@router.get("/users")
async def list_users(current_user: dict = Depends(require_admin)):
    """Return all registered users and their roles."""
    return rbac.list_users()


@router.put("/users/{username}/role")
async def update_user_role(
    username: str,
    body: RoleUpdate,
    current_user: dict = Depends(require_admin),
):
    """Change a user's role. Takes effect immediately on their next API request."""
    old_role = rbac.get_role(username)
    if old_role == body.role:
        return {"username": username, "role": body.role}

    rbac.set_role(username, body.role)

    # Tell the user they gained admin. Best-effort: the promotion already stands,
    # so a mail failure is reported rather than rolled back.
    notice = None
    if body.role == "admin":
        target = next(
            (u for u in rbac.list_users() if rbac.canonical(u["username"]) == rbac.canonical(username)),
            {},
        )
        notice = admin_notify.send_promotion_notice(
            username,
            target.get("email", ""),
            target.get("display_name", ""),
            current_user.get("display_name") or current_user["username"],
        )

    audit.log_event(
        "admin.role_change",
        current_user["username"],
        details={
            "target_username": username,
            "old_role": old_role,
            "new_role": body.role,
            **({"notified": bool(notice.get("sent")),
                "notify_error": notice.get("error")} if notice else {}),
        },
    )
    logger.info("Admin %s changed role of %s: %s -> %s", current_user["username"], username, old_role, body.role)
    return {
        "username": username,
        "role": body.role,
        **({"notified": bool(notice.get("sent")), "notify_error": notice.get("error")} if notice else {}),
    }


@router.get("/slack-directory")
async def get_slack_directory(current_user: dict = Depends(require_admin)):
    """Return staging metadata (not the full map) for the Slack email->handle directory."""
    return slack_directory.directory_meta()


@router.post("/slack-directory")
async def upload_slack_directory(
    body: dict,
    current_user: dict = Depends(require_admin),
):
    """
    Upload the local slack-cli users cache (or an already-slim map) so the
    backend can resolve ADO emails to Slack handles. The payload is slimmed to
    {email: {handle,id,name}} and stored on EFS. Admin only.
    """
    if not isinstance(body, (dict, list)) or (isinstance(body, dict) and not body):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Body must be the slack-cli users cache JSON or a slim email->handle map",
        )
    try:
        result = slack_directory.save_directory(body)
    except Exception as exc:  # malformed payload shapes surface as 400, not 500
        logger.error("Slack directory upload failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Could not parse Slack directory payload: {exc}",
        )
    if result["count"] == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No usable entries (members with an email) found in the payload",
        )
    audit.log_event(
        "admin.slack_directory_upload",
        current_user.get("username", "?"),
        details={"count": result["count"], "fetched_at": result["fetched_at"]},
    )
    return result


@router.get("/audit")
async def get_audit_log(
    date_from: str | None = None,
    date_to: str | None = None,
    username: str | None = None,
    event_type: str | None = None,
    page: int = 1,
    page_size: int = 50,
    current_user: dict = Depends(require_admin),
):
    """Return paginated audit log entries. Admin only."""
    page_size = min(page_size, 200)
    return audit.get_events(
        date_from=date_from,
        date_to=date_to,
        username=username,
        event_type=event_type,
        page=page,
        page_size=page_size,
    )


class ReleaseAnnounce(BaseModel):
    force: bool = False
    allow_duplicate: bool = False


@router.get("/release-announcement")
async def get_release_announcement(current_user: dict = Depends(require_admin)):
    """What would be posted for this release, and whether it already went out."""
    state = release_announce.read_state()
    version = release_notes.current_release()["version"]
    return {
        "version": version,
        "channel": release_announce.CHANNEL,
        "announced": state.get("version") == version and not state.get("held"),
        "held": state.get("version") == version and bool(state.get("held")),
        "announced_at": state.get("at") if state.get("version") == version else None,
        "announced_by": state.get("by") if state.get("version") == version else None,
        "preview": release_announce.build_message(),
    }


@router.post("/release-announcement")
async def post_release_announcement(
    body: ReleaseAnnounce,
    current_user: dict = Depends(require_admin),
):
    """Post this release to the team channel by hand, or re-post it with force."""
    result = release_announce.announce(
        force=body.force, by=current_user.get("username", "?"),
        allow_duplicate=body.allow_duplicate,
    )
    audit.log_event(
        "admin.release_announcement",
        current_user.get("username", "?"),
        details={
            "version": result.get("version"),
            "posted": result.get("posted"),
            "forced": body.force,
            "allow_duplicate": body.allow_duplicate,
            "reason": result.get("reason"),
        },
    )
    return result
