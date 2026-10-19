"""CLDSPT GitHub access request pipeline: full accounting plus the live queue.

Two different questions need two different query shapes, and conflating them
would be slow for no benefit:

Full accounting across every status is counts only, so it uses `maxResults=0`
searches that return a total without any issues. Nine of those cover all 2,685
tickets in under a second each; paging the issues would be 27 slow pages for
numbers we would then throw away.

The open queue needs issue-level detail for the per-engineer breakdown, so it
pages properly, but it is only the ~175 tickets that are not Done.

Latest comments are fetched only on drill-in. Across the queue that would be a
request per ticket; scoped to one engineer it is one request for their list.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from app.config import get_settings
from app.services import audit, cldspt_appname
from app.services.jira_service import MAINT_TEAM_POOL, _headers

logger = logging.getLogger(__name__)

CACHE_PATH = Path(__file__).resolve().parents[2] / "data" / "cldspt_tickets.json"

PAGE_SIZE = 100
_SEARCH_TIMEOUT = 180.0

# How a GitHub access request is recognized. These tickets are titled
# "GitHub: ..." by the EUA intake, so a summary match finds them; 125 of the
# team's 137 open tickets and 2,685 all time. Widen this if the intake format
# changes, since anything it misses silently drops out of the accounting.
GITHUB_SUMMARY_MATCH = "github"

# CLDSPT's intake prefixes a summary with the tool the request is for, so a
# ticket carrying another tool's prefix belongs to that tool even when it talks
# about GitHub. Matching the word alone pulled 2,750 tickets of which 654 were
# somebody else's: 354 secret-scanning alerts ("Security Alerting & Notification
# Service: Github detected a secret in ..."), 197 SonarQube tickets such as
# "SonarQube: GitHub PR reporting for HPMS/licensure_ui PR #201 are missing",
# plus Zscaler connectivity and Security Hub reviews. Open went 184 to 144.
#
# Excluding by prefix rather than by requiring the summary to start with
# "GitHub": a third of the real requests do not, including "Account access to
# GitHub", "Unlock GitHub Account" and "MAC - Add User GitHub CMS Enterprise",
# and anchoring on the front would silently drop them.
OTHER_TOOL_PREFIXES = (
    "Security Alerting & Notification Service",
    "SonarQube",
    "Security Hub",
    "Security Posture Management",
    "Security Audit",
    "Zscaler",
    "Snyk.io",
    "TWS",
    "Account Creation - AWS",
    "AWS Console Access",
    "AWS Config",
    "VPC Peering Request",
    "Create Active Directory Service Account",
    "Configure AD Permission / Groups",
    # An AD service account for GitHub is still AD's request, and the AD flow
    # handles it. Only a handful of tickets, but it is the debatable one here.
    "Cloud Active Directory",
    "MAG Operations Support",
)

# Display grouping for the statuses CLDSPT defines. This is presentation only:
# which statuses exist and whether each one counts as open is read from Jira at
# sweep time, so a status added to the workflow cannot fall out of the totals.
STATUS_BUCKETS: dict[str, str] = {
    "Open": "new",
    "Waiting for approval": "pending_approval",
    "Waiting for customer": "waiting_customer",
    "Waiting for Customer Validation": "waiting_customer",
    "On Hold": "on_hold",
    "Follow Up Required By Engineer": "needs_engineer",
    "Scheduled Work": "scheduled",
    "In Progress": "in_progress",
    "In Development Backlog": "backlog",
    "Approved": "approved",
    "Resolved": "resolved",
    "Closed": "closed",
    "Canceled": "canceled",
}

BUCKET_LABELS: dict[str, str] = {
    "new": "New",
    "pending_approval": "Waiting for approval",
    "waiting_customer": "Waiting for customer",
    "on_hold": "On hold",
    "needs_engineer": "Follow up required",
    "scheduled": "Scheduled work",
    "in_progress": "In progress",
    "backlog": "Development backlog",
    "approved": "Approved",
    "resolved": "Resolved",
    "closed": "Closed",
    "canceled": "Canceled",
    "other": "Other",
}

# Ordering hint for the UI only. Whether a ticket is open is decided by Jira's
# own status category, not by membership of this tuple.
OPEN_BUCKETS = (
    "new", "pending_approval", "waiting_customer", "needs_engineer",
    "scheduled", "in_progress", "backlog", "on_hold",
)

# "Primary Approver" on the CLDSPT service request screen. The approval-request
# comments name the same person, but this field is the structured source.
APPROVER_FIELD = "customfield_24904"

BO_FIELD = "customfield_19500"

# Set by the ticket-creation script from a CMDB lookup. Jira cascades the
# approvers and the Business Owner off it, so a blank here is why a ticket has
# nobody to approve it.
APPLICATION_FIELD = "customfield_15250"

# The prose the requester wrote, and the EUA IDs the access is for. Both feed
# the application guess when Application Name is blank.
JUSTIFICATION_FIELD = "customfield_15100"
USERS_FIELD = "customfield_21704"

# NFeed backs the Application Name picker on the portal form. Its search is
# scoped to an issue context, so a real numeric issue id is required.
_NFEED_PATH = "/rest/nfeed/3.0/nFeed/field/input/options"
_NFEED_MAX_CANDIDATES = 4

# Comment authors who can never be the approver: the Jira automation account,
# and ourselves. An engineer chasing an approval writes the word "approval" a
# lot, which is exactly what the classifier below is looking for.
NON_APPROVER_AUTHORS = {"cloud_jira_admin", "mdvf", "mgib", "s3xr", "sbs2", "m20m", "sz4r"}

# Jira's own workflow automation posts these when a ticket enters Waiting for
# Approval, and our own follow-up uses the third. They contain "approve", so
# they are matched first and never counted as an approval.
_APPROVAL_REQUESTED_RE = re.compile(
    r"request your approval|following up for your approval|get approval from your|"
    r"approval from your \*?cms business owner|haven't yet received confirmation",
    re.I,
)

# Someone performing the approval. Anchored on the act: a comment that opens
# with "Approved", or says "I approve", or approves in a named role.
_APPROVAL_GIVEN_RES = [re.compile(p, re.I) for p in (
    r"^\s*(?:\[~[^\]]+\][,\s]*)*(?:h\d\.\s*)?approv(?:e|ed|al)\b",
    r"\b(?:i|we)\s+(?:hereby\s+)?approve(?:d|s)?\b",
    r"\bapprove(?:d)?\s+(?:as|by)\s+(?:the\s+)?(?:cor|gtl|bo|business\s+owner|ado|cot)\b",
    r"\bapproval\s+(?:is\s+)?granted\b",
)]

# Talking about an approval rather than giving one. "the job code has been
# approved" is a different approval entirely (EUA), and "approval is pending"
# is the opposite of one.
_APPROVAL_MENTION_RES = [re.compile(p, re.I) for p in (
    r"job\s*code\s*(?:is\s*|has\s*been\s*)?approved",
    r"once\s+approved",
    r"ha(?:s|ve)\s+approved",
    r"been\s+approved",
    r"get\s+(?:an\s+)?approval",
    r"need(?:s|ed)?\s+approval",
    r"request(?:ing)?\s+(?:your\s+)?approval",
    r"approval\s+(?:is\s+)?pending",
    r"pending\s+approval",
    r"awaiting\s+approval",
)]

# Approval is two stages: the requester's Business Owner signs off first, then
# this approver signs off on top. Asking the second stage before the first has
# approved is the misfire the ticket-creation script avoids, so the page only
# offers it once a Business Owner approval is on the ticket.
SECOND_STAGE_APPROVER: dict[str, str] = {"username": "VHJN", "name": "Hung Van"}

BO_APPROVAL_LABELS: dict[str, str] = {
    "approved": "Fully approved",
    "second_stage_requested": f"{SECOND_STAGE_APPROVER['name']} asked",
    "bo_approved": f"{SECOND_STAGE_APPROVER['name']} approval required",
    "requested": "BO approval requested",
    "required": "BO approval required",
    "not_required": "No BO approval needed",
}

# Request types that never need a Business Owner sign-off. A Copilot seat is
# billed against a license we already hold, so BO and PO approval applies to
# GitHub license requests only.
NO_BO_APPROVAL_CATEGORIES = {"copilot"}


def _name_words(value) -> set[str]:
    if isinstance(value, list) and value:
        value = value[0]
    text = re.sub(r"\(.*?\)", "", str(value or "")).lower()
    return {w for w in re.split(r"[^a-z]+", text) if len(w) > 2}


def bo_approval(issue: dict) -> dict:
    """Whether a Business Owner has approved this request, read from comments.

    CLDSPT does not use Jira's approval feature for these and no approval field
    is ever populated (checked across the whole open queue), so the only record
    is someone commenting that they approve. ``requested`` means the ask is on
    the ticket and we are waiting; ``required`` means nobody has been asked yet
    and is the state the page offers a button for.

    ``approved_is_bo`` is reported but not relied on: in practice a COR or GTL
    signs off rather than the person named in the Business Owner field.

    Copilot seat requests return ``not_required``: BO and PO approval applies
    to GitHub license requests only, so offering the button there would chase
    an approval nobody is waiting on.
    """
    fields = issue.get("fields") or {}
    if category_for(fields.get("summary")) in NO_BO_APPROVAL_CATEGORIES:
        return {
            "state": "not_required",
            "bo_requested_on": None,
            "requested_on": None,
            "approved_by": None,
            "approved_on": None,
            "approved_is_bo": False,
            "second_stage_approver": SECOND_STAGE_APPROVER["name"],
            "second_stage_requested_on": None,
            "second_stage_approved_by": None,
            "second_stage_approved_on": None,
        }
    comments = ((fields.get("comment") or {}).get("comments")) or []
    reporter = ((fields.get("reporter") or {}).get("name") or "").lower()
    bo_words = _name_words(fields.get(BO_FIELD))
    second = SECOND_STAGE_APPROVER["username"].lower()

    bo: dict | None = None
    stage2: dict | None = None
    bo_requested_on: str | None = None
    stage2_requested_on: str | None = None

    for comment in comments:
        author = comment.get("author") or {}
        username = (author.get("name") or "").lower()
        body = re.sub(r"\s+", " ", comment.get("body") or "").strip()

        # A request for an approval, not an approval. Which stage it belongs to
        # is decided by who it addresses: Jira's automation tags the approver
        # by EUA, and our own ask tags the requester.
        if _APPROVAL_REQUESTED_RE.search(body):
            mentions = {m.lower() for m in re.findall(r"\[~([^\]]+)\]", body)}
            if second in mentions:
                stage2_requested_on = comment.get("created")
            else:
                bo_requested_on = comment.get("created")
            continue

        if username == reporter:
            continue
        if any(r.search(body) for r in _APPROVAL_MENTION_RES):
            continue
        if not any(r.search(body) for r in _APPROVAL_GIVEN_RES):
            continue

        display = author.get("displayName") or author.get("name") or ""
        record = {
            "by": display,
            "username": (author.get("name") or "").upper(),
            "on": comment.get("created"),
            "text": body[:200],
        }
        if username == second:
            stage2 = record
        elif username not in NON_APPROVER_AUTHORS:
            record["is_bo"] = bool(bo_words & _name_words(display))
            bo = record

    common = {
        "bo_requested_on": bo_requested_on,
        "requested_on": bo_requested_on,  # kept for the existing BO button
        "approved_by": bo["by"] if bo else None,
        "approved_on": bo["on"] if bo else None,
        "approved_is_bo": bool(bo and bo.get("is_bo")),
        "second_stage_approver": SECOND_STAGE_APPROVER["name"],
        "second_stage_requested_on": stage2_requested_on,
        "second_stage_approved_by": stage2["by"] if stage2 else None,
        "second_stage_approved_on": stage2["on"] if stage2 else None,
    }

    # Fully signed off once the second stage has approved, whatever we could
    # see of the first: a Business Owner sometimes approves over email and only
    # the second-stage sign-off lands on the ticket.
    if stage2:
        return {"state": "approved", **common}
    if bo:
        return {
            "state": "second_stage_requested" if stage2_requested_on else "bo_approved",
            **common,
        }
    return {"state": "requested" if bo_requested_on else "required", **common}


def _single_value(issue: dict, field: str) -> str | None:
    """Read one display string out of a CLDSPT custom field.

    These arrive as a bare string, a one-element list, or a Jira object
    depending on the field, so all three are flattened the same way.
    """
    raw = (issue.get("fields") or {}).get(field)
    if isinstance(raw, list) and raw:
        raw = raw[0]
    if isinstance(raw, dict):
        raw = raw.get("displayName") or raw.get("value") or raw.get("name")
    text = (str(raw).strip() if raw else "")
    return text or None


def business_owner_of(issue: dict) -> str | None:
    return _single_value(issue, BO_FIELD)


def application_name_of(issue: dict) -> str | None:
    return _single_value(issue, APPLICATION_FIELD)

# What kind of request each ticket is, derived from the summary. The rules are
# ordered and first match wins, so the two automated security feeds are matched
# on their exact service prefixes before anything else can claim them.
CATEGORY_RULES: list[tuple[str, str]] = [
    ("security_finding", r"security alerting\s*&?\s*notification service|security posture management|security hub|"
                         r"finding for|detected a secret|security (concerns|review)"),
    ("copilot",          r"co-?pilot"),
    ("repo_migration",   r"migrat(e|ing|ion)"),
    ("repo_creation",    r"\b(new|create|creating|requesting)\b[^.]{0,30}\brepo|repository for|\brepo\b[^.]{0,20}\bunder\b"),
    ("service_account",  r"service account"),
    ("admin_rights",     r"\bneed admin\b|\badmin (access|rights)\b|\bowner access\b|\bmaintain\b"),
    ("integration",      r"integration with|adding .{0,40}\b(tool|app)\b|github app|coderabbit|snowflake|webhook"),
    # Deliberately last and broad: access is the bulk of the queue, so anything
    # access-shaped that the narrower rules did not claim lands here.
    ("user_access",      r"enterprise github access|eua notification|org invite|account access|access to github|"
                         r"github access|user ?id:|request(ing)? access|request access|add user|re-?add user|"
                         r"new access|got deactivated|re-?join|contributors group|connection to your application|"
                         r"\baccess to\b"),
]

CATEGORY_LABELS: dict[str, str] = {
    "security_finding": "Security finding",
    "copilot": "Copilot seat or license",
    "repo_migration": "Repository migration",
    "repo_creation": "New repository",
    "service_account": "Service account",
    "user_access": "User or org access",
    "admin_rights": "Admin rights",
    "integration": "Integration or tooling",
    "uncategorized": "Uncategorized",
}


def bucket_for(status: str) -> str:
    return STATUS_BUCKETS.get(status, "other")


def category_for(summary: str | None) -> str:
    text = (summary or "").lower()
    for name, pattern in CATEGORY_RULES:
        if re.search(pattern, text):
            return name
    return "uncategorized"


def _approvers_of(issue: dict) -> list[dict]:
    """Primary Approver is multi-valued on these tickets."""
    raw = (issue.get("fields") or {}).get(APPROVER_FIELD)
    if not raw:
        return []
    if isinstance(raw, dict):
        raw = [raw]
    out = []
    for a in raw:
        if isinstance(a, dict) and a.get("name"):
            out.append({"username": a["name"].upper(), "name": a.get("displayName") or a["name"]})
    return out


def _team() -> list[dict]:
    return MAINT_TEAM_POOL


def _github_base() -> str:
    """The one JQL every count and listing derives from.

    The exclusion lives here rather than in Python so the per-status and
    per-engineer counts, which are JQL totals, agree with the lists.
    """
    proj = get_settings().CLDSPT_PROJECT
    not_other = " OR ".join(f'summary ~ "\\"{p}:\\""' for p in OTHER_TOOL_PREFIXES)
    return (f'project = {proj} AND summary ~ "{GITHUB_SUMMARY_MATCH}"'
            f' AND NOT ({not_other})')


def _search(jql: str, fields: str, start_at: int = 0, max_results: int = PAGE_SIZE) -> dict:
    s = get_settings()
    resp = httpx.get(
        f"{s.JIRA_URL}/rest/api/2/search",
        headers=_headers(),
        params={"jql": jql, "startAt": start_at, "maxResults": max_results, "fields": fields},
        timeout=_SEARCH_TIMEOUT,
        verify=True,
    )
    resp.raise_for_status()
    return resp.json()


def request_bo_approval(issue_key: str, requested_by: str) -> dict:
    """Post the Business Owner approval-request comment on one ticket.

    Phrased at the requester, not at the Primary Approver, and deliberately
    does not touch Application Name: setting that triggers Jira's own cascade,
    which emails the second-stage approver an approval request before any
    Business Owner has signed off. That misfired on real tickets.

    Refuses when an approval is already recorded, so the button cannot nag
    somebody who has already approved.
    """
    s = get_settings()
    try:
        page = _search(
            f"key = {issue_key}",
            f"summary,status,reporter,comment,{BO_FIELD},{APPLICATION_FIELD}",
            max_results=1,
        )
    except Exception as exc:  # noqa: BLE001 — a key Jira rejects is a 400, not an empty result
        logger.warning("BO approval lookup for %s failed: %s", issue_key, exc)
        return {"posted": False, "key": issue_key, "error": "No such ticket."}
    issues = page.get("issues") or []
    if not issues:
        return {"posted": False, "key": issue_key, "error": "No such ticket."}
    issue = issues[0]

    state = bo_approval(issue)
    if state["state"] == "not_required":
        return {"posted": False, "key": issue_key, "state": state,
                "error": "Copilot seat requests do not need a Business Owner approval."}
    if state["state"] == "approved":
        return {"posted": False, "key": issue_key, "state": state,
                "error": f"Already approved by {state.get('approved_by')}."}

    reporter = (issue.get("fields") or {}).get("reporter") or {}
    mention = (reporter.get("name") or "").upper()
    if not mention:
        return {"posted": False, "key": issue_key,
                "error": "The ticket has no reporter to address the request to."}

    body = (
        f"Hi [~{mention}] Could you please get approval from your "
        f"*CMS Business Owner* so we can proceed with your GitHub access. Thanks!"
    )
    resp = httpx.post(
        f"{s.JIRA_URL}/rest/servicedeskapi/request/{issue_key}/comment",
        headers={**_headers(), "Content-Type": "application/json"},
        json={"body": body, "public": True},
        timeout=60.0,
        verify=True,
    )
    if resp.status_code not in (200, 201):
        logger.warning("BO approval request on %s failed: %s %s",
                       issue_key, resp.status_code, resp.text[:200])
        return {"posted": False, "key": issue_key,
                "error": f"Jira returned {resp.status_code}."}

    logger.info("BO approval requested on %s by %s", issue_key, requested_by)
    return {"posted": True, "key": issue_key, "mentioned": mention,
            "business_owner": business_owner_of(issue), "body": body}


def notify_ticket_non_member_admins(issue_key: str, github_handles: list[str], repo_name: str) -> dict:
    """Comments on `issue_key` that `github_handles` need to be added as
    admin on `repo_name` once they're confirmed org members -- used when
    repo creation skips granting someone admin because they aren't a
    confirmed GitHub org member yet (adding a non-member directly would
    have GitHub send them its own invite, bypassing the org's real
    access-request approval process).

    Mentions the ticket's reporter, since a GitHub handle has no reliable
    mapping to a Jira account to mention directly -- a real person seeing
    this is the point, not a literal @-mention of the GitHub user."""
    s = get_settings()
    try:
        page = _search(f"key = {issue_key}", "reporter", max_results=1)
    except Exception as exc:  # noqa: BLE001 — a key Jira rejects is a 400, not an empty result
        logger.warning("Non-member notice lookup for %s failed: %s", issue_key, exc)
        return {"posted": False, "key": issue_key, "error": "No such ticket."}
    issues = page.get("issues") or []
    if not issues:
        return {"posted": False, "key": issue_key, "error": "No such ticket."}

    reporter = (issues[0].get("fields") or {}).get("reporter") or {}
    mention = (reporter.get("name") or "").upper()
    handles_text = ", ".join(github_handles)
    greeting = f"Hi [~{mention}] — " if mention else ""
    body = (
        f"{greeting}repo `{repo_name}` was created with baseline access, but GitHub handle(s) "
        f"{handles_text} could not be added as admin yet -- not confirmed as a member of the "
        f"GitHub org. Once added through the access-request process, add them as an admin "
        f"collaborator on `{repo_name}`."
    )
    resp = httpx.post(
        f"{s.JIRA_URL}/rest/servicedeskapi/request/{issue_key}/comment",
        headers={**_headers(), "Content-Type": "application/json"},
        json={"body": body, "public": True},
        timeout=60.0,
        verify=True,
    )
    if resp.status_code not in (200, 201):
        logger.warning("Non-member notice comment on %s failed: %s %s",
                       issue_key, resp.status_code, resp.text[:200])
        return {"posted": False, "key": issue_key, "error": f"Jira returned {resp.status_code}."}

    logger.info("Non-member notice posted on %s for %s", issue_key, handles_text)
    return {"posted": True, "key": issue_key, "mentioned": mention or None}


SLACK_APPROVAL_CHANNEL = "github-access-approvals-internal"
SLACK_APPROVAL_CHANNEL_ID = "C0C7GB5HDGS"


def _greeting(now: datetime | None = None) -> str:
    hour = (now or datetime.now()).hour
    if hour < 12:
        return "Good morning"
    if hour < 17:
        return "Good afternoon"
    return "Good evening"


def recent_nudges(days: int = 7) -> dict[str, dict]:
    """Who has already been nudged lately, keyed by engineer.

    Read from the audit log rather than carried in the sweep cache: a nudge
    happens between sweeps, so a cached answer would be wrong for hours and the
    button would invite a second message to the approver. Cheap enough to do on
    each queue read, since it only scans a few days of JSONL.
    """
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    try:
        events = audit.get_events(
            date_from=since, event_type="jira.slack_approval_nudge", page_size=500,
        ).get("events", [])
    except Exception as exc:  # noqa: BLE001 — the board must not fail over this
        logger.warning("Could not read nudge history: %s", exc)
        return {}

    out: dict[str, dict] = {}
    for e in events:  # get_events returns newest first, so the first win stands
        d = e.get("details") or {}
        who = (d.get("engineer") or "").upper()
        if not who or who in out or not d.get("posted"):
            continue
        out[who] = {
            "at": e.get("timestamp"),
            "by": e.get("username"),
            "tickets": d.get("tickets") or [],
        }
    return out


def slack_approval_nudge(username: str, requested_by_name: str = "") -> dict:
    """Build the Slack message asking the second-stage approver to sign off.

    Only ever covers one engineer's own tickets, and only those where the
    Business Owner has already approved, so the ask is never premature. The
    text is built here rather than in the browser so the wording is the same
    whether the dashboard posts it or somebody pastes it.

    Posts to Slack when a bot token is configured. Without one the message is
    still returned, for the page to put on the clipboard and open the channel.
    """
    detail = tickets_for(username)
    awaiting = [
        t for t in detail.get("tickets", [])
        if (t.get("bo_approval") or {}).get("state") in ("bo_approved", "second_stage_requested")
    ]
    approver = SECOND_STAGE_APPROVER["name"]
    if not awaiting:
        return {
            "posted": False,
            "channel": SLACK_APPROVAL_CHANNEL,
            "tickets": [],
            "message": None,
            "error": (f"None of {detail.get('name') or username}'s tickets are waiting on "
                      f"{approver}. He signs off after the Business Owner, so a ticket only "
                      "reaches him once that approval is on it."),
        }

    engineer = detail.get("name") or username
    first = engineer.split(",")[1].strip().split(" ")[0] if "," in engineer else engineer.split(" ")[0]

    def _build(api_links: bool) -> str:
        """The nudge text.

        Slack's ``<url|label>`` syntax is only parsed when a message arrives
        through the API. Pasted into the composer it is not markup, so Slack
        autolinks the whole token and the label ends up inside the href as
        %7CKEY, which is a dead link. The clipboard copy therefore carries bare
        URLs, which Slack autolinks correctly on its own.
        """
        out = [
            f"{_greeting()} {approver.split(' ')[0]}, "
            f"{len(awaiting)} GitHub access request{'s' if len(awaiting) != 1 else ''} "
            f"assigned to {first} {'are' if len(awaiting) != 1 else 'is'} waiting on your approval. "
            f"The Business Owner has signed off on {'each' if len(awaiting) != 1 else 'it'} already.",
            "",
        ]
        for t in awaiting:
            bo = (t.get("bo_approval") or {}).get("approved_by") or "the Business Owner"
            link = f"<{t['url']}|{t['key']}>" if api_links else f"{t['key']} {t['url']}"
            out.append(f"• {link} — {t.get('summary') or ''} (approved by {bo})")
        out += ["", "Thanks!"]
        return "\n".join(out)

    posted = False
    try:
        from app.services import slack
        posted = slack.send_message(SLACK_APPROVAL_CHANNEL, _build(api_links=True))
    except Exception as exc:  # noqa: BLE001 — falling back to a paste is fine
        logger.warning("Slack approval nudge post failed: %s", exc)

    # What the caller gets back is what it will do with it: the posted message
    # is already sent, so the text returned is the one for the clipboard.
    message = _build(api_links=posted)

    if posted:
        logger.info("Slack approval nudge for %s posted by %s", username, requested_by_name)

    return {
        "posted": posted,
        "channel": SLACK_APPROVAL_CHANNEL,
        "channel_url": f"https://cmsgov.slack.com/archives/{SLACK_APPROVAL_CHANNEL_ID}",
        "approver": approver,
        "engineer": engineer,
        "tickets": [t["key"] for t in awaiting],
        "message": message,
        # False means the dashboard has no Slack bot token, so the page should
        # put the text on the clipboard and open the channel instead.
        "can_post": posted,
        "error": None,
    }


def request_second_stage_approval(issue_key: str, requested_by: str) -> dict:
    """Ask the second-stage approver to sign off, once a Business Owner has.

    Refuses until a Business Owner approval is on the ticket. That order is the
    whole point: the second-stage approver signs off on top of the Business
    Owner, and asking early is what pinged him on tickets nobody had approved.
    """
    s = get_settings()
    try:
        page = _search(
            f"key = {issue_key}",
            f"summary,status,reporter,comment,{BO_FIELD},{APPLICATION_FIELD}",
            max_results=1,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Second-stage lookup for %s failed: %s", issue_key, exc)
        return {"posted": False, "key": issue_key, "error": "No such ticket."}
    issues = page.get("issues") or []
    if not issues:
        return {"posted": False, "key": issue_key, "error": "No such ticket."}
    issue = issues[0]

    state = bo_approval(issue)
    approver = SECOND_STAGE_APPROVER
    if state["state"] == "not_required":
        return {"posted": False, "key": issue_key, "state": state,
                "error": "Copilot seat requests do not go through this approval."}
    if state["state"] == "approved":
        return {"posted": False, "key": issue_key, "state": state,
                "error": f"{approver['name']} has already approved this request."}
    if state["state"] in ("required", "requested"):
        return {"posted": False, "key": issue_key, "state": state,
                "error": ("No Business Owner approval is on the ticket yet. "
                          f"{approver['name']} signs off after the Business Owner, "
                          "so asking now would be premature.")}

    bo_line = f"{state['approved_by']}"
    if state.get("approved_on"):
        bo_line += f" on {str(state['approved_on'])[:10]}"
    body = (
        f"Hi [~{approver['username']}] The Business Owner approval for this request is "
        f"in: {bo_line}. Could you please provide your approval so we can proceed "
        f"with the GitHub access. Thanks!"
    )
    resp = httpx.post(
        f"{s.JIRA_URL}/rest/servicedeskapi/request/{issue_key}/comment",
        headers={**_headers(), "Content-Type": "application/json"},
        json={"body": body, "public": True},
        timeout=60.0,
        verify=True,
    )
    if resp.status_code not in (200, 201):
        logger.warning("Second-stage approval request on %s failed: %s %s",
                       issue_key, resp.status_code, resp.text[:200])
        return {"posted": False, "key": issue_key,
                "error": f"Jira returned {resp.status_code}."}

    logger.info("Second-stage approval requested on %s by %s", issue_key, requested_by)
    return {"posted": True, "key": issue_key, "mentioned": approver["username"],
            "approver": approver["name"], "body": body}


def _nfeed_options(issue_id: str, user_input: str) -> list[str]:
    """Option ids the Application Name picker offers for a search string."""
    s = get_settings()
    try:
        resp = httpx.post(
            f"{s.JIRA_URL}{_NFEED_PATH}",
            headers={**_headers(), "Content-Type": "application/json"},
            json={
                "customFieldId": APPLICATION_FIELD,
                "userInput": user_input,
                "view": "EDIT",
                "fieldContext": {"issueKeyOrId": str(issue_id)},
                "formData": {APPLICATION_FIELD: [""]},
                "startIndex": 0,
            },
            timeout=40.0,
            verify=True,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Application catalog search failed for %r: %s", user_input, exc)
        return []
    if resp.status_code != 200:
        return []
    return [o["id"] for o in (resp.json().get("options") or []) if o.get("id")]


def _catalog_lookup(issue_id: str):
    """A lookup that only answers when the catalog is unambiguous.

    One option is a confident match. Several means the search was too loose,
    and the tie is only broken when exactly one option is an exact match for
    one of the spellings tried, which is a stronger signal than prefix
    overlap. Anything else returns nothing rather than guessing.
    """
    def lookup(candidate: str) -> str | None:
        variants = cldspt_appname.variants_of(candidate)
        options: list[str] = []
        for variant in variants:
            for opt in _nfeed_options(issue_id, variant):
                if opt not in options:
                    options.append(opt)
        if len(options) == 1:
            return options[0]
        wanted = {v.lower() for v in variants}
        exact = [o for o in options if o.lower() in wanted]
        return exact[0] if len(exact) == 1 else None

    return lookup


def _users_of(issue: dict) -> list[str]:
    """EUA IDs the access is being requested for, falling back to the reporter."""
    raw = (issue.get("fields") or {}).get(USERS_FIELD) or []
    out = [u["name"].upper() for u in raw if isinstance(u, dict) and u.get("name")]
    if out:
        return out
    reporter = ((issue.get("fields") or {}).get("reporter") or {}).get("name")
    return [reporter.upper()] if reporter else []


def infer_applications(issues: list[dict]) -> dict[str, dict]:
    """Guess the application for every issue whose Application Name is blank.

    Runs in the daily sweep rather than on page load: the AD lookup is one
    batched bind for all of them at once, and confirming candidates against
    the catalog costs a request per spelling tried.
    """
    blank = [i for i in issues if not application_name_of(i)]
    if not blank:
        return {}

    euas: set[str] = set()
    for issue in blank:
        euas.update(_users_of(issue))

    groups: dict[str, list[str]] = {}
    if euas:
        try:
            from app.services import ldap_accounts
            groups = ldap_accounts.get_groups(sorted(euas))
        except Exception as exc:  # noqa: BLE001 — AD is a fallback, never fatal
            logger.warning("AD group lookup for application inference failed: %s", exc)

    out: dict[str, dict] = {}
    for issue in blank:
        fields = issue.get("fields") or {}
        ad_groups: list[str] = []
        for eua in _users_of(issue):
            ad_groups.extend(groups.get(eua.lower(), []))
        issue_id = issue.get("id")
        result = cldspt_appname.infer(
            fields.get(JUSTIFICATION_FIELD),
            ad_groups,
            catalog_lookup=_catalog_lookup(issue_id) if issue_id else None,
        )
        result["users"] = _users_of(issue)
        out[issue.get("key")] = result
    return out


def _count(jql: str) -> int:
    """Total matching issues without fetching any of them."""
    try:
        return int(_search(jql, "key", max_results=0).get("total") or 0)
    except Exception as exc:
        logger.warning("CLDSPT count failed for %s: %s", jql, exc)
        return -1


def _assignee_of(issue: dict) -> str:
    a = (issue.get("fields") or {}).get("assignee") or {}
    return (a.get("name") or "").upper()


def project_statuses() -> dict[str, str]:
    """{status name: Jira status category} for the project, read live.

    Asking Jira which statuses exist is what keeps the accounting honest. A
    hardcoded list silently drops any status added to the workflow later, which
    is exactly what happened when a ticket moved to "Scheduled Work".
    """
    s = get_settings()
    resp = httpx.get(
        f"{s.JIRA_URL}/rest/api/2/project/{s.CLDSPT_PROJECT}/statuses",
        headers=_headers(),
        timeout=60.0,
        verify=True,
    )
    resp.raise_for_status()
    out: dict[str, str] = {}
    for issue_type in resp.json():
        for st in issue_type.get("statuses") or []:
            name = st.get("name")
            if name:
                out[name] = ((st.get("statusCategory") or {}).get("name") or "").strip()
    return out


def collect() -> dict:
    """Full status accounting, plus the open queue broken down per engineer."""
    base = _github_base()

    # Every status the project defines, counts only. Read from Jira rather than
    # from STATUS_BUCKETS so a new workflow status still lands in the totals.
    try:
        categories = project_statuses()
    except Exception as exc:
        logger.warning("Could not read CLDSPT statuses, falling back to the known set: %s", exc)
        categories = {name: "" for name in STATUS_BUCKETS}

    by_status: dict[str, int] = {}
    for status in categories:
        esc = status.replace('"', '\\"')
        n = _count(f'{base} AND status = "{esc}"')
        if n > 0:
            by_status[status] = n

    # What actually got finished, for the daily read. Canceled requests also land
    # in statusCategory Done, so they are counted apart instead of inflating the
    # completed figure: 3 of yesterday's 24 were cancellations, not deliveries.
    done_base = f"{base} AND statusCategory = Done AND status != Canceled"
    throughput = {
        "since_yesterday": _count(f"{done_base} AND resolutiondate >= startOfDay(-1d)"),
        "today": _count(f"{done_base} AND resolutiondate >= startOfDay()"),
        "canceled_since_yesterday": _count(
            f"{base} AND status = Canceled AND resolutiondate >= startOfDay(-1d)"),
    }

    by_bucket: dict[str, int] = {}
    for status, n in by_status.items():
        b = bucket_for(status)
        by_bucket[b] = by_bucket.get(b, 0) + n

    all_time = _count(base)
    accounted = sum(by_status.values())

    # Open versus done comes from Jira's status category, not our own grouping.
    open_total = sum(n for s, n in by_status.items() if categories.get(s) != "Done")
    done_total = sum(n for s, n in by_status.items() if categories.get(s) == "Done")

    # Any status we count but do not have a display bucket for. Surfacing this
    # separately from `unaccounted` distinguishes "we missed a status entirely"
    # from "we counted it but have no label for it".
    unmapped = sorted(s for s in by_status if s not in STATUS_BUCKETS)

    # Per-engineer all-time volume, counts only.
    per_engineer_all: dict[str, int] = {}
    for m in _team():
        per_engineer_all[m["username"]] = _count(f'{base} AND assignee = {m["username"]}')

    # Completed since the start of yesterday, per engineer. Counted here rather
    # than from the open queue because finished work is not in it.
    done_recent = (f"{base} AND statusCategory = Done AND status != Canceled "
                   f"AND resolutiondate >= startOfDay(-1d)")
    per_engineer_done: dict[str, int] = {}
    for m in _team():
        per_engineer_done[m["username"]] = _count(f'{done_recent} AND assignee = {m["username"]}')

    # The open queue, with issues, for the per-engineer status breakdown.
    rows: dict[str, dict] = {
        m["username"]: {
            "username": m["username"],
            "name": m["name"],
            "open": 0,
            "all_time": per_engineer_all.get(m["username"], 0),
            "completed_since_yesterday": per_engineer_done.get(m["username"], 0),
            "buckets": {},
            "categories": {},
            # "<category>|<bucket>" counts, so the UI can show an exact number
            # when a request type and a status are filtered together. Marginal
            # counts alone cannot answer that.
            "cross": {},
            "bo_approval": {},
        }
        for m in _team()
    }
    open_jql = f"{base} AND statusCategory != Done ORDER BY updated DESC"
    unassigned_open = 0
    by_category: dict[str, int] = {}
    # Open-only bucket totals. by_bucket is all time, which includes closed
    # work the engineer table does not carry, so the filterable chips need this.
    by_bucket_open: dict[str, int] = {}
    bo_totals: dict[str, int] = {}
    open_issues: list[dict] = []
    app_set = 0
    start, fetched, reported = 0, 0, None
    while True:
        page = _search(
            open_jql,
            f"status,assignee,summary,reporter,comment,{APPROVER_FIELD},{BO_FIELD},"
            f"{APPLICATION_FIELD},{JUSTIFICATION_FIELD},{USERS_FIELD}",
            start_at=start,
        )
        if reported is None:
            reported = page.get("total")
        issues = page.get("issues") or []
        if not issues:
            break
        open_issues.extend(issues)
        for issue in issues:
            f = issue.get("fields") or {}
            status = (f.get("status") or {}).get("name") or "Unknown"
            b = bucket_for(status)
            if application_name_of(issue):
                app_set += 1
            cat = category_for(f.get("summary"))
            by_category[cat] = by_category.get(cat, 0) + 1
            by_bucket_open[b] = by_bucket_open.get(b, 0) + 1

            bo_state = bo_approval(issue)["state"]
            bo_totals[bo_state] = bo_totals.get(bo_state, 0) + 1

            row = rows.get(_assignee_of(issue))
            if row is None:
                unassigned_open += 1
                continue
            row["open"] += 1
            row["buckets"][b] = row["buckets"].get(b, 0) + 1
            row["categories"][cat] = row["categories"].get(cat, 0) + 1
            key = f"{cat}|{b}"
            row["cross"][key] = row["cross"].get(key, 0) + 1
            row["bo_approval"][bo_state] = row["bo_approval"].get(bo_state, 0) + 1
        fetched += len(issues)
        start += len(issues)
        if reported is not None and fetched >= reported:
            break

    # Guessing the application is the expensive part, so it happens here in the
    # sweep and the page reads the answer out of the cache.
    try:
        inferred = infer_applications(open_issues)
    except Exception as exc:  # noqa: BLE001 — a failed guess must not fail the sweep
        logger.error("Application inference failed: %s", exc)
        inferred = {}

    engineers = sorted(rows.values(), key=lambda r: (r["open"], r["all_time"]), reverse=True)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "match": GITHUB_SUMMARY_MATCH,
        "all_time_total": all_time,
        "accounted_total": accounted,
        # A gap means a status outside STATUS_BUCKETS exists and is being
        # missed, so it is surfaced rather than left to look like a rounding slip.
        "unaccounted": (all_time - accounted) if all_time >= 0 else None,
        "open_total": open_total,
        "done_total": done_total,
        "open_fetched": fetched,
        "open_reported": reported,
        "unassigned_open": unassigned_open,
        "by_status": by_status,
        "by_bucket": by_bucket,
        "by_bucket_open": by_bucket_open,
        "by_category": by_category,
        "status_categories": categories,
        "unmapped_statuses": unmapped,
        "bucket_labels": BUCKET_LABELS,
        "category_labels": CATEGORY_LABELS,
        "open_buckets": list(OPEN_BUCKETS),
        "application_set": app_set,
        "application_blank": len(open_issues) - app_set,
        "application_inferred": inferred,
        "application_inferred_confirmed": sum(1 for v in inferred.values() if v.get("confirmed")),
        "throughput": throughput,
        "bo_approval_totals": bo_totals,
        "bo_approval_labels": BO_APPROVAL_LABELS,
        "engineers": engineers,
        "error": None,
    }


def _write_cache(payload: dict) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = CACHE_PATH.with_suffix(CACHE_PATH.suffix + f".tmp.{os.getpid()}")
    tmp.write_text(json.dumps(payload))
    os.replace(tmp, CACHE_PATH)


def read_cache() -> dict | None:
    try:
        return json.loads(CACHE_PATH.read_text())
    except FileNotFoundError:
        return None
    except Exception as exc:
        logger.warning("CLDSPT ticket cache unreadable: %s", exc)
        return None


_SWEEP_STATE = {"running": False, "started_at": None, "last_error": None}
_sweep_lock = threading.Lock()


def sweep_status() -> dict:
    state = dict(_SWEEP_STATE)
    cached = read_cache() or {}
    state["generated_at"] = cached.get("generated_at")
    state["all_time_total"] = cached.get("all_time_total")
    state["open_total"] = cached.get("open_total")
    return state


def _run_sweep() -> None:
    try:
        _write_cache(collect())
        with _sweep_lock:
            _SWEEP_STATE["last_error"] = None
    except Exception as exc:
        logger.exception("CLDSPT ticket sweep failed")
        with _sweep_lock:
            _SWEEP_STATE["last_error"] = str(exc)
    finally:
        with _sweep_lock:
            _SWEEP_STATE["running"] = False


def start_background_sweep() -> dict:
    with _sweep_lock:
        if _SWEEP_STATE["running"]:
            return {"started": False, "reason": "already running"}
        _SWEEP_STATE["running"] = True
        _SWEEP_STATE["started_at"] = datetime.now(timezone.utc).isoformat()
    threading.Thread(target=_run_sweep, name="cldspt-ticket-sweep", daemon=True).start()
    return {"started": True}


def _latest_comment(issue: dict) -> dict | None:
    comments = (((issue.get("fields") or {}).get("comment")) or {}).get("comments") or []
    if not comments:
        return None
    last = comments[-1]
    body = (last.get("body") or "").strip()
    # Truncated rather than summarized: real summarization belongs with the
    # Bedrock work, and a wrong summary on a support ticket is worse than none.
    return {
        "author": (last.get("author") or {}).get("displayName"),
        "created": last.get("created"),
        "body": body[:600],
        "truncated": len(body) > 600,
        "count": len(comments),
    }


def tickets_for(username: str, include_done: bool = False, limit: int = 300) -> dict:
    """One engineer's GitHub requests with status and latest comment.

    Open only by default. include_done walks the whole history, which for the
    busiest engineer is a few hundred tickets, so it is capped.
    """
    username = (username or "").upper()
    known = {m["username"]: m for m in _team()}
    if username not in known:
        return {"username": username, "error": "Unknown engineer", "tickets": []}

    jql = f"{_github_base()} AND assignee = {username}"
    if not include_done:
        jql += " AND statusCategory != Done"
    jql += " ORDER BY updated DESC"

    cached = read_cache() or {}
    inferred_apps: dict[str, dict] = cached.get("application_inferred") or {}

    tickets: list[dict] = []
    start, total = 0, None
    while True:
        page = _search(
            jql,
            f"summary,status,updated,created,reporter,comment,{APPROVER_FIELD},{BO_FIELD},{APPLICATION_FIELD}",
            start_at=start,
        )
        if total is None:
            total = page.get("total")
        issues = page.get("issues") or []
        if not issues:
            break
        for issue in issues:
            f = issue.get("fields") or {}
            status = (f.get("status") or {}).get("name") or "Unknown"
            bucket = bucket_for(status)
            approvers = _approvers_of(issue)
            tickets.append({
                "key": issue.get("key"),
                "summary": f.get("summary"),
                "status": status,
                "bucket": bucket,
                "category": category_for(f.get("summary")),
                "updated": f.get("updated"),
                "created": f.get("created"),
                "url": f"{get_settings().JIRA_URL}/browse/{issue.get('key')}",
                "approvers": approvers,
                "application_name": application_name_of(issue),
                "application_inferred": inferred_apps.get(issue.get("key")),
                "business_owner": business_owner_of(issue),
                "bo_approval": bo_approval(issue),
                "latest_comment": _latest_comment(issue),
            })
        start += len(issues)
        if len(tickets) >= limit or (total is not None and start >= total):
            break

    return {
        "username": username,
        "name": known[username]["name"],
        "include_done": include_done,
        "total": total,
        "returned": len(tickets),
        "tickets": tickets,
        "error": None,
    }


# ─── Self-service queue (assign + close from the dashboard) ───────────────────
#
# A different question from everything above: not "every GitHub-related
# ticket, however it arrived" (the BO-approval accounting's job, tuned around
# a text-match heuristic because that is what reliably covers 2,000+ tickets
# going back years), but "requests a developer submitted through the current
# intake, that still need a team member to pick up and close out". That is a
# structural question with a structural answer, and a spot check shows the
# two do not overlap cleanly enough to share a filter: the same project on
# the same day returned 1,194 all-time tickets through the structured filter
# below versus 2,157 through the text heuristic. Kept separate rather than
# reconciled, so neither accounting silently shifts under the other.
#
# New tickets land on this account until a team member assigns one to
# themselves, which is the whole reason this queue exists. The real value
# lives in settings.CLDSPT_DEFAULT_QUEUE_ASSIGNEE -- this is who it is
# today, not a guarantee of who it'll always be.

SELF_SERVICE_STATUSES_EXCLUDED = ("Closed", "Resolved", "Canceled")


def _self_service_jql() -> str:
    proj = get_settings().CLDSPT_PROJECT
    excluded = ", ".join(SELF_SERVICE_STATUSES_EXCLUDED)
    return (
        f"project = {proj} AND status not in ({excluded})"
        f' AND ((Teams = "CMS-Cloud-DevOps" AND "Customer Request Type" = "CMS Cloud: Access Request")'
        f' OR (issuetype = "Service Request" AND "Service Name" = GitHub))'
        f" ORDER BY created ASC"
    )


def self_service_queue(safety_limit: int = 5000) -> dict:
    """Open developer-submitted GitHub requests, oldest first, every matching
    page -- a queue meant to be acted on has to cover every open request, not
    just however many fit in one page, or the ones omitted (often the oldest,
    since this already sorts oldest-first and a page cap would cut off
    whichever came later) would need-pickup without showing up anywhere.

    `safety_limit` is a true ceiling against a runaway JQL match, not a
    realistic cap for this queue's actual size -- it should never be hit in
    practice.

    Live, not cached: this queue exists to be acted on, so a stale assignee
    would be actively misleading rather than just late.
    """
    default_assignee = get_settings().CLDSPT_DEFAULT_QUEUE_ASSIGNEE.upper()
    jql = _self_service_jql()
    tickets: list[dict] = []
    start, total = 0, None
    while True:
        page = _search(jql, "summary,status,issuetype,assignee,reporter,created,updated", start_at=start)
        if total is None:
            total = page.get("total")
        issues = page.get("issues") or []
        if not issues:
            break
        for issue in issues:
            f = issue.get("fields") or {}
            assignee = f.get("assignee") or {}
            reporter = f.get("reporter") or {}
            tickets.append({
                "key": issue.get("key"),
                "summary": f.get("summary"),
                "status": (f.get("status") or {}).get("name"),
                "issue_type": (f.get("issuetype") or {}).get("name"),
                "assignee": assignee.get("name"),
                "assignee_name": assignee.get("displayName"),
                "needs_pickup": (assignee.get("name") or "").upper() == default_assignee,
                "reporter": reporter.get("name"),
                "reporter_name": reporter.get("displayName"),
                "created": f.get("created"),
                "updated": f.get("updated"),
                "url": f"{get_settings().JIRA_URL}/browse/{issue.get('key')}",
            })
        start += len(issues)
        if len(tickets) >= safety_limit or (total is not None and start >= total):
            break

    return {
        "total": total,
        "returned": len(tickets),
        "needs_pickup": sum(1 for t in tickets if t["needs_pickup"]),
        "tickets": tickets,
        "error": None,
    }


def issue_transitions(issue_key: str) -> dict:
    """The workflow transitions actually available for one ticket right now.

    Jira's valid "next status" set depends on the ticket's current status, so
    this is fetched live rather than assumed, and the caller is expected to
    offer the user a choice drawn from it rather than a hardcoded status id.
    """
    s = get_settings()
    try:
        resp = httpx.get(
            f"{s.JIRA_URL}/rest/api/2/issue/{issue_key}/transitions",
            headers=_headers(),
            timeout=30.0,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Transition lookup for %s failed: %s", issue_key, exc)
        return {"key": issue_key, "transitions": [], "error": str(exc)[:200]}
    if resp.status_code != 200:
        return {"key": issue_key, "transitions": [], "error": f"Jira returned {resp.status_code}."}
    transitions = [
        {"id": t["id"], "name": t["name"], "to_status": (t.get("to") or {}).get("name")}
        for t in (resp.json().get("transitions") or [])
    ]
    return {"key": issue_key, "transitions": transitions, "error": None}


def assign_issue(issue_key: str, username: str) -> dict:
    """Assign a ticket to a team member's own Jira account."""
    s = get_settings()
    username = (username or "").strip()
    if not username:
        return {"assigned": False, "key": issue_key, "error": "No username given."}
    try:
        resp = httpx.put(
            f"{s.JIRA_URL}/rest/api/2/issue/{issue_key}/assignee",
            headers=_headers(),
            json={"name": username},
            timeout=30.0,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Assign %s to %s failed: %s", issue_key, username, exc)
        return {"assigned": False, "key": issue_key, "error": str(exc)[:200]}
    if resp.status_code not in (200, 204):
        logger.warning("Assign %s to %s failed: %s %s", issue_key, username, resp.status_code, resp.text[:200])
        return {"assigned": False, "key": issue_key, "error": f"Jira returned {resp.status_code}."}
    return {"assigned": True, "key": issue_key, "assignee": username}


def transition_issue(issue_key: str, transition_id: str, comment: str | None = None) -> dict:
    """Move a ticket to one of its currently valid workflow statuses.

    Expects a transition id drawn from issue_transitions() for this same
    ticket: Jira 400s on one that is not valid from the current status, which
    surfaces here as an error rather than a guess at a fix.
    """
    s = get_settings()
    body: dict = {"transition": {"id": transition_id}}
    if comment:
        body["update"] = {"comment": [{"add": {"body": comment}}]}
    try:
        resp = httpx.post(
            f"{s.JIRA_URL}/rest/api/2/issue/{issue_key}/transitions",
            headers=_headers(),
            json=body,
            timeout=30.0,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Transition %s to %s failed: %s", issue_key, transition_id, exc)
        return {"transitioned": False, "key": issue_key, "error": str(exc)[:200]}
    if resp.status_code not in (200, 204):
        logger.warning("Transition %s to %s failed: %s %s",
                       issue_key, transition_id, resp.status_code, resp.text[:200])
        return {"transitioned": False, "key": issue_key, "error": f"Jira returned {resp.status_code}."}
    return {"transitioned": True, "key": issue_key}
