"""Posting to Slack.

Two delivery paths, tried in order:

1. An incoming webhook URL for the channel. This is what CMS Slack
   administration issues; they do not hand out bot tokens. A webhook is bound to
   the channel it was created for, so there is one URL per channel and the
   channel in the payload is ignored.
2. chat.postMessage with a bot token, kept for any environment that has one.

Neither configured is not an error. The caller is told so and falls back to
putting the text on the clipboard for somebody to paste.
"""
import logging

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

_SLACK_API_BASE = "https://slack.com/api"

# Channel name to the setting holding its webhook URL.
_WEBHOOK_SETTINGS: dict[str, str] = {
    "github-access-approvals-internal": "SLACK_WEBHOOK_APPROVALS",
    "cms-cloud-devops-internal": "SLACK_WEBHOOK_TEAM",
}


def webhook_url_for(channel: str) -> str:
    setting = _WEBHOOK_SETTINGS.get(channel.lstrip("#"))
    return getattr(get_settings(), setting, "") if setting else ""


def _headers() -> dict[str, str]:
    settings = get_settings()
    return {
        "Authorization": f"Bearer {settings.SLACK_BOT_TOKEN}",
        "Content-Type": "application/json; charset=utf-8",
    }


def _post_webhook(url: str, channel: str, payload: dict) -> bool:
    try:
        with httpx.Client(timeout=10) as client:
            resp = client.post(url, json=payload)
    except httpx.RequestError as exc:
        logger.error("HTTP error posting the webhook for #%s: %s", channel, exc)
        return False

    # A webhook answers with "ok" as plain text, not JSON, so the body is read
    # as text; calling .json() on it would raise on the success case.
    body = (resp.text or "").strip()
    if resp.status_code != 200 or body.lower() != "ok":
        logger.error("Slack webhook for #%s returned %s: %s",
                     channel, resp.status_code, body[:200])
        return False
    logger.info("Slack message delivered to #%s by webhook", channel)
    return True


def send_message(channel: str, text: str, blocks: list | None = None) -> bool:
    """
    Send a message to a Slack channel.

    channel - Channel name (without #) or channel ID. With a webhook this only
              selects the URL; the channel is fixed when the webhook is made.
    text    - Plain-text fallback message.
    blocks  - Optional list of Block Kit block dicts for rich formatting.

    Returns True when Slack accepted it, False when it was not sent at all.
    """
    payload: dict = {"text": text}
    if blocks:
        payload["blocks"] = blocks

    url = webhook_url_for(channel)
    if url:
        return _post_webhook(url, channel, payload)

    settings = get_settings()
    if not settings.SLACK_BOT_TOKEN:
        logger.warning(
            "No webhook URL or bot token for #%s; skipping the Slack message", channel)
        return False

    try:
        with httpx.Client(timeout=10) as client:
            resp = client.post(
                f"{_SLACK_API_BASE}/chat.postMessage",
                json={**payload, "channel": channel},
                headers=_headers(),
            )
        data = resp.json()
        if not data.get("ok"):
            logger.error("Slack API error sending to #%s: %s", channel, data.get("error"))
            return False
        logger.info("Slack message sent to #%s (ts=%s)", channel, data.get("ts"))
        return True
    except httpx.RequestError as exc:
        logger.error("HTTP error sending Slack message to #%s: %s", channel, exc)
        return False


def notify_maintenance_complete(tool: str, env: str, jenkins_url: str) -> bool:
    """
    Send a rich Slack notification indicating that a maintenance job has completed.

    Sends to the #cms-cloud-devops-internal channel with a structured Block Kit message.
    """
    channel = "cms-cloud-devops-internal"
    text = f"Maintenance complete: {tool} {env}"

    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"Maintenance Complete: {tool} ({env})",
                "emoji": False,
            },
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Tool:*\n{tool}"},
                {"type": "mrkdwn", "text": f"*Environment:*\n{env}"},
            ],
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Jenkins Build:*\n<{jenkins_url}|View Build>",
            },
        },
        {"type": "divider"},
    ]

    return send_message(channel=channel, text=text, blocks=blocks)
