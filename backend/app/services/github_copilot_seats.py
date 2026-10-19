"""Bulk GitHub Copilot seat assignment, sent with the assigning engineer's
own PAT (never the shared service account). Before writing, checks the
org's seat-management policy and each handle's membership/seat state, so a
non-member or already-seated handle isn't misreported as a failure; after
writing, re-checks seat state per handle since seats_created alone can't
say *which* handles got one.
"""
from __future__ import annotations

import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor

import httpx

from app.config import get_settings
from app.services import audit, bulk_job, bulk_report, github_auth
from app.services.github_http import GH_API, auth_headers, error_detail, request_with_retry

logger = logging.getLogger(__name__)

_MAX_WORKERS = 8

# GitHub username rules: alphanumeric with single (non-consecutive) hyphens,
# can't start or end with a hyphen, max 39 characters.
_HANDLE_RE = re.compile(r"^[A-Za-z0-9](?:-?[A-Za-z0-9]){0,38}$")

SEAT_YES = "seat"
SEAT_NO = "no_seat"
SEAT_UNKNOWN = "unknown"

MEMBER_ACTIVE = "active"
MEMBER_PENDING = "pending"
MEMBER_NONE = "none"
MEMBER_UNKNOWN = "unknown"


def validate_and_dedupe(raw_usernames: list[str]) -> tuple[list[str], list[tuple[str, str]]]:
    """Cleans, format-validates, and case-insensitively dedupes candidate
    handles. Rejects anything containing a space or parenthesis outright
    (catches "octocat (Some Name)") as well as anything that isn't a
    syntactically valid GitHub username.

    Returns (valid, rejected) where rejected is a list of
    (original_value, reason) tuples.
    """
    valid, rejected = [], []
    seen = set()
    for raw in raw_usernames:
        h = str(raw).strip().lstrip("@")
        if not h:
            continue
        if "(" in h or ")" in h or " " in h:
            rejected.append((raw, "looks like 'handle (Name)' or contains a space - "
                                   "pass the bare GitHub handle only, not Name+Handle combined"))
            continue
        if not _HANDLE_RE.match(h):
            rejected.append((raw, "not a syntactically valid GitHub username (letters/digits/single "
                                   "hyphens, can't start/end with a hyphen or contain '--', max 39 chars)"))
            continue
        cf = h.casefold()
        if cf in seen:
            continue
        seen.add(cf)
        valid.append(h)
    return valid, rejected


def get_org_copilot_policy(token: str, org: str) -> str | None:
    """Returns the org's seat_management_setting, or None if it couldn't be
    determined. The selected_users endpoint used below only does anything
    when this is 'assign_selected'."""
    try:
        r = httpx.get(f"{GH_API}/orgs/{org}/copilot/billing", headers=auth_headers(token), timeout=15)
    except httpx.RequestError:
        return None
    if r.status_code != 200:
        return None
    try:
        return r.json().get("seat_management_setting")
    except Exception:  # noqa: BLE001
        return None


def get_seat_state(token: str, org: str, handle: str) -> tuple[str, str]:
    """Only a real HTTP 404 whose message says there is no seat counts as
    SEAT_NO. A permissions error, a rate limit, a 5xx, or an unrecognized
    404 is SEAT_UNKNOWN, so it surfaces as "couldn't tell" rather than a
    confirmed absence or a failed assignment."""
    try:
        r = httpx.get(f"{GH_API}/orgs/{org}/members/{handle}/copilot", headers=auth_headers(token), timeout=15)
    except httpx.RequestError as exc:
        return SEAT_UNKNOWN, f"could not reach GitHub: {exc}"
    if r.status_code == 200:
        return SEAT_YES, ""
    message = error_detail(r)
    if r.status_code == 404 and "no seat found" in message.casefold():
        return SEAT_NO, message
    return SEAT_UNKNOWN, message or f"GitHub returned {r.status_code}"


def get_membership_state(token: str, org: str, handle: str) -> tuple[str, str]:
    """A 404 is a real answer (not a member); anything else non-zero is
    UNKNOWN rather than being assumed to mean "not a member"."""
    try:
        r = httpx.get(f"{GH_API}/orgs/{org}/memberships/{handle}", headers=auth_headers(token), timeout=15)
    except httpx.RequestError as exc:
        return MEMBER_UNKNOWN, f"could not reach GitHub: {exc}"
    if r.status_code == 200:
        state = r.json().get("state")
        if state == "active":
            return MEMBER_ACTIVE, ""
        if state == "pending":
            return MEMBER_PENDING, "invitation not yet accepted"
        return MEMBER_NONE, f"membership state {state!r}"
    message = error_detail(r)
    if r.status_code == 404:
        return MEMBER_NONE, message or "not an org member"
    return MEMBER_UNKNOWN, message or f"GitHub returned {r.status_code}"


