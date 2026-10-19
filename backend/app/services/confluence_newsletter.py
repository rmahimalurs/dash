"""Append the DevOps maintenance change to the weekly change newsletter in COC.

The Hybrid Cloud team publishes a "YYYY-M-D Weekly change newsletter" page in the
COC space each week; it is a sequence of ``<h2>Change N</h2>`` headings each
followed by a table (Author / "Change record ticket:" / Content). This module
finds the current week's page, computes the next Change number, and surgically
appends our maintenance change (with the ITC link) WITHOUT touching the rest of
the page's storage format ([[feedback_confluence_update_format]]).

Default is dry-run: it returns the proposed section + next version so it can be
reviewed before any live PUT.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime

import httpx

from app.config import get_settings
from app.services.confluence_service import _headers, _api, _get_page_with_body

logger = logging.getLogger(__name__)

_NEWSLETTER_SPACE = "COC"
_NEWSLETTER_TITLE_MATCH = "Weekly change newsletter"


def _title_date(title: str) -> date | None:
    """Parse the leading 'YYYY-M-D' from a newsletter title."""
    m = re.match(r"\s*(\d{4})-(\d{1,2})-(\d{1,2})", title or "")
    return date(int(m[1]), int(m[2]), int(m[3])) if m else None


def find_newsletter_page(maint_date: date | None = None, window_days: int = 12) -> dict | None:
    """Find the weekly COC newsletter page for a maintenance window.

    The newsletter is published a few days before each Saturday maintenance
    (e.g. maint 8/15 -> "2026-8-13" page). Given ``maint_date``, pick the page
    whose title date is on-or-before it and closest (within ``window_days``);
    fall back to the nearest by absolute distance. Without a date, the latest.
    """
    cql = f'space="{_NEWSLETTER_SPACE}" AND type=page AND title~"{_NEWSLETTER_TITLE_MATCH}"'
    resp = httpx.get(
        _api("/rest/api/content/search"),
        params={"cql": cql, "limit": 30, "expand": "version"},
        headers=_headers(), timeout=20, verify=True,
    )
    resp.raise_for_status()
    dated = [(p, _title_date(p.get("title", ""))) for p in resp.json().get("results", [])]
    dated = [(p, d) for p, d in dated if d]
    if not dated:
        return None
    if maint_date is not None:
        on_before = [(p, d) for p, d in dated if d <= maint_date and (maint_date - d).days <= window_days]
        chosen = max(on_before, key=lambda x: x[1]) if on_before \
            else min(dated, key=lambda x: abs((x[1] - maint_date).days))
    else:
        chosen = max(dated, key=lambda x: x[1])
    p = chosen[0]
    return {"id": p["id"], "title": p["title"]}


# A slot nobody has filled still carries the template's author prompt.
_BLANK_MARKER = "@-mention your name"

# Every placeholder the blank slot ships with, and what replaces it. Each one
# MUST match exactly once, so a template edit upstream fails loudly instead of
# half-filling a slot and leaving instructions in a customer-facing notice.
_SUBJECT_PH = "<p>(Summary of change on date)</p>"
_SUMMARY_PH = ("<p>(Explain in 1-2 sentences what is happening. eg. Maintenance on x tools "
               "for upgrade to v.1.x)</p>")
_ACTIONS_PH = ("<p><strong>(</strong>Provide a list or summary of what you are doing as part of "
               "this maintenance or change. eg. During this time, CMS Cloud will update service "
               "xx to the latest version; CMS Cloud will be adding additional clusters to its "
               "environments for xxx). </p>")
_WHEN_PH = "<p>(Day, Monday, date, year from hour:00 a.m./p.m. - hour:00 a.m./p.m. ET) </p>"
_WHO_PH = ("<p>(Specifically note which customers will be impacted by the change or maintenance. "
           "eg. All AWS Commercial accounts; all customers using xxx tool)</p>")
_IMPACT_BLANK_PH = ("<p>________ customers may experience an outage of ________ within "
                    "_____________ environments. </p>")
_IMPACT_HINT_PH = ("<p>(Explain any outages or delays in service and list timeframe. Note other "
                   "impacts on customers. eg. Customers should expect a brief outage of no more "
                   "than two minutes; Customers should expect no outage of service but could see "
                   "a brief downgrade in performance. )</p>")
_BENEFITS_PH = ("<p>(Upon completion, customers should realize decreased costs; This change will "
                "provide increased security.)</p>")
_VALIDATION_PH = ("<p><strong><span>Validation:</span></strong><span> (Day of week, DD/MM/YYYY, "
                  "Start time - End time) <br /><strong>Meeting ID:</strong> ()         "
                  "<strong>Passcode:</strong> ()</span></p>")
_CONTACT_PH = "<p><span>For Questions / Concerns contact (provide contact email)</span></p>"

IMPACTED = "CMS Cloud - JFrog Artifactory/Xray, CloudBees Jenkins, SonarQube"

# Whoever the change is filed under. The page wants a real mention, not a name.
_DEFAULT_AUTHOR_USERKEY = "8a72538b948993e101948ace82e00005"   # Rahimi, Masood (RWRW)
CONTACT_EMAIL = "CMS_Cloud_DevOps@cms.hhs.gov"


def find_blank_slot(storage: str) -> tuple[int, int, int] | None:
    """(change number, start offset, end offset) of the first unfilled slot.

    The page ships with several blank Change slots after the filled ones. A new
    change fills the next blank one in place; appending a section instead puts
    it past "Step 3" at the end of the document, where it is not a change entry
    at all.
    """
    heads = [(m.start(), int(m.group(1)))
             for m in re.finditer(r"<h2[^>]*>\s*Change\s+(\d+)\s*</h2>", storage)]
    for i, (pos, num) in enumerate(heads):
        end = heads[i + 1][0] if i + 1 < len(heads) else len(storage)
        if _BLANK_MARKER in storage[pos:end]:
            return num, pos, end
    return None


def _fmt_when(iso: str) -> str:
    try:
        dt = datetime.strptime(iso.split(".")[0], "%Y-%m-%dT%H:%M:%S")
        return dt.strftime("%A, %-m/%-d/%Y at %-I:%M %p ET")
    except Exception:
        return iso


def fill_slot_html(slot: str, itc_key: str, maint_date_mdy: str, start_dt: str,
                   end_dt: str, tool_bullets: list[str], author_userkey: str) -> str:
    """Substitute the template's placeholders inside one slot, nothing else.

    Only the placeholder text is replaced. Every heading, table row, class and
    style the template defines is left byte-identical, so the page keeps the
    shape Change Management reviews against.
    """
    s = get_settings()
    out = slot

    def sub(placeholder: str, replacement: str, what: str) -> None:
        """Replace one placeholder, tolerating the template's own whitespace.

        Confluence stores non-breaking spaces throughout these placeholders, so
        matching them literally fails on spacing rather than on content. Any
        whitespace run matches any other; everything else must match exactly,
        and it must match exactly once.
        """
        nonlocal out
        tokens = [re.escape(t) for t in re.split(r"[\s\u00a0]+", placeholder) if t]
        pattern = r"[\s\u00a0]*".join(tokens)
        out, n = re.subn(pattern, lambda _: replacement, out, count=1)
        if n != 1:
            raise RuntimeError(
                f"Newsletter template changed: could not find the {what} placeholder. "
                "Refusing to edit the page."
            )

    # Author: the page uses a real user mention, not a name in text.
    sub(f">{_BLANK_MARKER}</td>",
        f'><ac:link><ri:user ri:userkey="{author_userkey}" /></ac:link></td>',
        "author")

    # Ticket: the page uses the Jira macro so the status renders inline.
    sub(
        ">ITC- </td>",
        '><div class="content-wrapper"><p><ac:structured-macro ac:name="jira" '
        'ac:schema-version="1"><ac:parameter ac:name="server">Enterprise JIRA</ac:parameter>'
        f'<ac:parameter ac:name="key">{itc_key}</ac:parameter>'
        "</ac:structured-macro></p></div></td>",
        "change record ticket",
    )

    sub(_SUBJECT_PH, f"<p>{maint_date_mdy} - DevOps Services Maintenance</p>", "subject")
    sub(_SUMMARY_PH,
        "<p>The CMS Hybrid Cloud DevOps team will perform scheduled maintenance on its "
        f"DevOps tooling on {maint_date_mdy}. Each tool is upgraded and validated within "
        "the maintenance window.</p>",
        "summary")
    bullets = "".join(f"<li>{b}</li>" for b in tool_bullets)
    sub(_ACTIONS_PH, f"<ul>{bullets}</ul>", "actions")
    sub(_WHEN_PH,
        f"<p>Start Time: {_fmt_when(start_dt)}</p><p>End Time: {_fmt_when(end_dt)}</p>",
        "when")
    sub(_WHO_PH, f"<p>{IMPACTED}</p>", "who")
    sub(_IMPACT_BLANK_PH,
        f"<p>Customers using {IMPACTED} may experience an outage for the duration of the "
        "maintenance window within all environments. </p>",
        "impact")
    sub(_IMPACT_HINT_PH,
        "<p>These tools are unavailable while each upgrade is applied. No other CMS Cloud "
        "service is affected, and no customer action is required.</p>",
        "impact detail")
    sub(_BENEFITS_PH,
        "<p>Upon completion, customers receive the latest security patches and bug fixes "
        "for each tool.</p>",
        "benefits")
    sub(_VALIDATION_PH,
        "<p><strong><span>Validation:</span></strong><span> No validation bridge is required "
        "for this change.</span></p>",
        "validation bridge")
    sub(_CONTACT_PH,
        f"<p><span>For Questions / Concerns contact {CONTACT_EMAIL}</span></p>",
        "contact")
    return out


def append_maintenance_change(
    itc_key: str,
    maint_date_mdy: str,       # "M/D/YYYY"
    start_dt: str, end_dt: str,
    tool_bullets: list[str],
    page_id: str | None = None,
    dry_run: bool = True,
    author_userkey: str = "",
) -> dict:
    """Fill the next blank Change slot on the weekly newsletter.

    The page ships with blank slots carrying the template's instructions. This
    fills the first one in place and replaces only placeholder text; it never
    appends a section, which would land after "Step 3" where it is not a change
    entry, and it never rewrites the template's own markup.

    dry_run=True (default) returns the proposed slot without modifying anything.
    """
    if page_id:
        page = {"id": page_id}
    else:
        try:
            md = datetime.strptime(maint_date_mdy, "%m/%d/%Y").date()
        except Exception:
            md = None
        page = find_newsletter_page(md)
    if not page:
        raise RuntimeError("Could not find a COC weekly change newsletter page for this maintenance week")
    full = _get_page_with_body(page["id"])
    storage = full["body"]["storage"]["value"]
    title = full["title"]
    space_key = full.get("space", {}).get("key", _NEWSLETTER_SPACE)
    version = full["version"]["number"]
    base = get_settings().CONFLUENCE_URL.rstrip("/")
    url = f"{base}/spaces/{space_key}/pages/{page['id']}/{title.replace(' ', '+')}"

    slot = find_blank_slot(storage)
    if slot is None:
        raise RuntimeError(
            "No blank Change slot left on this newsletter page. Ask Change Management to "
            "add one rather than appending a section, which lands outside the change list."
        )
    n, slot_start, slot_end = slot
    filled = fill_slot_html(
        storage[slot_start:slot_end], itc_key, maint_date_mdy, start_dt, end_dt,
        tool_bullets, author_userkey or _DEFAULT_AUTHOR_USERKEY,
    )
    new_storage = storage[:slot_start] + filled + storage[slot_end:]

    # Everything outside the slot has to be untouched.
    if new_storage[:slot_start] != storage[:slot_start] or \
       new_storage[slot_start + len(filled):] != storage[slot_end:]:
        raise RuntimeError("Refusing to save: the edit reached outside the Change slot.")

    result = {
        "page_id": page["id"], "title": title, "space": space_key,
        "change_number": n, "current_version": version,
        "url": url,
        "section_preview": filled, "dry_run": dry_run,
    }
    if dry_run:
        return result

    payload = {
        "id": page["id"], "type": "page", "title": title,
        "space": {"key": space_key},
        "version": {"number": version + 1},
        "body": {"storage": {"value": new_storage, "representation": "storage"}},
    }
    resp = httpx.put(_api(f"/rest/api/content/{page['id']}"), json=payload,
                     headers=_headers(), timeout=30, verify=True)
    if not resp.is_success:
        raise RuntimeError(f"Confluence {resp.status_code} updating newsletter: {resp.text[:400]}")
    result["new_version"] = version + 1
    return result
