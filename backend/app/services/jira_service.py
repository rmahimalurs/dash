import re
import calendar
import logging
from datetime import date, datetime

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

# ─── Maintenance prep constants ───────────────────────────────────────────────

MAINT_TEAM_POOL = [
    {"index": 0, "username": "RWRW", "name": "Rahimi, Masood"},
    {"index": 1, "username": "MDVF", "name": "Mangalvedhekar, Shantanu"},
    {"index": 2, "username": "MGIB", "name": "Mahimalur, Ramesh Krishna"},
    {"index": 3, "username": "SBS2", "name": "Sharikar, Srikanth Rao"},
    {"index": 4, "username": "M20M", "name": "Mehdi, Syed Muhammad"},
    {"index": 5, "username": "S3XR", "name": "Shaik, Abdul Qavi"},
]

# Owner of every ITC ticket. Change Management rejects an unassigned ITC.
ITC_ASSIGNEE = "RWRW"

MAINT_EPIC_KEY    = "DMSC-399"
MAINT_SP          = {"jfrog": 3, "cloudbees": 5, "sonarqube": 2}
DMSC_COMPONENT_ID = "68203"   # DevOps Tools
DMSC_BOARD_ID     = 7118
DMSC_SPRINT_FIELD       = "customfield_10104"
DMSC_STORY_POINTS_FIELD = "customfield_10106"

# ─── On-call constants ────────────────────────────────────────────────────────

ON_CALL_TEAM = [
    {"username": "RWRW", "name": "Masood Rahimi"},
    {"username": "MDVF", "name": "Shantanu Mangalvedhekar"},
    {"username": "MGIB", "name": "Ramesh Krishna Mahimalur"},
    {"username": "M20M", "name": "Syed Muhammad Mehdi"},
    {"username": "S3XR", "name": "Abdul Qavi Shaik"},
]

_ON_CALL_DESCRIPTION = (
    "Provide On-Call support to ADOs and help with CLDSPT tickets.\n\n"
    "On-Call Responsibilities:\n\n"
    "1. *VictorOps Pages:* Monitor VictorOps for incoming pages. If paged, log in and triage the "
    "problem. If the issue cannot be resolved within 30 minutes, escalate to the team and join a "
    "bridge call to resolve. Document all pages on the On-Call Incidents Confluence page.\n\n"
    "2. *DevOps Tier Channel:* Monitor the DevOps Tier channel for tickets coming from the Tier 2 "
    "team. Review the Tier 2 comments to ensure an initial triage has been completed prior to "
    "investigating further. If no comments are present, push back to the Tier 2 team to complete "
    "their initial triage first.\n\n"
    "3. *Slack Channels:* Monitor the DevOps Discussion and DevsecOps Collab channels and respond "
    "to messages.\n\n"
    "4. *NO TICKET NO WORK:* Any DMs or ad-hoc requests must have a CLDSPT ticket created to track "
    "the work. No exceptions."
)

_ON_CALL_ACCEPTANCE_CRITERIA = (
    "* Ticket is updated with a complete list of CLDSPT tickets worked during the on-call week.\n"
    "* All VictorOps pages are documented on the On-Call Incidents Confluence page with triage "
    "notes and resolution or escalation outcome.\n"
    "* Any unresolved issues or follow-up items are communicated to the team before the end of "
    "the on-call week."
)

# Fields that cannot be set on ticket creation — skip them when cloning
_SKIP_ON_CREATE = {
    "reporter",   # let Jira default the reporter to the API-token user, not the template's
    "status", "resolution", "created", "updated", "creator", "id", "self",
    "subtasks", "timetracking", "votes", "watches", "worklog", "comment",
    "attachment", "changelog", "issuelinks", "resolutiondate", "lastViewed",
    "aggregatetimespent", "aggregatetimeoriginalestimate", "aggregatetimeestimate",
    "timespent", "timeestimate", "timeoriginalestimate", "progress", "aggregateprogress",
    # Jira-computed / read-only custom fields
    "customfield_10000",   # dev status bean
    "customfield_10105",   # lexorank
    "customfield_25252",   # max-long sentinel
    "customfield_34420",   # max-long sentinel
    "customfield_30529",   # numeric computed
    "customfield_33267",   # "Major" classification (computed)
}


def _headers() -> dict:
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {get_settings().JIRA_TOKEN}",
    }


def _mggd_headers() -> dict:
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {get_settings().MGGD_TOKEN}",
    }


# Static option IDs for MGGD PROD Deployment tickets (sourced from MGGD-62548)
_MGGD_CHANGE_TYPE_ROUTINE  = {"id": "21224"}   # Routine Changes & Operational Tasks
_MGGD_CHANGE_TYPE_INFRA    = {"id": "21220"}   # Infrastructure and Technical
_MGGD_ORG_CMS_CLOUD        = {"id": "57419"}   # CMS Cloud
_MGGD_CHANGE_REASON_TECH   = {"id": "21261"}   # Technical Improvement
_MGGD_PRIORITY_MEDIUM      = {"id": "21264"}   # Medium
_MGGD_SYSTEM_AWS           = {"id": "21270"}   # AWS Infrastructure
_MGGD_MAINT_PAGE_NONE      = {"id": "21395"}   # None Required
_MGGD_DOWNTIME_APP         = {"id": "21399"}   # Application Downtime
_MGGD_DOWNTIME_NONE        = {"id": "21401"}   # No Downtime
_MGGD_IMPACTED_AWS         = [{"id": "21406"}] # AWS Infrastructure
_MGGD_GATE_REVIEW_NO       = {"id": "21452"}   # No
_MGGD_PLAN_YES             = {"id": "21912"}   # Implementation/Rollback Plan Attached: Yes
_MGGD_PLAN_NO              = {"id": "21913"}   # Implementation/Rollback Plan Attached: No
# Cascading select: parent AWS + child Infrastructure.PROD
_MGGD_PROVIDER_AWS         = {"id": "28904", "child": {"id": "30188"}}
_MGGD_NO_SURPRISES_NA      = [{"id": "48177"}] # Not Applicable
_MGGD_INCIDENT_NO          = {"id": "43903"}   # Is this change being made to support an incident: No


def _transform_value(value):
    """
    Convert a Jira field value from GET format to POST/create format.
    Option fields: {"id": "...", "value": "...", "self": "..."} → {"id": "..."}
    User fields:   {"name": "...", "displayName": "...", ...} → {"name": "..."}
    Group fields:  {"name": "...", "self": "..."} → {"name": "..."}
    Lists: transform each item recursively.
    Primitives: pass through.
    """
    if value is None:
        return None
    if isinstance(value, list):
        transformed = [_transform_value(item) for item in value]
        transformed = [v for v in transformed if v is not None]
        return transformed or None
    if isinstance(value, dict):
        if "id" in value and ("value" in value or "child" in value):
            # Select / cascading-select option
            result = {"id": value["id"]}
            if "child" in value and value["child"]:
                result["child"] = _transform_value(value["child"])
            return result
        if "name" in value and "displayName" in value:
            # User object
            return {"name": value["name"]}
        if "name" in value and "self" in value and "id" not in value:
            # Group or component
            return {"name": value["name"]}
        if "key" in value and "id" in value:
            # Version / fix-version
            return {"id": value["id"]}
        # Unknown dict shape — skip
        return None
    # String, int, float, bool
    return value


