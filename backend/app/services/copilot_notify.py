"""Nudges to Copilot seat holders who are not using the license they hold.

Built on the same pair the CloudBees ADO outreach uses — email_service for the
send and email_notices for the escalating subject prefix and the send history —
so a seat that gets nudged twice says "Second Notice" without this module
keeping its own counter.
"""
from __future__ import annotations

import logging

from app.services import email_notices
from app.services.email_service import render_shell, send_html_email

logger = logging.getLogger(__name__)

FLOW = "copilot_usage_nudge"

_DOCS_URL = "https://docs.github.com/copilot"


def _nudge_html(display_name: str, login: str, never_used: bool,
                idle_days: int | None, threshold: int, sender: str,
                ordinal: int) -> str:
    usage = (
        "our records show the seat has never been used since it was assigned"
        if never_used else
        f"the last activity we can see on it was {idle_days} days ago"
    )
    repeat = (
        f'<p style="margin:0 0 10px;color:#92400e"><strong>This is nudge '
        f'{ordinal}.</strong> The seat is still showing no activity.</p>'
        if ordinal > 1 else ""
    )
    inner = (
        f'<p style="margin:0 0 10px">Hi {display_name},</p>'
        f'{repeat}'
        f'<p style="margin:0 0 10px">You hold a GitHub Copilot license on the CMS enterprise '
        f'against the account <strong>{login}</strong>, and {usage}.</p>'
        f'<p style="margin:0 0 10px">CMS has licensed Copilot for everyone on the '
        f'enterprise, and the seat is already yours at no cost to your team, so there is '
        f'nothing to request and nothing to approve. We are flagging it only because a '
        f'paid-for seat sitting unused is a tool you could be getting value from.</p>'
        f'<p style="margin:0 0 12px">If you are not sure where to start, the guide below '
        f'covers code completion and chat in VS Code, Visual Studio, JetBrains and the '
        f'CLI. If something is blocking you from using it, reply and tell us what.</p>'
        f'<p style="margin:8px 0 0"><a href="{_DOCS_URL}" '
        f'style="background:#0b4f8a;color:#fff;text-decoration:none;padding:8px 14px;'
        f'border-radius:6px;font-size:13px">Getting started with Copilot</a></p>'
        f'<p style="margin:14px 0 0;font-size:12px;color:#666">Sent by {sender} via the '
        f'CMS Cloud DevOps dashboard.</p>'
    )
    return render_shell("You have a Copilot license you are not using", inner)


def send_usage_nudge(login: str, email: str, display_name: str, *,
                     never_used: bool, idle_days: int | None,
                     threshold: int, sender: str) -> dict:
    """Nudge one seat holder to start using the Copilot license they hold.

    Best-effort: a failed send is reported, never raised, so one bad address
    does not abort a batch.
    """
    if not email:
        return {"sent": False, "login": login,
                "error": "no email could be resolved for this login"}

    ordinal, prefix = email_notices.peek_next(FLOW, login)
    subject = f"{prefix}You have a GitHub Copilot license you are not using"
    try:
        res = send_html_email(
            [email],
            subject,
            _nudge_html(display_name or login, login, never_used, idle_days,
                        threshold, sender, ordinal),
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Copilot usage nudge to %s failed: %s", email, exc)
        return {"sent": False, "login": login, "email": email, "error": str(exc)[:200]}

    sent = bool(res.get("sent", True))
    if sent:
        email_notices.record(FLOW, login, to=[email], by=sender)
    return {"sent": sent, "login": login, "email": email, "ordinal": ordinal,
            "error": res.get("error")}


def reminder_history(logins: list[str]) -> dict[str, list[dict]]:
    """{login: [{sent_at, ordinal, to, by}]} so the tile can show prior nudges."""
    return {l: email_notices.history(FLOW, l) for l in logins}
