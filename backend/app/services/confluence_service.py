"""
Confluence REST API helpers for creating retrospective pages.

Two flows:
- create_maintenance_retro_page() — clones a maintenance retro skeleton under
  COM/Maintenance Retros, titled e.g. "February 14th Maintenance Retro",
  date sourced from the latest ITC DevOps Service Maintenance ticket.
- create_sprint_retro_page() — clones a sprint retro skeleton under
  COM/DevOps Sprint Retros, titled e.g. "07/13/26 - Sprint 34 Retro",
  date and number derived from the active DMSC sprint.

Both append a row to the parent page's child-listing table on success.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime
from typing import Optional

import httpx

from app.config import get_settings
from app.services.jira_service import _find_latest_maintenance_ticket, _get_issue_fields, get_dmsc_sprints

logger = logging.getLogger(__name__)


# ─── HTTP helpers ─────────────────────────────────────────────────────────────

def _headers() -> dict:
    token = get_settings().CONFLUENCE_TOKEN
    if not token:
        raise RuntimeError("CONFLUENCE_TOKEN is not configured")
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }


def _api(path: str) -> str:
    return f"{get_settings().CONFLUENCE_URL.rstrip('/')}{path}"


def _page_url(page_id: str, title: str) -> str:
    base = get_settings().CONFLUENCE_URL.rstrip("/")
    space = get_settings().CONFLUENCE_SPACE
    slug = title.replace(" ", "+")
    return f"{base}/spaces/{space}/pages/{page_id}/{slug}"


# ─── Date / title formatting ──────────────────────────────────────────────────

def _ordinal(day: int) -> str:
    if 10 <= (day % 100) <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return f"{day}{suffix}"


def _format_maint_title(d: date) -> str:
    return f"{d.strftime('%B')} {_ordinal(d.day)} Maintenance Retro"


def _format_sprint_title(end_date: date, sprint_num: int) -> str:
    # Match existing convention: MM/D/YY — day is not zero-padded.
    return f"{end_date.month:02d}/{end_date.day}/{end_date.strftime('%y')} - Sprint {sprint_num} Retro"


def _maint_description(d: date) -> str:
    return f"Post-maintenance retrospective for the {d.strftime('%B')} {_ordinal(d.day)} maintenance window."


# ─── Date sourcing ────────────────────────────────────────────────────────────

_ITC_SUMMARY_DATE_RE = re.compile(r"(\d{2})-(\d{2})-(\d{4})")


def get_latest_itc_maintenance_date() -> date:
    """Return the maintenance date of the most recent ITC DevOps Service Maintenance ticket."""
    template_key = _find_latest_maintenance_ticket()
    fields = _get_issue_fields(template_key)

    # Prefer the Maintenance start custom field (ISO datetime)
    start_iso = fields.get("customfield_12809")
    if start_iso:
        try:
            return datetime.fromisoformat(start_iso.replace("Z", "+00:00")).date()
        except ValueError:
            pass

    summary = fields.get("summary", "") or ""
    m = _ITC_SUMMARY_DATE_RE.search(summary)
    if not m:
        raise RuntimeError(f"Could not parse maintenance date from ITC ticket summary: {summary!r}")
    month, day, year = (int(g) for g in m.groups())
    return date(year, month, day)


def get_current_sprint_end() -> tuple[date, int]:
    """
    Return (end_date, sprint_number) for the active DMSC sprint.
    Raises if no active sprint or sprint name lacks a trailing number.
    """
    sprints = get_dmsc_sprints()
    active = next((s for s in sprints if s["state"] == "active"), None)
    if not active:
        raise RuntimeError("No active DMSC sprint found")

    end_iso = active.get("endDate")
    if not end_iso:
        raise RuntimeError(f"Active sprint {active.get('name')} has no endDate")
    end_date = datetime.fromisoformat(end_iso.replace("Z", "+00:00")).date()

    m = re.search(r"(\d+)$", active.get("name", ""))
    if not m:
        raise RuntimeError(f"Could not parse sprint number from name: {active.get('name')!r}")
    return end_date, int(m.group(1))


# ─── Page templates (Confluence storage format) ───────────────────────────────

_MAINT_RETRO_TEMPLATE = """\
<p>Tasks completed:</p>
<ol><li> </li></ol>
<p><br /></p>
<table class="wrapped relative-table" style="width: 93.9498%;">
<colgroup><col style="width: 27.9625%;" /><col style="width: 26.2604%;" /><col style="width: 26.2604%;" /><col style="width: 26.2604%;" /></colgroup>
<tbody>
<tr>
<th scope="col">What went well?</th>
<th scope="col">What went wrong?</th>
<th scope="col">What we learned?</th>
<th scope="col">Action items</th>
</tr>
<tr>
<td><div class="content-wrapper"><ul><li> </li></ul></div></td>
<td><div class="content-wrapper"><ul><li> </li></ul></div></td>
<td><div class="content-wrapper"><ul><li> </li></ul></div></td>
<td><div class="content-wrapper"><ul><li> </li></ul></div></td>
</tr>
</tbody>
</table>
<p><br /></p>
"""


_SPRINT_RETRO_TEMPLATE = """\
<table class="wrapped"><colgroup><col /></colgroup>
<tbody>
<tr><th scope="col">Explain in one Gif Your Work Week? <a href="https://giphy.com/">https://giphy.com/</a></th></tr>
<tr><td><div class="content-wrapper"><p><br /></p></div></td></tr>
</tbody>
</table>
<p><br /></p>
<table class="wrapped relative-table" style="width: 100.0%;">
<colgroup><col style="width: 33.3%;" /><col style="width: 33.3%;" /><col style="width: 33.4%;" /></colgroup>
<tbody>
<tr>
<th scope="col">What Went Well?</th>
<th scope="col">What have you learned?</th>
<th scope="col">What we can improve (Action Items)</th>
</tr>
<tr>
<td><div class="content-wrapper"><ul><li> </li></ul></div></td>
<td><div class="content-wrapper"><ul><li> </li></ul></div></td>
<td><div class="content-wrapper"><ul><li> </li></ul></div></td>
</tr>
</tbody>
</table>
<p>Links to Dashboards, Achievements, etc...</p>
<ol>
<li>Cloud Support Dashboard: <a href="https://jiraent.cms.gov/secure/Dashboard.jspa?selectPageId=78500">https://jiraent.cms.gov/secure/Dashboard.jspa?selectPageId=78500</a></li>
</ol>
<h3><strong>Closing Notes:</strong></h3>
<p><br /></p>
"""


# ─── Confluence REST ──────────────────────────────────────────────────────────

def _find_page_by_title(title: str) -> Optional[dict]:
    """Return {'id', 'title', 'url'} if a page with this exact title exists in the space, else None."""
    settings = get_settings()
    resp = httpx.get(
        _api("/rest/api/content"),
        params={
            "spaceKey": settings.CONFLUENCE_SPACE,
            "title": title,
            "type": "page",
            "limit": 1,
        },
        headers=_headers(),
        timeout=20,
        verify=True,
    )
    resp.raise_for_status()
    results = resp.json().get("results", [])
    if not results:
        return None
    page = results[0]
    return {"id": page["id"], "title": page["title"], "url": _page_url(page["id"], page["title"])}


def _get_page_with_body(page_id: str) -> dict:
    """Fetch a page with storage-format body and version."""
    resp = httpx.get(
        _api(f"/rest/api/content/{page_id}"),
        params={"expand": "body.storage,version,space"},
        headers=_headers(),
        timeout=20,
        verify=True,
    )
    resp.raise_for_status()
    return resp.json()


def _create_child_page(parent_id: str, title: str, body_storage: str) -> dict:
    """Create a child page under parent_id. Returns the new page dict."""
    settings = get_settings()
    payload = {
        "type": "page",
        "title": title,
        "space": {"key": settings.CONFLUENCE_SPACE},
        "ancestors": [{"id": parent_id}],
        "body": {"storage": {"value": body_storage, "representation": "storage"}},
    }
    resp = httpx.post(
        _api("/rest/api/content"),
        json=payload,
        headers=_headers(),
        timeout=30,
        verify=True,
    )
    if not resp.is_success:
        raise RuntimeError(f"Confluence {resp.status_code} creating page {title!r}: {resp.text[:600]}")
    return resp.json()


def _update_page(page_id: str, new_version: int, title: str, body_storage: str,
                 space_key: str | None = None) -> None:
    """Update a page's body. Requires next version number.

    ``space`` is intentionally omitted from the payload unless ``space_key`` is
    given — Confluence keeps the page in its current space, and sending a space
    that differs from the page's own space 400s with "You can't change an
    existing page's space." (This matters for pages outside the default COM space,
    e.g. the OE readiness pages in OEC.)
    """
    payload = {
        "id": page_id,
        "type": "page",
        "title": title,
        "version": {"number": new_version},
        "body": {"storage": {"value": body_storage, "representation": "storage"}},
    }
    if space_key:
        payload["space"] = {"key": space_key}
    resp = httpx.put(
        _api(f"/rest/api/content/{page_id}"),
        json=payload,
        headers=_headers(),
        timeout=30,
        verify=True,
    )
    if not resp.is_success:
        raise RuntimeError(f"Confluence {resp.status_code} updating page {page_id}: {resp.text[:600]}")


_TBODY_CLOSE_RE = re.compile(r"</tbody>", re.IGNORECASE)


def _append_row_to_parent_table(parent_id: str, child_title: str, description: str) -> None:
    """
    Append a new <tr> linking to child_title with the given description to the
    parent page's child-listing table. Best-effort: if the table can't be found,
    log a warning and continue.
    """
    try:
        page = _get_page_with_body(parent_id)
        title = page["title"]
        version = page["version"]["number"]
        body = page["body"]["storage"]["value"]

        new_row = (
            f'<tr><td><ac:link><ri:page ri:content-title="{child_title}" /></ac:link></td>'
            f'<td>{description}</td></tr>'
        )

        if "</tbody>" not in body.lower():
            logger.warning("Parent page %s has no <tbody> — skipping table update", parent_id)
            return

        new_body = _TBODY_CLOSE_RE.sub(new_row + "</tbody>", body, count=1)
        _update_page(parent_id, version + 1, title, new_body)
        logger.info("Appended row for %r to parent %s", child_title, parent_id)
    except Exception as exc:
        logger.warning("Could not update parent page %s table: %s", parent_id, exc)


# ─── Public flows ─────────────────────────────────────────────────────────────

def preview_retro_titles() -> dict:
    """Return the titles the two retro widgets would create without creating anything."""
    maint_info: dict = {}
    sprint_info: dict = {}

    try:
        d = get_latest_itc_maintenance_date()
        title = _format_maint_title(d)
        existing = _find_page_by_title(title)
        maint_info = {
            "date": d.isoformat(),
            "title": title,
            "already_exists": existing is not None,
            "existing_url": existing["url"] if existing else None,
        }
    except Exception as exc:
        maint_info = {"error": str(exc)}

    try:
        end_date, sprint_num = get_current_sprint_end()
        title = _format_sprint_title(end_date, sprint_num)
        existing = _find_page_by_title(title)
        sprint_info = {
            "end_date": end_date.isoformat(),
            "sprint_number": sprint_num,
            "title": title,
            "already_exists": existing is not None,
            "existing_url": existing["url"] if existing else None,
        }
    except Exception as exc:
        sprint_info = {"error": str(exc)}

    return {"maintenance": maint_info, "sprint": sprint_info}


def create_maintenance_retro_page() -> dict:
    """
    Create a maintenance retro page under the configured parent, titled from the
    latest ITC maintenance date. Returns:
      {created: bool, title, url, already_existed: bool, source_date}
    """
    settings = get_settings()
    d = get_latest_itc_maintenance_date()
    title = _format_maint_title(d)
    parent_id = settings.CONFLUENCE_MAINT_RETRO_PARENT_ID

    existing = _find_page_by_title(title)
    if existing:
        return {
            "created": False,
            "already_existed": True,
            "title": title,
            "url": existing["url"],
            "source_date": d.isoformat(),
        }

    new_page = _create_child_page(parent_id, title, _MAINT_RETRO_TEMPLATE)
    new_url = _page_url(new_page["id"], title)
    _append_row_to_parent_table(parent_id, title, _maint_description(d))

    return {
        "created": True,
        "already_existed": False,
        "title": title,
        "url": new_url,
        "source_date": d.isoformat(),
    }


def create_sprint_retro_page() -> dict:
    """
    Create a sprint retro page under the configured parent, titled from the
    active DMSC sprint's end date and number.
    """
    settings = get_settings()
    end_date, sprint_num = get_current_sprint_end()
    title = _format_sprint_title(end_date, sprint_num)
    parent_id = settings.CONFLUENCE_SPRINT_RETRO_PARENT_ID

    existing = _find_page_by_title(title)
    if existing:
        return {
            "created": False,
            "already_existed": True,
            "title": title,
            "url": existing["url"],
            "sprint_number": sprint_num,
            "end_date": end_date.isoformat(),
        }

    new_page = _create_child_page(parent_id, title, _SPRINT_RETRO_TEMPLATE)
    new_url = _page_url(new_page["id"], title)
    _append_row_to_parent_table(parent_id, title, "Sprint retrospective notes.")

    return {
        "created": True,
        "already_existed": False,
        "title": title,
        "url": new_url,
        "sprint_number": sprint_num,
        "end_date": end_date.isoformat(),
    }