def _find_latest_maintenance_ticket() -> str:
    """Return the key of the most recent 'DevOps Service Maintenance' ITC ticket."""
    settings = get_settings()
    jql = 'project = ITC AND summary ~ "DevOps Service Maintenance" ORDER BY created DESC'
    url = f"{settings.JIRA_URL}/rest/api/2/search"
    resp = httpx.get(
        url,
        params={"jql": jql, "maxResults": 1, "fields": "summary,created"},
        headers=_headers(),
        timeout=15,
        verify=True,
    )
    resp.raise_for_status()
    issues = resp.json().get("issues", [])
    if not issues:
        raise RuntimeError("No existing DevOps Service Maintenance ticket found in ITC project")
    return issues[0]["key"]


def _get_issue_fields(key: str) -> dict:
    """Fetch all fields of an ITC ticket for cloning."""
    settings = get_settings()
    resp = httpx.get(
        f"{settings.JIRA_URL}/rest/api/2/issue/{key}",
        headers=_headers(),
        timeout=15,
        verify=True,
    )
    resp.raise_for_status()
    return resp.json()["fields"]


def _add_clone_link(new_key: str, original_key: str) -> None:
    """Add a 'Clones' issue link from new_key → original_key."""
    settings = get_settings()
    try:
        httpx.post(
            f"{settings.JIRA_URL}/rest/api/2/issueLink",
            json={
                "type": {"name": "Clones"},
                "inwardIssue": {"key": new_key},
                "outwardIssue": {"key": original_key},
            },
            headers=_headers(),
            timeout=10,
            verify=True,
        )
    except Exception as exc:
        logger.warning("Could not add clone link %s → %s: %s", new_key, original_key, exc)


def create_ticket(project: str, summary: str, description: str, issue_type: str = "Task",
                  extra_fields: dict | None = None) -> dict:
    """Minimal ticket creation used by other maintenance actions (Slack, etc.).

    ``extra_fields`` is merged into ``fields`` for projects that require more than
    the basics (e.g. JSM service desks with required custom fields)."""
    settings = get_settings()
    if not settings.JIRA_TOKEN:
        raise RuntimeError("JIRA_TOKEN is not configured")

    fields = {
        "project": {"key": project},
        "summary": summary,
        "description": description,
        "issuetype": {"name": issue_type},
    }
    if extra_fields:
        fields.update(extra_fields)

    resp = httpx.post(
        f"{settings.JIRA_URL}/rest/api/2/issue",
        json={"fields": fields},
        headers=_headers(),
        timeout=15,
        verify=True,
    )
    if not resp.is_success:
        raise RuntimeError(f"Jira API {resp.status_code}: {resp.text[:400]}")

    key = resp.json().get("key", "")
    return {"key": key, "url": f"{settings.JIRA_URL}/browse/{key}"}


def comment_ticket(key: str, body: str) -> None:
    """Add a comment to a jiraent (JIRA_TOKEN) ticket. Best-effort — raises on HTTP error."""
    _add_comment(get_settings().JIRA_URL, _headers(), key, body)


def assign_ticket(key: str, username: str) -> None:
    """Assign a jiraent (JIRA_TOKEN) issue to a user by username (Jira DC format).

    Raises on HTTP error so the caller can log it without losing an
    already-created ticket. Note: on a JSM service desk (e.g. CLDSPT) the
    assignee must be an agent on that desk, otherwise Jira rejects the assign.
    """
    settings = get_settings()
    resp = httpx.put(
        f"{settings.JIRA_URL}/rest/api/2/issue/{key}/assignee",
        json={"name": username},
        headers=_headers(),
        timeout=15,
        verify=True,
    )
    if not resp.is_success:
        raise RuntimeError(f"Jira assignee API {resp.status_code}: {resp.text[:300]}")


def _gb(n) -> str:
    try:
        return f"{float(n or 0) / 1024**3:.1f} GB"
    except (TypeError, ValueError):
        return "0.0 GB"


def create_cldspt_prune_ticket(
    controller: str,
    pct: float,
    categories: list[str],
    keep_builds: int,
    ado: str | None,
    engineer: str,
    top_consumers: list[dict] | None = None,
) -> dict:
    """
    Open a CLDSPT ticket documenting a real PVC prune, for the audit trail.

    Uses JIRA_TOKEN (the reporter is the token's user). Returns
    {"key", "url"}; the caller should treat failures as non-fatal (the prune
    still proceeds) and surface the error to the UI.
    """
    settings = get_settings()
    cats = ", ".join(categories) or "old builds / workspaces / caches"
    summary = f"PVC cleanup: prune {controller} controller (prod-east) at {pct}% disk usage"

    lines = [
        f"h3. Automated PVC cleanup — {controller} (prod-east)",
        "",
        f"The CloudBees Jenkins controller *{controller}* was at *{pct}%* PVC disk usage on "
        f"cluster {{{{jenkins-prod-east}}}} (Datadog monitor 283161). Old data is being pruned "
        f"to reclaim space; running jobs are unaffected.",
        "",
        f"* *Approved by (ADO):* {ado or '_not recorded_'}",
        f"* *Performed by:* {engineer or 'the DevOps team'}",
        f"* *Categories pruned:* {cats}",
        f"* *Builds retained per job:* {keep_builds}",
    ]
    if top_consumers:
        lines += ["", "h4. Top consumers at prune time"]
        for j in top_consumers[:10]:
            name = j.get("name")
            if name:
                lines.append(f"* {{{{{name}}}}} — {_gb(j.get('bytes'))}")
    lines += [
        "",
        "_Freed space will be added as a comment when the run completes._",
        "_Created automatically by the DevOps Dashboard Controller PVC Cleanup tile._",
    ]

    # CLDSPT ("CMS Cloud Support") is a JSM service desk — a Service Request needs
    # Request Type, Urgency, Production-system, and Application Name. IDs come from
    # config (discovered from the project; createmeta is restricted). Application
    # Name is a free-form array — default to the controller when not overridden.
    app_name = settings.CLDSPT_APP_NAME or controller
    extra_fields = {
        "customfield_15275": {"id": settings.CLDSPT_REQUEST_TYPE_ID},   # Request Type
        "customfield_15408": {"id": settings.CLDSPT_URGENCY_ID},        # How urgent
        "customfield_15407": {"id": settings.CLDSPT_PROD_ID},           # Production system?
        "customfield_15250": [app_name],                                # Application Name
    }

    return create_ticket(settings.CLDSPT_PROJECT, summary, "\n".join(lines),
                         settings.CLDSPT_ISSUE_TYPE, extra_fields=extra_fields)


