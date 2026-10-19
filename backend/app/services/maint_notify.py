"""Monthly-maintenance ticket notifications: readiness, reminder, confirmations.

- Reminder (13 days before maintenance): a daily loop calls ``reminder_tick()``;
  when today is exactly MAINT_REMINDER_DAYS before the next maintenance and a
  reminder has not already been sent for that date, an HTML reminder goes to the
  configured recipients (Patrick, Meghana, Max).
- Confirmations: the prep/ITC/MGGD create endpoints call ``send_confirmation``.
- Readiness: ``ticket_readiness()`` powers the notification bell.

All email is best-effort via email_service.send_html_email (never raises).
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date

from app.config import get_settings
from app.services.email_service import render_shell, send_html_email
from app.services.jira_service import get_next_maintenance_date, get_maint_prep_status

logger = logging.getLogger(__name__)

# The standard window as prose, for callers that want it without a lookup.
# Maintenance is the third Saturday (the Saturday of the third week) and runs
# 9 AM to 1 PM ET, so it no longer crosses midnight.
MAINT_WINDOW_LABEL = "9:00 AM – 1:00 PM ET"


def _window_label() -> str:
    """The window as prose, honoring an admin time override.

    A month whose window was moved has to say so in the email, otherwise the
    notice tells people a time the tickets contradict.
    """
    try:
        from app.services import maint_date_override
        w = maint_date_override.effective_window()
        return f"{_as_prose(w['start_time'])} – {_as_prose(w['end_time'])} ET"
    except Exception as exc:  # noqa: BLE001 — never fail an email over a label
        logger.warning("Could not resolve the maintenance window label: %s", exc)
        return MAINT_WINDOW_LABEL


def _as_prose(hhmm: str) -> str:
    """"09:00" -> "9:00 AM"."""
    from datetime import datetime
    return datetime.strptime(hhmm, "%H:%M").strftime("%-I:%M %p")


def _recipients() -> list[str]:
    """Everyone who should hear about maintenance tickets.

    The whole DevOps team, resolved from the maintenance roster through AD, plus
    anyone named in MAINT_NOTIFY_EMAILS who is not on it (the comms and
    management side). Deriving it from the roster means a joiner or leaver is
    picked up from one place instead of being missed because an env var was not
    updated.

    AD being unreachable falls back to the configured list, so a notice still
    goes out rather than going nowhere.
    """
    configured = [e.strip() for e in get_settings().MAINT_NOTIFY_EMAILS.split(",") if e.strip()]

    team: list[str] = []
    try:
        from app.services.jira_service import MAINT_TEAM_POOL
        from app.services import ldap_accounts
        euas = [m["username"] for m in MAINT_TEAM_POOL if m.get("username")]
        resolved = ldap_accounts.get_mail(euas)
        for eua in euas:
            mail = (resolved.get(eua.lower()) or {}).get("mail")
            if mail:
                team.append(mail)
            else:
                logger.warning("No AD mail for maintenance roster member %s", eua)
    except Exception as exc:  # noqa: BLE001 — never let a lookup stop the email
        logger.warning("Could not resolve the maintenance roster from AD: %s", exc)

    out: list[str] = []
    seen: set[str] = set()
    for addr in team + configured:
        key = addr.lower()
        if key not in seen:
            seen.add(key)
            out.append(addr)
    return out


# ─── Shared HTML shell (matches the pvc_cleanup inline-style look) ─────────────

_shell = render_shell


def ticket_readiness() -> dict:
    """Days until maintenance + whether it's time to create tickets (bell source)."""
    settings = get_settings()
    maint = get_next_maintenance_date()
    days_until = (maint - date.today()).days
    due = 0 <= days_until <= settings.MAINT_REMINDER_DAYS
    prep = {"all_created": False, "tools": {}}
    if due:
        try:
            prep = get_maint_prep_status(maint.strftime("%B %-d, %Y"))
        except Exception as exc:  # noqa: BLE001
            logger.warning("readiness prep lookup failed: %s", exc)
    return {
        "maint_date": maint.isoformat(),
        "maint_date_str": maint.strftime("%B %-d, %Y"),
        "days_until": days_until,
        "due": due,
        "prep_all_created": prep.get("all_created", False),
        "prep_tools": prep.get("tools", {}),
    }


