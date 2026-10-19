"""Notifications for admin role changes."""
from __future__ import annotations

import logging

from app.services.email_service import render_shell, send_html_email

logger = logging.getLogger(__name__)

_DASHBOARD_URL = "https://devops-dashboard.cloud.cms.gov"

_RESPONSIBILITIES = [
    "Promote or demote other engineers on the Admin page.",
    "Put the site into maintenance mode, which locks everyone else out.",
    "Override the monthly maintenance date, which moves every downstream flow "
    "including the prep tickets, the ITC and MGGD tickets and the reminder email.",
    "Read the audit log of every state-changing action the team takes.",
    "Upload the Slack directory used to resolve handles.",
]


def _promotion_html(display_name: str, promoted_by: str) -> str:
    items = "".join(
        f'<li style="margin-bottom:4px">{r}</li>' for r in _RESPONSIBILITIES
    )
    inner = (
        f'<p style="margin:0 0 10px">Hi {display_name},</p>'
        f'<p style="margin:0 0 10px">Your DevOps Dashboard account is now an '
        f'<strong>administrator</strong>, granted by <strong>{promoted_by}</strong>. '
        f'It takes effect on your next request, so reload the dashboard if you have it open.</p>'
        f'<p style="margin:0 0 6px">Admin access lets you:</p>'
        f'<ul style="margin:0 0 12px;padding-left:20px;font-size:14px">{items}</ul>'
        f'<p style="margin:0 0 12px">Every one of those actions is recorded in the audit '
        f'log against your name.</p>'
        f'<p style="margin:8px 0 0"><a href="{_DASHBOARD_URL}/admin" '
        f'style="background:#0b4f8a;color:#fff;text-decoration:none;padding:8px 14px;'
        f'border-radius:6px;font-size:13px">Open the Admin page</a></p>'
    )
    return render_shell("You are now a dashboard administrator", inner)


def send_promotion_notice(username: str, email: str, display_name: str, promoted_by: str) -> dict:
    """Tell a user they were promoted to admin. Best-effort: never raises."""
    if not email:
        logger.warning("No email on file for %s; skipping admin promotion notice", username)
        return {"sent": False, "error": "no email on file for this user"}
    try:
        return send_html_email(
            [email],
            "You are now a DevOps Dashboard administrator",
            _promotion_html(display_name or username, promoted_by),
        )
    except Exception as exc:  # noqa: BLE001 — a failed notice must not fail the promotion
        logger.error("Admin promotion notice to %s failed: %s", email, exc)
        return {"sent": False, "error": str(exc)}