def get_active_sprint_id() -> int | None:
    """The DMSC board's currently-active sprint id, or None if there isn't one
    (or the Agile API is unavailable). Best-effort — never raises."""
    settings = get_settings()
    try:
        resp = httpx.get(
            f"{settings.JIRA_URL}/rest/agile/1.0/board/{DMSC_BOARD_ID}/sprint",
            params={"state": "active"}, headers=_headers(), timeout=15, verify=True)
        if resp.is_success:
            values = resp.json().get("values", [])
            return values[0]["id"] if values else None
        logger.warning("Active-sprint lookup returned %s: %s", resp.status_code, resp.text[:200])
    except httpx.HTTPError as exc:
        logger.warning("Could not fetch active DMSC sprint: %s", exc)
    return None


def add_to_active_sprint(key: str) -> int | None:
    """Move an issue into the DMSC board's active sprint. Returns the sprint id,
    or None if there's no active sprint. Raises on API error so the caller can log."""
    sprint_id = get_active_sprint_id()
    if not sprint_id:
        return None
    settings = get_settings()
    resp = httpx.post(
        f"{settings.JIRA_URL}/rest/agile/1.0/sprint/{sprint_id}/issue",
        json={"issues": [key]}, headers=_headers(), timeout=15, verify=True)
    if not resp.is_success:
        raise RuntimeError(f"Jira sprint-add API {resp.status_code}: {resp.text[:300]}")
    return sprint_id


def create_dmsc_prune_ticket(
    controller: str,
    pct: float,
    categories,
    keep: int,
    ado: str,
    engineer: str = "",
) -> dict:
    """Open a DMSC Task documenting a real PVC prune: pointed 1 and added to the
    board's active sprint. (Assignment to the triggering engineer is done as a
    separate best-effort step by the caller.) Auto-closed Fixed on completion."""
    settings = get_settings()
    cats = ", ".join(
        (c.get("category") if isinstance(c, dict) else str(c)) for c in (categories or [])
    ) or "old builds / workspaces / caches"
    summary = f"PVC cleanup: prune Jenkins controller {controller} ({pct}% used)"
    lines = [
        f"Automated PVC prune of the prod-east Jenkins controller *{controller}*.",
        "",
        f"* *PVC usage at prune:* {pct}%",
        f"* *Categories pruned:* {cats}",
        f"* *Keep last N builds/job:* {keep}",
        f"* *ADO sign-off:* {ado or 'n/a'}",
        f"* *Triggered by:* {engineer or 'the DevOps team'}",
        "",
        "Freed space is recorded as a comment on completion; this ticket auto-closes (Fixed) when the prune finishes.",
    ]
    extra_fields = {
        DMSC_STORY_POINTS_FIELD: settings.DMSC_PRUNE_STORY_POINTS,
        "components": [{"id": DMSC_COMPONENT_ID}],   # DevOps Tools (required on DMSC)
    }
    ticket = create_ticket(settings.DMSC_PRUNE_PROJECT, summary, "\n".join(lines),
                           settings.DMSC_PRUNE_ISSUE_TYPE, extra_fields=extra_fields)
    try:
        sprint_id = add_to_active_sprint(ticket["key"])
        if sprint_id:
            ticket["sprint_id"] = sprint_id
    except Exception as exc:  # noqa: BLE001 — sprint placement is non-fatal
        logger.warning("Created %s but could not add to active sprint: %s", ticket.get("key"), exc)
    return ticket


def close_prune_ticket(key: str, resolution_id: str | None = None) -> dict:
    """Transition a DMSC prune ticket into a Done/Closed state with the given
    resolution (default: Fixed). Finds the right transition dynamically so it
    survives workflow tweaks; retries without the resolution field if the
    transition screen doesn't accept one."""
    settings = get_settings()
    resolution_id = resolution_id or settings.DMSC_FIXED_RESOLUTION_ID
    r = httpx.get(f"{settings.JIRA_URL}/rest/api/2/issue/{key}/transitions",
                  headers=_headers(), timeout=15, verify=True)
    transitions = r.json().get("transitions", []) if r.is_success else []
    target = None
    for t in transitions:
        to_name = (t.get("to", {}).get("name") or "").lower()
        name = (t.get("name") or "").lower()
        if to_name in ("done", "closed", "resolved") or any(w in name for w in ("done", "close", "resolve")):
            target = t
            break
    if not target:
        raise RuntimeError(
            f"No Done/Close transition available for {key} "
            f"(offered: {[t.get('name') for t in transitions]})")
    payload = {"transition": {"id": target["id"]}, "fields": {"resolution": {"id": resolution_id}}}
    resp = httpx.post(f"{settings.JIRA_URL}/rest/api/2/issue/{key}/transitions",
                      json=payload, headers=_headers(), timeout=15, verify=True)
    if not resp.is_success:
        # Some transition screens don't expose the resolution field — retry bare.
        resp = httpx.post(f"{settings.JIRA_URL}/rest/api/2/issue/{key}/transitions",
                          json={"transition": {"id": target["id"]}},
                          headers=_headers(), timeout=15, verify=True)
        if not resp.is_success:
            raise RuntimeError(f"Jira transition API {resp.status_code}: {resp.text[:300]}")
    return {"key": key, "status": (target.get("to") or {}).get("name"), "resolution_id": resolution_id}