def check_membership_and_seats(token: str, org: str, usernames: list[str], on_progress=None) -> dict:
    """Per-user preflight: is this person an org member, and do they already
    have a Copilot seat? Threaded, one call per check per user. `on_progress`,
    if given, is called with each handle as its check completes (for a
    progress bar on a large batch)."""
    def check_one(h):
        member, member_detail = get_membership_state(token, org, h)
        seat, seat_detail = get_seat_state(token, org, h)
        if on_progress:
            on_progress(h)
        return h, {"member": member, "member_detail": member_detail,
                   "seat": seat, "seat_detail": seat_detail}

    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as ex:
        return dict(ex.map(check_one, usernames))


def _assign(token: str, org: str, usernames: list[str]) -> dict:
    """The actual write. Retries a transient failure (rate limit, 5xx); a
    real rejection is raised immediately since retrying can't fix it, and
    the caller's verify_seats pass afterward is what confirms the outcome
    either way -- this call succeeding is not itself treated as proof."""
    try:
        r = request_with_retry(
            "POST", f"{GH_API}/orgs/{org}/copilot/billing/selected_users",
            headers=auth_headers(token),
            json={"selected_usernames": usernames},
            timeout=30,
        )
    except httpx.RequestError as exc:
        raise RuntimeError(f"could not reach GitHub: {exc}")
    if r.status_code not in (200, 201):
        raise RuntimeError(f"GitHub {r.status_code}: {error_detail(r)}")
    try:
        return r.json()
    except Exception:  # noqa: BLE001
        return {}


def verify_seats(token: str, org: str, usernames: list[str], attempts: int = 3, delay: float = 3.0,
                  on_progress=None) -> dict:
    """Post-assignment: confirms which of these handles actually have a seat
    right now, retrying the unconfirmed ones a couple of times since seat
    activation isn't always instant. Returns {handle: (state, detail)}.
    `on_progress`, if given, is called with each handle as its check
    completes (including repeats across retry rounds)."""
    results: dict[str, tuple[str, str]] = {}
    pending = list(usernames)
    for attempt in range(max(1, attempts)):
        with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as ex:
            for h, res in ex.map(lambda x: (x, get_seat_state(token, org, x)), pending):
                results[h] = res
                if on_progress:
                    on_progress(h)
        pending = [h for h in pending if results[h][0] != SEAT_YES]
        if not pending or attempt == max(1, attempts) - 1:
            break
        time.sleep(delay)
    return results


def start_bulk_assign(username: str, raw_handles: list[str], org: str | None = None) -> str:
    """Validates input and eligibility synchronously (fast), then hands the
    preflight/assign/verify work to a background job and returns its id.
    Raises ValueError for bad input or a missing personal PAT.

    `org` defaults to the configured GITHUB_ORG; pass a different org the
    caller's PAT has access to in order to assign seats there instead."""
    auth = github_auth.resolve_github_auth(username)
    if auth["source"] != "user":
        raise ValueError(
            "No usable GitHub PAT on file for you. Save one with Copilot billing "
            "permission (classic PAT scope manage_billing:copilot, or org admin) "
            "under Profile -> GitHub PAT, then try again."
        )
    token = auth["token"]
    org = (org or get_settings().GITHUB_ORG).strip()

    handles, rejected = validate_and_dedupe(raw_handles)
    if not handles:
        detail = "; ".join(f"{v!r}: {r}" for v, r in rejected) or "no handles given"
        raise ValueError(f"No valid handles to assign ({detail})")

    # Progress has two per-handle phases (preflight check, post-write verify)
    # around one near-instant bulk write in between.
    job_id = bulk_job.new_job("copilot_seat_assign", username, total=len(handles) * 2)
    bulk_job.set_extra(
        job_id, assigned_by=auth.get("login"), org=org,
        rejected_input=[{"value": v, "reason": r} for v, r in rejected],
    )
    bulk_job.run_in_background(_assign_worker, job_id, username, auth.get("login"), token, org, handles, raw_handles)
    return job_id


