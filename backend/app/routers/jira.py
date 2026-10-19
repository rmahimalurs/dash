import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel, Field

from app.auth.jwt import get_current_user
from app.services import audit, cldspt_tickets

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/jira", tags=["jira"])


@router.get("/cldspt/queue")
async def get_queue(current_user: dict = Depends(get_current_user)):
    """Cached open-CLDSPT counts per engineer and per status bucket.

    Returns the cache as-is, including when it is missing, so the page can say
    the sweep has not run rather than hanging on a slow Jira search. Who has
    already been nudged is the one thing added on top, because it changes
    between sweeps.
    """
    cached = cldspt_tickets.read_cache()
    if cached is None:
        return {
            "generated_at": None,
            "engineers": [],
            "by_status": {},
            "by_bucket": {},
            "bucket_labels": cldspt_tickets.BUCKET_LABELS,
            "open_buckets": list(cldspt_tickets.OPEN_BUCKETS),
            "all_time_total": None,
            "open_total": None,
            "last_nudged": {},
            "error": "No sweep has run yet.",
        }
    # Attached on read, not stored in the cache: a nudge happens between sweeps,
    # and a stale answer here would let the approver be messaged twice.
    return {**cached, "last_nudged": cldspt_tickets.recent_nudges()}


@router.post("/cldspt/sweep")
async def start_sweep(current_user: dict = Depends(get_current_user)):
    return cldspt_tickets.start_background_sweep()


@router.get("/cldspt/sweep-status")
async def get_sweep_status(current_user: dict = Depends(get_current_user)):
    return cldspt_tickets.sweep_status()


@router.post("/cldspt/{issue_key}/request-bo-approval")
async def post_bo_approval_request(
    issue_key: str = Path(pattern=r"^CLDSPT-\d+$"),
    current_user: dict = Depends(get_current_user),
):
    """Ask the requester to get their Business Owner's approval. Audited."""
    who = current_user.get("username", "?")
    result = await asyncio.to_thread(cldspt_tickets.request_bo_approval, issue_key, who)
    audit.log_event(
        "jira.bo_approval_requested",
        who,
        details={"key": issue_key, "posted": result.get("posted"),
                 "error": result.get("error")},
    )
    if not result.get("posted"):
        raise HTTPException(status_code=409, detail=result.get("error") or "Could not post the request.")
    return result


@router.post("/cldspt/{issue_key}/request-second-stage-approval")
async def post_second_stage_approval_request(
    issue_key: str = Path(pattern=r"^CLDSPT-\d+$"),
    current_user: dict = Depends(get_current_user),
):
    """Ask the second-stage approver to sign off, once a Business Owner has. Audited."""
    who = current_user.get("username", "?")
    result = await asyncio.to_thread(
        cldspt_tickets.request_second_stage_approval, issue_key, who)
    audit.log_event(
        "jira.second_stage_approval_requested",
        who,
        details={"key": issue_key, "posted": result.get("posted"),
                 "error": result.get("error")},
    )
    if not result.get("posted"):
        raise HTTPException(status_code=409, detail=result.get("error") or "Could not post the request.")
    return result


@router.post("/cldspt/engineer/{username}/slack-nudge")
async def post_slack_approval_nudge(
    username: str,
    current_user: dict = Depends(get_current_user),
):
    """Ask the second-stage approver on Slack for one engineer's approved-by-BO tickets.

    Posts directly when a Slack bot token is configured; otherwise returns the
    message so the page can hand it to the clipboard. Audited either way.
    """
    who = current_user.get("username", "?")
    result = await asyncio.to_thread(
        cldspt_tickets.slack_approval_nudge, username.upper(),
        current_user.get("display_name") or who)
    audit.log_event(
        "jira.slack_approval_nudge",
        who,
        details={"engineer": username.upper(), "posted": result.get("posted"),
                 "tickets": result.get("tickets"), "error": result.get("error")},
    )
    if result.get("error"):
        raise HTTPException(status_code=409, detail=result["error"])
    return result


@router.get("/cldspt/engineer/{username}")
async def get_engineer_tickets(
    username: str,
    include_done: bool = Query(False),
    current_user: dict = Depends(get_current_user),
):
    """One engineer's GitHub requests with status and latest comment, fetched live.

    Not cached: it is a single search scoped to one assignee, and a stale
    comment is more misleading than a short wait.
    """
    return cldspt_tickets.tickets_for(username, include_done=include_done)


@router.get("/cldspt/self-service-queue")
async def get_self_service_queue(current_user: dict = Depends(get_current_user)):
    """Open developer-submitted GitHub requests, oldest first, fetched live."""
    return await asyncio.to_thread(cldspt_tickets.self_service_queue)


@router.get("/cldspt/{issue_key}/transitions")
async def get_issue_transitions(
    issue_key: str = Path(pattern=r"^CLDSPT-\d+$"),
    current_user: dict = Depends(get_current_user),
):
    """The workflow statuses actually available for this ticket right now."""
    return await asyncio.to_thread(cldspt_tickets.issue_transitions, issue_key)


@router.post("/cldspt/{issue_key}/assign-to-me")
async def post_assign_to_me(
    issue_key: str = Path(pattern=r"^CLDSPT-\d+$"),
    current_user: dict = Depends(get_current_user),
):
    """Assign a ticket to the signed-in user. Audited."""
    who = current_user.get("username", "?")
    result = await asyncio.to_thread(cldspt_tickets.assign_issue, issue_key, who.upper())
    audit.log_event(
        "jira.ticket_assigned", who,
        details={"key": issue_key, "assigned": result.get("assigned"), "error": result.get("error")},
    )
    if not result.get("assigned"):
        raise HTTPException(status_code=409, detail=result.get("error") or "Could not assign the ticket.")
    return result


class TransitionBody(BaseModel):
    transition_id: str = Field(min_length=1, max_length=20)
    comment: str | None = Field(default=None, max_length=2000)


@router.post("/cldspt/{issue_key}/transition")
async def post_transition(
    body: TransitionBody,
    issue_key: str = Path(pattern=r"^CLDSPT-\d+$"),
    current_user: dict = Depends(get_current_user),
):
    """Move a ticket to one of its currently valid statuses. Audited."""
    who = current_user.get("username", "?")
    result = await asyncio.to_thread(
        cldspt_tickets.transition_issue, issue_key, body.transition_id, body.comment)
    audit.log_event(
        "jira.ticket_transitioned", who,
        details={"key": issue_key, "transition_id": body.transition_id,
                 "transitioned": result.get("transitioned"), "error": result.get("error")},
    )
    if not result.get("transitioned"):
        raise HTTPException(status_code=409, detail=result.get("error") or "Could not update the ticket.")
    return result