def create_itc_maintenance_ticket(
    maintenance_date: str,       # "MM-DD-YYYY" displayed in summary
    description: str,            # full Jira wiki markup description
    start_dt: str,               # ISO datetime e.g. "2026-10-17T09:00:00.000-0400"
    end_dt: str,                 # ISO datetime for maintenance window close
    confluence_url: str = "",
    mggd_url: str = "",
) -> dict:
    """
    Clone the latest DevOps Service Maintenance ITC ticket and apply the
    new maintenance-specific overrides. Returns {"key": "ITC-XXXX", "url": "..."}.
    """
    settings = get_settings()
    if not settings.JIRA_TOKEN:
        raise RuntimeError("JIRA_TOKEN is not configured")

    # 1. Find template ticket
    template_key = _find_latest_maintenance_ticket()
    logger.info("Cloning ITC maintenance ticket from %s", template_key)
    template_fields = _get_issue_fields(template_key)

    # 2. Build create payload from template (transform all fields)
    create_fields: dict = {}
    for field_name, value in template_fields.items():
        if field_name in _SKIP_ON_CREATE:
            continue
        transformed = _transform_value(value)
        if transformed is not None:
            create_fields[field_name] = transformed

    # 3. Apply overrides for the new maintenance window
    # Set issue type explicitly. The cloned template's issuetype is a plain
    # {id, name, self, ...} object that _transform_value can't map, so it drops
    # to None and Jira rejects the create with "issue type is required". ITC uses
    # "Change Request" (id 11001).
    create_fields["issuetype"] = {"id": "11001"}
    create_fields["summary"] = f"DevOps Service Maintenance {maintenance_date}"
    create_fields["description"] = description
    create_fields["customfield_12809"] = start_dt           # Maintenance start
    create_fields["customfield_20400"] = end_dt             # Maintenance window close
    create_fields["customfield_12822"] = end_dt             # Scheduled end

    if confluence_url:
        create_fields["customfield_20404"] = confluence_url

    # Resolve the MGGD link. The frontend sends mggd_url when it found this
    # month's MGGD ticket on modal open; if it came back empty we look it up here
    # so the ITC still gets the right link (the MGGD ticket is normally created
    # before the ITC). Always assign the field — the ITC is cloned from last
    # month's template, and customfield_15206 would otherwise carry the previous
    # month's MGGD link straight through.
    resolved_mggd_url = mggd_url
    if not resolved_mggd_url:
        try:
            found = find_this_month_maintenance_tickets().get("mggd")
            if found:
                resolved_mggd_url = found["url"]
                logger.info("ITC: auto-resolved MGGD link via lookup: %s", resolved_mggd_url)
        except Exception as exc:
            logger.warning("ITC: MGGD link fallback lookup failed: %s", exc)
    create_fields["customfield_15206"] = resolved_mggd_url

    # The "Additional Info" field (customfield_13004) is cloned from the template
    # and its Marketplace-impact question (#2) still points at last month's MGGD
    # ticket. Repoint that link to this cycle's MGGD ticket.
    addl = create_fields.get("customfield_13004")
    if resolved_mggd_url and isinstance(addl, str):
        create_fields["customfield_13004"] = re.sub(
            r"https?://jira\.cms\.gov/browse/MGGD-\d+",
            resolved_mggd_url,
            addl,
        )

    # Assign the ITC rather than leaving it unassigned. Change Management
    # rejects an unassigned ITC, and the clone would otherwise carry the
    # template's assignee. Set after creation too, since on some ITC projects
    # assignee is not on the create screen and Jira drops it there.
    create_fields["assignee"] = {"name": ITC_ASSIGNEE}

    # 4. POST to create. The clone copies fields that aren't on the ITC create
    # screen; Jira rejects those with "cannot be set ... not on the appropriate
    # screen, or unknown". Drop exactly the fields Jira names and retry, instead
    # of maintaining a hardcoded skip-list. A "is required" error is never
    # dropped (it falls through to raise), so we won't silently create a bad ticket.
    resp = None
    for _attempt in range(8):
        resp = httpx.post(
            f"{settings.JIRA_URL}/rest/api/2/issue",
            json={"fields": create_fields},
            headers=_headers(),
            timeout=20,
            verify=True,
        )
        if resp.is_success:
            break
        if resp.status_code == 400:
            try:
                errs = resp.json().get("errors", {}) or {}
            except Exception:
                errs = {}
            droppable = [
                f for f, msg in errs.items()
                if f in create_fields
                and ("cannot be set" in msg or "not on the appropriate screen" in msg)
            ]
            if droppable:
                for f in droppable:
                    create_fields.pop(f, None)
                logger.warning("ITC create: dropping non-settable fields and retrying: %s", droppable)
                continue
        raise RuntimeError(
            f"Jira API {resp.status_code} creating ITC ticket: {resp.text[:600]}"
        )
    else:
        raise RuntimeError(
            f"Jira API: gave up creating ITC ticket after retries: "
            f"{resp.text[:400] if resp is not None else 'no response'}"
        )

    new_key = resp.json().get("key", "")
    new_url = f"{settings.JIRA_URL}/browse/{new_key}"
    logger.info("Created ITC maintenance ticket %s", new_key)

    # 5. Add clone link
    _add_clone_link(new_key, template_key)

    # 5b. Assign explicitly. On this project assignee is not on the create
    # screen, so Jira silently drops it from the create payload; the dedicated
    # assign endpoint is the one that sticks. Best-effort: an unassigned ticket
    # is a Change Management rejection, not a reason to fail creation and leave
    # the caller unsure whether a ticket exists.
    assigned = False
    try:
        r = httpx.put(
            f"{settings.JIRA_URL}/rest/api/2/issue/{new_key}/assignee",
            headers={**_headers(), "Content-Type": "application/json"},
            json={"name": ITC_ASSIGNEE}, timeout=30, verify=True,
        )
        assigned = r.status_code in (200, 204)
        if not assigned:
            logger.warning("Could not assign %s to %s: %s %s",
                           new_key, ITC_ASSIGNEE, r.status_code, r.text[:200])
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not assign %s to %s: %s", new_key, ITC_ASSIGNEE, exc)

    # 6. Move Draft -> Ready for Review (best-effort; never fail creation on it)
    transitioned = False
    try:
        _apply_transition(settings.JIRA_URL, _headers(), new_key, "Ready for Review")
        transitioned = True
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not transition %s to Ready for Review: %s", new_key, exc)

    return {"key": new_key, "url": new_url, "cloned_from": template_key,
            "transitioned": transitioned, "assigned_to": ITC_ASSIGNEE if assigned else None}


def _add_comment(base_url: str, headers: dict, ticket_key: str, body: str) -> None:
    resp = httpx.post(
        f"{base_url}/rest/api/2/issue/{ticket_key}/comment",
        json={"body": body},
        headers=headers,
        timeout=15,
    )
    resp.raise_for_status()


def _apply_transition(base_url: str, headers: dict, ticket_key: str, transition_name: str) -> None:
    resp = httpx.get(
        f"{base_url}/rest/api/2/issue/{ticket_key}/transitions",
        headers=headers,
        timeout=15,
    )
    resp.raise_for_status()
    transitions = resp.json().get("transitions", [])
    match = next((t for t in transitions if t["name"].lower() == transition_name.lower()), None)
    if not match:
        available = [t["name"] for t in transitions]
        raise ValueError(f"Transition '{transition_name}' not found. Available: {available}")
    resp = httpx.post(
        f"{base_url}/rest/api/2/issue/{ticket_key}/transitions",
        json={"transition": {"id": match["id"]}},
        headers=headers,
        timeout=15,
    )
    resp.raise_for_status()


def close_itc_ticket(ticket_key: str) -> dict:
    """Add completion comment and transition ITC ticket to Implemented."""
    settings = get_settings()
    headers = _headers()
    _add_comment(settings.JIRA_URL, headers, ticket_key, "Maintenance Successfully Completed")
    _apply_transition(settings.JIRA_URL, headers, ticket_key, "Implemented")
    return {"key": ticket_key, "url": f"{settings.JIRA_URL}/browse/{ticket_key}"}


def close_mggd_ticket(ticket_key: str) -> dict:
    """Add completion comment to MGGD ticket (no transition required)."""
    settings = get_settings()
    _add_comment(settings.MGGD_URL, _mggd_headers(), ticket_key, "Maintenance Successfully Completed")
    return {"key": ticket_key, "url": f"{settings.MGGD_URL}/browse/{ticket_key}"}


# Status names across the two Jira instances (ITC uses "Closed"/"Done"-style
# names, MGGD uses its own change-management workflow) that should read as
# "no longer active" on the maintenance ticket overview widget.
_CLOSED_STATUSES = {"closed", "done", "resolved", "cancelled", "canceled", "rejected"}