def _reminder_html(r: dict) -> str:
    tools = r.get("prep_tools", {})
    rows = ""
    for tool, info in (tools or {}).items():
        state = f'✅ {info["key"]}' if info else "❌ not created"
        rows += (f'<tr><td style="padding:4px 10px;border-bottom:1px solid #eee">{tool}</td>'
                 f'<td style="padding:4px 10px;border-bottom:1px solid #eee">{state}</td></tr>')
    prep_tbl = (f'<table style="border-collapse:collapse;font-size:13px;margin:6px 0 12px">'
                f'<tr><th style="text-align:left;padding:4px 10px;border-bottom:2px solid #ddd">Tool</th>'
                f'<th style="text-align:left;padding:4px 10px;border-bottom:2px solid #ddd">Prep ticket</th></tr>'
                f'{rows}</table>') if rows else ""
    inner = (
        f'<p style="margin:0 0 10px">Monthly maintenance is on <strong>{r["maint_date_str"]}</strong>, '
        f'<strong>{_window_label()}</strong> '
        f'(<strong>{r["days_until"]} days</strong> away). It\'s time to create the maintenance tickets:</p>'
        f'<ol style="margin:0 0 12px;padding-left:20px">'
        f'<li>Create the <strong>tool Prep tickets</strong> (rotation-assigned, added to the covering sprint).</li>'
        f'<li>Then create the <strong>ITC</strong> and <strong>MGGD</strong> tickets (prep is a prerequisite).</li>'
        f'<li>Go/No-Go review is <strong>10 days before</strong> maintenance.</li></ol>'
        f'{prep_tbl}'
        f'<p style="margin:8px 0 0"><a href="https://devops-dashboard.cloud.cms.gov/jira" '
        f'style="background:#0b4f8a;color:#fff;text-decoration:none;padding:8px 14px;border-radius:6px;font-size:13px">'
        f'Open the dashboard</a></p>'
    )
    return _shell("Time to create the maintenance tickets", inner)


def send_reminder(test: bool = False) -> dict:
    r = ticket_readiness()
    subject = f'{"[TEST] " if test else ""}Action needed: create maintenance tickets for {r["maint_date_str"]}'
    return send_html_email(_recipients(), subject, _reminder_html(r))


def send_confirmation(kind: str, tickets: list[dict], maint_date_str: str) -> dict:
    """kind = 'Prep' | 'ITC' | 'MGGD'. tickets = [{key,url}]."""
    items = "".join(
        f'<li><a href="{t.get("url","")}">{t.get("key","")}</a>'
        f'{" — " + t["assignee_name"] if t.get("assignee_name") else ""}</li>'
        for t in tickets
    )
    inner = (
        f'<p style="margin:0 0 10px">The following <strong>{kind}</strong> ticket(s) were created for the '
        f'<strong>{maint_date_str}</strong> maintenance window '
        f'(<strong>{_window_label()}</strong>):</p>'
        f'<ul style="margin:0 0 8px;padding-left:20px">{items}</ul>'
    )
    subject = f'Created: {kind} ticket(s) for {maint_date_str} maintenance'
    return send_html_email(_recipients(), subject, _shell(f"{kind} ticket(s) created", inner))


# ─── Reminder scheduler tick (dedupe via state file) ──────────────────────────

def _load_state() -> dict:
    path = get_settings().MAINT_REMINDER_STATE_FILE
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return {}


def _save_state(state: dict) -> None:
    path = get_settings().MAINT_REMINDER_STATE_FILE
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w") as f:
            json.dump(state, f)
    except Exception as exc:  # noqa: BLE001
        logger.warning("could not persist reminder state: %s", exc)


def reminder_tick() -> None:
    """Called daily. Sends the reminder exactly once per maintenance date, when
    today is within MAINT_REMINDER_DAYS of it.

    Fires anywhere inside the window (0..N days out), not only on the exact Nth
    day, so a late-set maintenance-date override — or a missed daily tick / pod
    restart on the exact day — still triggers exactly one reminder. Dedup is by
    the maintenance date, so moving the date (e.g. an override) sends a fresh
    reminder for the new date."""
    settings = get_settings()
    maint = get_next_maintenance_date()
    days_until = (maint - date.today()).days
    if not (0 <= days_until <= settings.MAINT_REMINDER_DAYS):
        return
    key = maint.isoformat()
    state = _load_state()
    if state.get("last_reminder") == key:
        return
    res = send_reminder()
    if res.get("sent"):
        state["last_reminder"] = key
        _save_state(state)
        logger.info("Sent maintenance reminder for %s", key)
    else:
        logger.warning("Maintenance reminder send failed: %s", res.get("error"))