def _assign_worker(
    job_id: str, username: str, login: str | None, token: str, org: str,
    handles: list[str], raw_handles: list[str],
) -> None:
    try:
        policy = get_org_copilot_policy(token, org)
        policy_warning = None
        if policy != "assign_selected":
            policy_display = repr(policy) if policy else "UNKNOWN (could not check)"
            policy_warning = (
                f"{org}'s Copilot seat-management policy is {policy_display}, not "
                f"'assign_selected' -- this may do nothing."
            )
        bulk_job.set_extra(job_id, policy_warning=policy_warning)

        def check_progress(h: str) -> None:
            bulk_job.set_current(job_id, f"checking {h}")
            bulk_job.increment_done(job_id)

        status = check_membership_and_seats(token, org, handles, on_progress=check_progress)
        not_members = [h for h in handles if status[h]["member"] == MEMBER_NONE]
        pending_invite = [h for h in handles if status[h]["member"] == MEMBER_PENDING]
        undetermined = [
            h for h in handles
            if status[h]["member"] == MEMBER_UNKNOWN
            or (status[h]["member"] == MEMBER_ACTIVE and status[h]["seat"] == SEAT_UNKNOWN)
        ]
        already_seated = [
            h for h in handles
            if status[h]["member"] == MEMBER_ACTIVE and status[h]["seat"] == SEAT_YES
        ]
        to_assign = [
            h for h in handles
            if status[h]["member"] == MEMBER_ACTIVE and status[h]["seat"] == SEAT_NO
        ]

        assigned, assign_failed, assign_unverifiable = [], [], []
        assign_write_error = None
        if to_assign:
            bulk_job.set_current(job_id, "Assigning seats via GitHub...")
            try:
                _assign(token, org, to_assign)
            except (RuntimeError, httpx.RequestError) as exc:
                # The write call itself failed or timed out -- GitHub may
                # have applied it anyway before the response was lost, so
                # this is not treated as the final answer: still read back
                # the real seat state below rather than skipping straight
                # to a crash report with no audit trail at all.
                assign_write_error = str(exc)
                logger.warning("Copilot seat assign write for %s failed, verifying anyway: %s", job_id, exc)

            def verify_progress(h: str) -> None:
                bulk_job.set_current(job_id, f"verifying {h}")
                bulk_job.increment_done(job_id)

            verified = verify_seats(token, org, to_assign, on_progress=verify_progress)
            assigned = [h for h in to_assign if verified[h][0] == SEAT_YES]
            assign_failed = [h for h in to_assign if verified[h][0] == SEAT_NO]
            assign_unverifiable = [h for h in to_assign if verified[h][0] == SEAT_UNKNOWN]
            # The handles classified in phase 1 but never in to_assign
            # (already_seated, not_members, pending_invite, undetermined)
            # have no phase-2 verification step of their own -- without this,
            # progress stalls short of 100% by exactly that count whenever
            # to_assign is a strict subset of handles (the `else` branch
            # below only covers the case where it's everyone).
            bulk_job.increment_done(job_id, by=len(handles) - len(to_assign))

            if assign_failed:
                # One more attempt at just the handles confirmed without a
                # seat -- never the ones already assigned or the ones we
                # couldn't even confirm either way, matching the
                # retry-only-what's-confirmed-failed shape the other two
                # bulk actions already use.
                time.sleep(5)  # let any sustained rate limit cool off first
                bulk_job.set_current(job_id, "Retrying failed seat assignments...")
                try:
                    _assign(token, org, assign_failed)
                except (RuntimeError, httpx.RequestError) as exc:
                    assign_write_error = assign_write_error or str(exc)
                    logger.warning("Copilot seat retry-assign for %s failed, verifying anyway: %s", job_id, exc)

                retry_candidates = assign_failed
                retried = verify_seats(token, org, retry_candidates)
                assigned += [h for h in retry_candidates if retried[h][0] == SEAT_YES]
                assign_failed = [h for h in retry_candidates if retried[h][0] == SEAT_NO]
                assign_unverifiable += [h for h in retry_candidates if retried[h][0] == SEAT_UNKNOWN]
        else:
            bulk_job.increment_done(job_id, by=len(handles))  # nothing to verify -- still reach 100%

        audit.log_event(
            "github.copilot_seat_assign",
            username,
            details={
                "org": org, "requested": raw_handles, "assigned": assigned,
                "already_seated": already_seated, "not_members": not_members, "assign_failed": assign_failed,
                "assign_write_error": assign_write_error,
            },
        )
        logger.info(
            "Copilot seat assign by %s (%s): %d assigned, %d already seated, %d not members, %d failed",
            username, login or username, len(assigned), len(already_seated), len(not_members), len(assign_failed),
        )
        bulk_job.set_extra(
            job_id,
            not_members=not_members, pending_invite=pending_invite, undetermined=undetermined,
            already_seated=already_seated, assigned=assigned,
            assign_failed=assign_failed, assign_unverifiable=assign_unverifiable,
        )
        bulk_job.finish(job_id)
        lines = [
            f"*Assigned:* {len(assigned)}",
            f"*Already had a seat:* {len(already_seated)}",
            f"*Not org members:* {len(not_members)}",
            f"*Invite pending:* {len(pending_invite)}",
            f"*Could not be checked:* {len(undetermined)}",
        ]
        if policy_warning:
            lines.append(f"*Policy warning:* {policy_warning}")
        if assign_write_error:
            lines.append(f"*Assignment request itself errored (verified anyway):* {assign_write_error}")
        bulk_report.send_completion_report(
            title=f"GitHub Copilot seat assignment finished — {org}",
            by=login or username,
            lines=lines,
            failures=[(h, "assignment did not take") for h in assign_failed]
            + [(h, "could not verify after assigning") for h in assign_unverifiable]
            + [(h, status[h]["member_detail"] or status[h]["seat_detail"] or "could not be checked")
               for h in undetermined],
        )
    except Exception as exc:  # noqa: BLE001 -- never let the worker thread die silently
        logger.exception("Copilot seat assign job %s failed", job_id)
        bulk_job.finish(job_id, error=str(exc))
        bulk_report.send_crash_report("Copilot seat assignment", username, str(exc))