def find_this_month_maintenance_tickets() -> dict:
    """
    Search both Jira instances for this month's DevOps Service Maintenance tickets.
    Returns {"itc": {"key": ..., "url": ...} | None, "mggd": {"key": ..., "url": ...} | None}.
    """
    settings = get_settings()
    # ITC tickets are created in-cycle, so scope to this month to find the current one.
    itc_jql = 'project = ITC AND summary ~ "DevOps Service Maintenance" AND created >= startOfMonth() ORDER BY created DESC'
    # MGGD tickets are cut ahead of the maintenance date (often the prior month), so do
    # NOT month-box them — take the most recently created maintenance ticket instead.
    mggd_jql = 'project = MGGD AND summary ~ "DevOps Service Maintenance" ORDER BY created DESC'

    itc = None
    try:
        resp = httpx.get(
            f"{settings.JIRA_URL}/rest/api/2/search",
            params={"jql": itc_jql, "maxResults": 1, "fields": "summary,status"},
            headers=_headers(),
            timeout=15,
            verify=True,
        )
        resp.raise_for_status()
        issues = resp.json().get("issues", [])
        if issues:
            key = issues[0]["key"]
            issue_status = (issues[0].get("fields", {}).get("status") or {}).get("name")
            itc = {
                "key": key,
                "url": f"{settings.JIRA_URL}/browse/{key}",
                "status": issue_status,
                "is_closed": (issue_status or "").lower() in _CLOSED_STATUSES,
            }
    except Exception as exc:
        logger.warning("Could not fetch ITC maintenance ticket: %s", exc)

    mggd = None
    try:
        resp = httpx.get(
            f"{settings.MGGD_URL}/rest/api/2/search",
            params={"jql": mggd_jql, "maxResults": 1, "fields": "summary,status"},
            headers=_mggd_headers(),
            timeout=15,
            verify=True,
        )
        resp.raise_for_status()
        issues = resp.json().get("issues", [])
        if issues:
            key = issues[0]["key"]
            issue_status = (issues[0].get("fields", {}).get("status") or {}).get("name")
            mggd = {
                "key": key,
                "url": f"{settings.MGGD_URL}/browse/{key}",
                "status": issue_status,
                "is_closed": (issue_status or "").lower() in _CLOSED_STATUSES,
            }
    except Exception as exc:
        logger.warning("Could not fetch MGGD maintenance ticket: %s", exc)

    return {"itc": itc, "mggd": mggd}


def get_latest_prep_tickets() -> dict:
    """Report the most recently created prep ticket per tool, regardless of
    which maintenance window it was for.

    Unlike get_maint_prep_status() (which only counts a ticket if it matches
    a specific *upcoming* maintenance date — used to gate new-ticket
    creation), this just answers "what's the latest prep ticket for each
    tool right now" for a status overview. That means it naturally shows
    this cycle's tickets right up until next cycle's prep tickets get
    created, at which point it rolls over on its own — no date math needed.

    Returns {tools: {tool: {key,url,assignee,assignee_name,status} | None}}.
    """
    settings = get_settings()
    tools: dict = {}
    for tool, summary in _MAINT_PREP_SUMMARIES.items():
        found = None
        try:
            jql = f'project=DMSC AND summary~"\\"{summary}\\"" ORDER BY created DESC'
            resp = httpx.get(
                f"{settings.JIRA_URL}/rest/api/2/search",
                params={"jql": jql, "maxResults": 1,
                        "fields": "summary,assignee,status"},
                headers=_headers(), timeout=15, verify=True,
            )
            resp.raise_for_status()
            issues = resp.json().get("issues", [])
            if issues:
                iss = issues[0]
                f = iss.get("fields", {})
                a = f.get("assignee") or {}
                found = {
                    "key": iss["key"],
                    "url": f"{settings.JIRA_URL}/browse/{iss['key']}",
                    "assignee": a.get("name"),
                    "assignee_name": a.get("displayName"),
                    "status": (f.get("status") or {}).get("name"),
                }
        except Exception as exc:  # noqa: BLE001 — status check is best-effort
            logger.warning("latest-prep lookup failed for %s: %s", tool, exc)
        tools[tool] = found
    return {"tools": tools}


def get_maintenance_overview() -> dict:
    """
    Combine the latest prep ticket per tool (DMSC) with this cycle's ITC and
    MGGD tickets into one payload for the Dashboard's maintenance-ticket-status
    widget, so the team doesn't have to open Jira to see what's outstanding.
    Each rolls over on its own once next cycle's tickets are created.

    Returns {prep: {tools: {...}}, itc: {...} | None, mggd: {...} | None}.
    """
    prep = get_latest_prep_tickets()
    tickets = find_this_month_maintenance_tickets()
    return {
        "prep": prep,
        "itc": tickets.get("itc"),
        "mggd": tickets.get("mggd"),
    }


def get_mggd_ticket_tasks(ticket_key: str) -> dict:
    """
    Fetch an MGGD ticket and parse per-tool bullet points from its description.
    Returns {"jfrog": str, "jenkins": str, "sonar": str} where each value is
    newline-separated task lines (empty string if no bullets found).
    """
    settings = get_settings()
    resp = httpx.get(
        f"{settings.MGGD_URL}/rest/api/2/issue/{ticket_key}",
        params={"fields": "description"},
        headers=_mggd_headers(),
        timeout=15,
        verify=True,
    )
    resp.raise_for_status()
    description: str = resp.json().get("fields", {}).get("description", "") or ""

    def _extract_section(text: str, header: str) -> str:
        """Extract ** bullet lines under a * <header>: section in Jira wiki markup."""
        lines = text.splitlines()
        in_section = False
        bullets: list[str] = []
        header_marker = f"* {header}:"
        for line in lines:
            stripped = line.strip()
            if stripped == header_marker:
                in_section = True
                continue
            if in_section:
                if stripped.startswith("** "):
                    bullets.append(stripped[3:].strip())
                elif stripped.startswith("* ") and not stripped.startswith("** "):
                    break
        return "\n".join(bullets)

    return {
        "jfrog":   _extract_section(description, "Jfrog"),
        "jenkins": _extract_section(description, "CB Jenkins"),
        "sonar":   _extract_section(description, "SonarQube"),
    }


def _attach_to_mggd(ticket_key: str, filename: str, file_bytes: bytes) -> None:
    """Upload a file as an attachment to an MGGD Jira ticket."""
    settings = get_settings()
    headers = {
        "Authorization": f"Bearer {settings.MGGD_TOKEN}",
        "X-Atlassian-Token": "no-check",
    }
    resp = httpx.post(
        f"{settings.MGGD_URL}/rest/api/2/issue/{ticket_key}/attachments",
        headers=headers,
        files={
            "file": (
                filename,
                file_bytes,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
        timeout=30,
        verify=True,
    )
    if not resp.is_success:
        raise RuntimeError(
            f"MGGD attachment upload failed {resp.status_code}: {resp.text[:400]}"
        )


def create_mggd_maintenance_ticket(
    maintenance_date: str,              # "MM-DD-YYYY" — used in ticket summary
    description: str,                   # Jira wiki markup body
    start_dt: str,                      # ISO datetime e.g. "2026-10-17T09:00:00.000-0400"
    end_dt: str,                        # ISO datetime for window close
    go_nogo_review_date: str,           # "YYYY-MM-DD" — typically the Friday before maintenance
    release_number: str,                # e.g. "Cloudbees_2.528.2.xx"
    downtime: bool = True,              # True → Application Downtime, False → No Downtime
    impl_rollback_plan_attached: bool = True,
    itc_key: str = "",                  # ITC ticket number for the IR Plan (optional)
) -> dict:
    """
    Create a PROD Deployment ticket in MGGD (jira.cms.gov) for a DevOps maintenance window,
    then generate and attach the IR Plan and Change Management Excel spreadsheets.
    Returns {"key": "MGGD-XXXXX", "url": "..."}.
    """
    settings = get_settings()
    if not settings.MGGD_TOKEN:
        raise RuntimeError("MGGD_TOKEN is not configured")

    fields = {
        "project":   {"key": "MGGD"},
        "issuetype": {"id": "14403"},    # PROD Deployment
        "summary":   f"{maintenance_date} DevOps Service Maintenance",
        "description": description,

        # Deployment window dates
        "customfield_15301": go_nogo_review_date,   # Go/No Go Review Date (YYYY-MM-DD)
        "customfield_15322": start_dt,              # PROD Deployment Start Date/Time
        "customfield_15323": end_dt,                # PROD Deployment End Date/Time

        # Select / option fields
        "customfield_15302": _MGGD_CHANGE_TYPE_ROUTINE,
        "customfield_15307": _MGGD_ORG_CMS_CLOUD,
        "customfield_15308": _MGGD_CHANGE_REASON_TECH,
        "customfield_15310": _MGGD_PRIORITY_MEDIUM,
        "customfield_15311": _MGGD_SYSTEM_AWS,
        "customfield_15325": _MGGD_MAINT_PAGE_NONE,
        "customfield_15326": _MGGD_DOWNTIME_APP if downtime else _MGGD_DOWNTIME_NONE,
        "customfield_15327": _MGGD_IMPACTED_AWS,    # Other PROD Impacted Systems
        "customfield_15329": _MGGD_GATE_REVIEW_NO,
        "customfield_15506": _MGGD_PLAN_YES if impl_rollback_plan_attached else _MGGD_PLAN_NO,
        "customfield_18934": _MGGD_PROVIDER_AWS,
        "customfield_28529": _MGGD_NO_SURPRISES_NA,
        "customfield_26201": _MGGD_INCIDENT_NO,        # Is this change being made to support an incident
        "customfield_26202": "N/A",                     # Incident Ticket Number

        # User picker — GTL (Lijun Shao)
        "customfield_15313": {"name": settings.MGGD_GTL_USER},

        # Free-text fields
        "customfield_15304": settings.MGGD_POC_NAME,
        "customfield_15305": settings.MGGD_POC_PHONE,
        "customfield_15306": settings.MGGD_POC_EMAIL,
        "customfield_15309": (
            "Upgrade of DevOps components to current releases to get "
            "technical improvements and security fixes."
        ),
        "customfield_18929": release_number,
        "customfield_18933": settings.MGGD_SIGNOFF_NAME,
    }

    resp = httpx.post(
        f"{settings.MGGD_URL}/rest/api/2/issue",
        json={"fields": fields},
        headers=_mggd_headers(),
        timeout=20,
        verify=True,
    )
    if not resp.is_success:
        raise RuntimeError(
            f"MGGD Jira API {resp.status_code} creating ticket: {resp.text[:600]}"
        )

    key = resp.json().get("key", "")
    url = f"{settings.MGGD_URL}/browse/{key}"
    logger.info("Created MGGD maintenance ticket %s", key)

    # Generate and attach the two Excel spreadsheets
    try:
        from app.services.excel_service import generate_ir_plan, generate_change_management_form

        # IR-plan task owners = the engineer assigned to each tool's prep ticket.
        tool_owners = None
        try:
            md_str = get_next_maintenance_date().strftime("%B %-d, %Y")
            ps = get_maint_prep_status(md_str)
            pool_by_user = {m["username"]: m["name"] for m in MAINT_TEAM_POOL}
            tool_owners = {}
            for tool, info in ps.get("tools", {}).items():
                if info and info.get("assignee"):
                    nm = pool_by_user.get(info["assignee"]) or info.get("assignee_name") or ""
                    # "Rahimi, Masood" -> "Masood Rahimi"
                    tool_owners[tool] = " ".join(p.strip() for p in reversed(nm.split(",", 1))) if "," in nm else nm
        except Exception as exc:  # noqa: BLE001 — owners are best-effort
            logger.warning("Could not compute IR-plan owners: %s", exc)

        ir_bytes = generate_ir_plan(
            mggd_key=key,
            itc_key=itc_key,
            go_nogo_date=go_nogo_review_date,
            start_dt=start_dt,
            end_dt=end_dt,
            description=description,
            maintenance_date=maintenance_date,
            tool_owners=tool_owners,
        )
        _attach_to_mggd(
            key,
            f"IR Plan - cms-cloud-devops-services-maintenance-{maintenance_date}.xlsx",
            ir_bytes,
        )
        logger.info("Attached IR Plan to %s", key)

        cm_bytes = generate_change_management_form(
            start_dt=start_dt,
            end_dt=end_dt,
            description=description,
            go_nogo_date=go_nogo_review_date,
            maintenance_date=maintenance_date,
        )
        _attach_to_mggd(
            key,
            f"CMS Enterprise Change Management Downtime-{maintenance_date}.xlsx",
            cm_bytes,
        )
        logger.info("Attached Change Management form to %s", key)
    except Exception as exc:
        logger.warning("Could not attach Excel files to %s: %s", key, exc)

    return {"key": key, "url": url}


# ─── Maintenance prep helpers ─────────────────────────────────────────────────

def _third_saturday(year: int, month: int) -> date:
    """Date of the 3rd Saturday, which is always the Saturday of the 3rd week:
    the 1st Saturday falls on day 1-7, so the 3rd falls on day 15-21."""
    cal = calendar.monthcalendar(year, month)
    saturdays = [week[calendar.SATURDAY] for week in cal if week[calendar.SATURDAY] != 0]
    return date(year, month, saturdays[2])


def get_next_maintenance_date() -> date:
    """Return the maintenance date: an admin override when set (and not yet past),
    otherwise the 3rd Saturday of the current month (the Saturday of the 3rd
    week), or next month if it has passed.

    The window itself runs 9 AM to 1 PM ET; those times live with the forms that
    submit them (frontend/src/utils/maintenanceWindow.ts) and in
    maint_notify.MAINT_WINDOW_LABEL for the emails."""
    # Admin override takes precedence when enabled and still upcoming.
    from app.services import maint_date_override
    override = maint_date_override.get_override_date()
    if override is not None:
        return override

    today = date.today()
    third_sat = _third_saturday(today.year, today.month)
    if today <= third_sat:
        return third_sat
    next_month = today.month % 12 + 1
    next_year  = today.year + (1 if today.month == 12 else 0)
    return _third_saturday(next_year, next_month)


def get_dmsc_sprints() -> list[dict]:
    """Return active and future DMSC sprints from the scrum board, including dates."""
    settings = get_settings()
    resp = httpx.get(
        f"{settings.JIRA_URL}/rest/agile/1.0/board/{DMSC_BOARD_ID}/sprint",
        params={"state": "active,future", "maxResults": 10},
        headers=_headers(),
        timeout=15,
        verify=True,
    )
    resp.raise_for_status()
    return [
        {
            "id":        s["id"],
            "name":      s["name"],
            "state":     s["state"],
            "startDate": s.get("startDate"),
            "endDate":   s.get("endDate"),
        }
        for s in resp.json().get("values", [])
    ]


def create_dmsc_sprint(name: str, start_date: str, end_date: str) -> dict:
    """Create a new sprint on the DMSC board. Returns the created sprint dict."""
    settings = get_settings()
    resp = httpx.post(
        f"{settings.JIRA_URL}/rest/agile/1.0/sprint",
        json={"name": name, "originBoardId": DMSC_BOARD_ID, "startDate": start_date, "endDate": end_date},
        headers=_headers(),
        timeout=15,
        verify=True,
    )
    resp.raise_for_status()
    s = resp.json()
    return {"id": s["id"], "name": s["name"], "state": s["state"], "startDate": s.get("startDate"), "endDate": s.get("endDate")}


def _add_to_sprint(sprint_id: int, keys: list[str]) -> None:
    settings = get_settings()
    try:
        httpx.post(
            f"{settings.JIRA_URL}/rest/agile/1.0/sprint/{sprint_id}/issue",
            json={"issues": keys},
            headers=_headers(),
            timeout=15,
            verify=True,
        )
    except Exception as exc:
        logger.warning("Could not add tickets to sprint %s: %s", sprint_id, exc)


TOOL_ROTATION_ORDER = ("jfrog", "cloudbees", "sonarqube")


def maint_cycle_index(maint_date: date) -> int:
    """Monotonic month counter for a maintenance date, used to drive the rotation."""
    return maint_date.year * 12 + maint_date.month


def rotation_for_cycle(cycle: int, pool: list[dict] | None = None) -> dict:
    """Assign the three prep tools for one maintenance cycle.

    Two independent walks, both driven by the cycle counter:

    * ``start`` advances three places per cycle, so each cycle draws a trio of
      distinct engineers and consecutive cycles do not reuse anyone.
    * ``offset`` rotates which tool each slot in that trio receives.

    The offset is what keeps tools moving: deriving ``start`` alone from the
    cycle repeats every ``size / 3`` cycles whenever the size is a multiple of
    three, which pinned every engineer to one tool once the pool reached six.

    How the offset advances depends on the pool size, because the two cases
    behave differently:

    * When three divides the size, the pool splits into fixed trios and
      ``start`` only ever takes ``size / 3`` values. The offset then has to step
      once per completed pass, or a trio draws the same tools every time it
      comes round.
    * Otherwise ``start`` already walks every position, so stepping the offset
      once per cycle is enough.

    Checked exhaustively for sizes 3 to 24: every engineer reaches all three
    tools, nobody appears twice in a cycle, the load stays even, and a trio
    never repeats the same tool split on consecutive appearances.
    """
    pool = pool if pool is not None else MAINT_TEAM_POOL
    size = len(pool)
    start = (cycle * 3) % size
    offset = ((cycle * 3) // size if size % 3 == 0 else cycle) % 3
    return {
        tool: pool[(start + (i + offset) % 3) % size]
        for i, tool in enumerate(TOOL_ROTATION_ORDER)
    }


def get_maint_prep_rotation() -> dict:
    """
    Compute the prep-ticket rotation for the next maintenance window.

    Assignment is derived from the maintenance month, not from the previous
    ticket's assignee: chaining off the last assignee meant a pool size
    divisible by three collapsed into a two-cycle loop that gave every engineer
    the same tool every month. ``last_jfrog_assignee`` is still reported for
    reference but no longer influences the result.
    """
    settings = get_settings()
    last_username: str | None = None
    try:
        jql = 'project=DMSC AND summary~"Monthly Maintenance: Jfrog Prep" ORDER BY created DESC'
        resp = httpx.get(
            f"{settings.JIRA_URL}/rest/api/2/search",
            params={"jql": jql, "maxResults": 1, "fields": "assignee"},
            headers=_headers(),
            timeout=15,
            verify=True,
        )
        resp.raise_for_status()
        issues = resp.json().get("issues", [])
        if issues:
            assignee = issues[0]["fields"].get("assignee")
            last_username = assignee["name"] if assignee else None
    except Exception as exc:
        logger.warning("Could not determine last JFrog prep assignee: %s", exc)

    cycle = maint_cycle_index(get_next_maintenance_date())
    return {
        **rotation_for_cycle(cycle),
        "last_jfrog_assignee": last_username,
    }


# Prep-ticket summaries per tool (must match create_maint_prep_tickets below).
_MAINT_PREP_SUMMARIES = {
    "jfrog":     "Monthly Maintenance: Jfrog Prep",
    "cloudbees": "Monthly Maintenance: Cloudbees Prep",
    "sonarqube": "Monthly Maintenance: SonarQube Prep",
}


_PREP_DATE_RE = re.compile(r"([A-Z][a-z]+ \d{1,2}, \d{4})")

# How far a prep ticket's stated window can sit from the current maintenance
# date and still count as this window's prep. An override that nudges the date
# by a day or two must not orphan prep tickets that were already created.
_PREP_NEAR_DAYS = 10


def _parse_display_date(value: str | None) -> date | None:
    """Parse "October 17, 2026" back to a date."""
    if not value:
        return None
    try:
        return datetime.strptime(value.strip(), "%B %d, %Y").date()
    except ValueError:
        return None


def get_maint_prep_status(maint_date_str: str) -> dict:
    """Report which of the 3 prep tickets exist for a given maintenance window.

    Prep summaries repeat every month, so the ticket has to be tied to a window.
    It is matched on the date its body states ("...ready for prod deployment on
    <date>."), preferring an exact match on ``maint_date_str`` and otherwise
    taking the most recent ticket whose stated window is within
    ``_PREP_NEAR_DAYS`` of it.

    That tolerance is the point: requiring an exact string match meant moving
    the window by a single day reported all three tickets as missing and told
    the engineer to create duplicates. A near match is reported with the date it
    actually states, so the mismatch is visible rather than silent.

    Returns ``{all_created, tools: {tool: {...} | None}, date_mismatch: [...]}``.
    The per-tool assignee also feeds the IR-plan owners.
    """
    settings = get_settings()
    target = _parse_display_date(maint_date_str)
    tools: dict = {}
    all_created = True
    mismatched: list[str] = []

    for tool, summary in _MAINT_PREP_SUMMARIES.items():
        found = None
        try:
            jql = f'project=DMSC AND summary~"\\"{summary}\\"" AND created>=-45d ORDER BY created DESC'
            resp = httpx.get(
                f"{settings.JIRA_URL}/rest/api/2/search",
                params={"jql": jql, "maxResults": 5,
                        "fields": "summary,description,assignee,status"},
                headers=_headers(), timeout=15, verify=True,
            )
            resp.raise_for_status()

            def _record(iss: dict, stated: str | None) -> dict:
                f = iss.get("fields", {})
                a = f.get("assignee") or {}
                return {
                    "key": iss["key"],
                    "url": f"{settings.JIRA_URL}/browse/{iss['key']}",
                    "assignee": a.get("name"),
                    "assignee_name": a.get("displayName"),
                    "status": (f.get("status") or {}).get("name"),
                    "window_date_str": stated,
                    "exact": stated == maint_date_str,
                }

            issues = resp.json().get("issues", [])
            # Ordered newest first, so the first exact match is the current one.
            for iss in issues:
                body = (iss.get("fields", {}).get("description") or "")
                if maint_date_str and maint_date_str in body:
                    found = _record(iss, maint_date_str)
                    break

            if found is None and target is not None:
                best = None
                for iss in issues:
                    body = (iss.get("fields", {}).get("description") or "")
                    m = _PREP_DATE_RE.search(body)
                    stated = _parse_display_date(m.group(1)) if m else None
                    if stated is None:
                        continue
                    gap = abs((stated - target).days)
                    if gap <= _PREP_NEAR_DAYS and (best is None or gap < best[0]):
                        best = (gap, _record(iss, m.group(1)))
                if best is not None:
                    found = best[1]
                    mismatched.append(tool)
        except Exception as exc:  # noqa: BLE001 — status check is best-effort
            logger.warning("prep-status lookup failed for %s: %s", tool, exc)
        tools[tool] = found
        if found is None:
            all_created = False

    return {"all_created": all_created, "tools": tools, "date_mismatch": mismatched}


def create_maint_prep_tickets(
    sprint_id: int,
    maint_date_str: str,     # "Month D, YYYY" display string
    jfrog_assignee: str,
    cloudbees_assignee: str,
    sonarqube_assignee: str,
) -> list[dict]:
    """Create 3 DMSC maintenance prep tasks, set epic + story points, add to sprint."""
    settings = get_settings()
    if not settings.JIRA_TOKEN:
        raise RuntimeError("JIRA_TOKEN is not configured")

    configs = [
        {
            "service":   "jfrog",
            "summary":   "Monthly Maintenance: Jfrog Prep",
            "body":      f"This ticket is to prepare for the upcoming monthly maintenance of Jfrog Platform deployment in production. Please run through the updates in Dev and then test using the Test Plan document on Confluence to make sure we are ready for prod deployment on {maint_date_str}.",
            "assignee":  jfrog_assignee,
            "sp":        MAINT_SP["jfrog"],
        },
        {
            "service":   "cloudbees",
            "summary":   "Monthly Maintenance: Cloudbees Prep",
            "body":      f"This ticket is to prepare for the upcoming monthly maintenance of Cloudbees Jenkins deployment in production and gov cloud production. Please run through the updates in Dev and then test using the Test Plan document on Confluence to make sure we are ready for prod deployment on {maint_date_str}.",
            "assignee":  cloudbees_assignee,
            "sp":        MAINT_SP["cloudbees"],
        },
        {
            "service":   "sonarqube",
            "summary":   "Monthly Maintenance: SonarQube Prep",
            "body":      f"This ticket is to prepare for the upcoming monthly maintenance of SonarQube deployment in production. Please run through the updates in Dev and then test using the Test Plan document on Confluence to make sure we are ready for prod deployment on {maint_date_str}.",
            "assignee":  sonarqube_assignee,
            "sp":        MAINT_SP["sonarqube"],
        },
    ]

    created: list[dict] = []
    for cfg in configs:
        resp = httpx.post(
            f"{settings.JIRA_URL}/rest/api/2/issue",
            json={"fields": {
                "project":    {"key": "DMSC"},
                "issuetype":  {"name": "Task"},
                "summary":    cfg["summary"],
                "description": cfg["body"],
                "assignee":   {"name": cfg["assignee"]},
                "components": [{"id": DMSC_COMPONENT_ID}],
            }},
            headers=_headers(),
            timeout=15,
            verify=True,
        )
        if not resp.is_success:
            raise RuntimeError(f"Jira {resp.status_code} creating {cfg['service']} ticket: {resp.text[:400]}")
        key = resp.json()["key"]

        # Set epic link + story points
        httpx.put(
            f"{settings.JIRA_URL}/rest/api/2/issue/{key}",
            json={"fields": {"customfield_10100": MAINT_EPIC_KEY, "customfield_10106": cfg["sp"]}},
            headers=_headers(),
            timeout=10,
            verify=True,
        )

        created.append({
            "key":      key,
            "url":      f"{settings.JIRA_URL}/browse/{key}",
            "service":  cfg["service"],
            "assignee": cfg["assignee"],
            "sp":       cfg["sp"],
        })
        logger.info("Created maint prep ticket %s (%s → %s)", key, cfg["service"], cfg["assignee"])

    if sprint_id:
        _add_to_sprint(sprint_id, [t["key"] for t in created])

    return created


# ─── On-call ticket helpers ───────────────────────────────────────────────────

def create_on_call_tickets(sprint_id: int, weeks: list[dict]) -> list[dict]:
    """
    Create on-call Story tickets for each week.
    weeks: [{"week": 1, "assignee": "RWRW"}, ...]
    """
    settings = get_settings()
    if not settings.JIRA_TOKEN:
        raise RuntimeError("JIRA_TOKEN is not configured")

    created: list[dict] = []
    for w in weeks:
        resp = httpx.post(
            f"{settings.JIRA_URL}/rest/api/2/issue",
            json={"fields": {
                "project":             {"key": "DMSC"},
                "issuetype":           {"id": "10001"},   # Story
                "priority":            {"id": "3"},        # Medium
                "summary":             f"On-Call Support Week {w['week']}",
                "description":         _ON_CALL_DESCRIPTION,
                "assignee":            {"name": w["assignee"]},
                "components":          [{"id": DMSC_COMPONENT_ID}],
                "customfield_10901":   _ON_CALL_ACCEPTANCE_CRITERIA,
            }},
            headers=_headers(),
            timeout=15,
            verify=True,
        )
        if not resp.is_success:
            raise RuntimeError(f"Jira {resp.status_code} creating on-call week {w['week']}: {resp.text[:400]}")
        key = resp.json()["key"]

        # Set story points (2) and epic link (DMSC-250) via PUT — these fields
        # are not accepted by the POST endpoint in this Jira version.
        patch = httpx.put(
            f"{settings.JIRA_URL}/rest/api/2/issue/{key}",
            json={"fields": {"customfield_10100": "DMSC-250", "customfield_10106": 2}},
            headers=_headers(),
            timeout=15,
            verify=True,
        )
        if not patch.is_success:
            logger.warning("Could not set epic/points on %s: %s", key, patch.text[:200])

        created.append({
            "key":      key,
            "url":      f"{settings.JIRA_URL}/browse/{key}",
            "week":     w["week"],
            "assignee": w["assignee"],
        })
        logger.info("Created on-call ticket %s (Week %s → %s)", key, w["week"], w["assignee"])

    if sprint_id:
        _add_to_sprint(sprint_id, [t["key"] for t in created])

    return created
