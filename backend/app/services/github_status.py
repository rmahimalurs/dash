"""GitHub's own service health (githubstatus.com), with a Slack alert on change.

githubstatus.com is a public, unauthenticated Atlassian Statuspage feed — no
GitHub credentials involved, and nothing here reads or writes anything of
ours. Two independent uses of the same feed:

1. A live read (current_status) for the dashboard banner on the GitHub page.
2. A background tick (status_alert_tick), called every 5 minutes from
   app.main's lifespan loop, that posts to Slack #cms-cloud-devops-internal
   exactly twice per incident — once when the page goes from all-clear to
   degraded, once when it comes back — not per component and not on every
   tick, so a sustained or multi-component outage doesn't spam the channel.
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone

import httpx

from app.services import slack

logger = logging.getLogger(__name__)

_SUMMARY_URL = "https://www.githubstatus.com/api/v2/summary.json"
_CACHE_TTL = 60

# "showcase" is false only on the one placeholder entry ("Visit
# www.githubstatus.com for more information") that isn't a real component.
_STATUS_LABELS = {
    "operational": "Operational",
    "degraded_performance": "Degraded performance",
    "partial_outage": "Partial outage",
    "major_outage": "Major outage",
}

_cache: tuple[float, dict] | None = None


def _fetch_summary() -> dict:
    resp = httpx.get(_SUMMARY_URL, timeout=15.0)
    resp.raise_for_status()
    return resp.json()


def _components(summary: dict) -> list[dict]:
    return [c for c in (summary.get("components") or []) if c.get("showcase")]


def current_status() -> dict:
    """Live-ish read for the dashboard banner. Cached briefly so the widget
    polling every few seconds doesn't hit githubstatus.com that often."""
    global _cache
    if _cache and (time.time() - _cache[0]) < _CACHE_TTL:
        return _cache[1]

    try:
        summary = _fetch_summary()
    except Exception as exc:  # noqa: BLE001
        logger.warning("GitHub status fetch failed: %s", exc)
        return {"error": str(exc)[:200], "indicator": "unknown", "components": [], "incidents": []}

    components = [
        {
            "name": c["name"],
            "status": c["status"],
            "label": _STATUS_LABELS.get(c["status"], c["status"]),
        }
        for c in _components(summary)
    ]
    incidents = [
        {
            "name": i.get("name"),
            "status": i.get("status"),
            "impact": i.get("impact"),
            "shortlink": i.get("shortlink"),
            "updated_at": i.get("updated_at"),
        }
        for i in (summary.get("incidents") or [])
    ]
    page_status = summary.get("status") or {}

    result = {
        "indicator": page_status.get("indicator", "none"),
        "description": page_status.get("description", "All Systems Operational"),
        "components": components,
        "degraded": [c for c in components if c["status"] != "operational"],
        "incidents": incidents,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "url": "https://www.githubstatus.com",
        "error": None,
    }
    _cache = (time.time(), result)
    return result


def _load_state(path: str) -> dict:
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return {}


def _save_state(path: str, state: dict) -> None:
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w") as f:
            json.dump(state, f)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not persist github-status alert state: %s", exc)


def _down_alert_blocks(description: str, degraded: list[dict]) -> tuple[str, list]:
    headline = f"🔴 GitHub: {description}"
    affected = ", ".join(f"{c['name']} ({_STATUS_LABELS.get(c['status'], c['status'])})" for c in degraded)
    text = headline
    blocks = [
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*{headline}*"}},
        {
            "type": "context",
            "elements": [{
                "type": "mrkdwn",
                "text": f"{affected or 'See githubstatus.com for details'} · "
                        f"<https://www.githubstatus.com|githubstatus.com>",
            }],
        },
    ]
    return text, blocks


def _recovery_alert_blocks() -> tuple[str, list]:
    headline = "🟢 GitHub: All Systems Operational"
    text = headline
    blocks = [
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*{headline}*"}},
        {
            "type": "context",
            "elements": [{
                "type": "mrkdwn",
                "text": f"Back to normal · <https://www.githubstatus.com|githubstatus.com>",
            }],
        },
    ]
    return text, blocks


def status_alert_tick(settings) -> None:
    """Called every 5 minutes. Posts to Slack exactly twice per incident:
    once when the overall status moves off "all clear", once when it comes
    back — regardless of how many individual components flap in between, so
    a multi-component outage doesn't turn into a burst of pings."""
    state_path = settings.GITHUB_STATUS_STATE_FILE
    state = _load_state(state_path)
    prev_indicator = state.get("indicator", "none")

    try:
        summary = _fetch_summary()
    except Exception as exc:  # noqa: BLE001
        logger.warning("GitHub status alert tick failed: %s", exc)
        return

    page_status = summary.get("status") or {}
    indicator = page_status.get("indicator", "none")
    description = page_status.get("description", "All Systems Operational")
    degraded = [c for c in _components(summary) if c["status"] != "operational"]

    was_down = prev_indicator != "none"
    is_down = indicator != "none"

    # If there's a transition to report, only record it once Slack actually
    # accepted the message -- saving it unconditionally would mean a Slack
    # hiccup during the one tick that mattered permanently loses that alert,
    # since every later tick would see prev == current and see no transition.
    saved_indicator = indicator
    if is_down and not was_down:
        text, blocks = _down_alert_blocks(description, degraded)
        sent = slack.send_message("cms-cloud-devops-internal", text, blocks)
        logger.info("GitHub status down: %s (slack sent=%s)", description, sent)
        if not sent:
            saved_indicator = prev_indicator
    elif was_down and not is_down:
        text, blocks = _recovery_alert_blocks()
        sent = slack.send_message("cms-cloud-devops-internal", text, blocks)
        logger.info("GitHub status recovered (slack sent=%s)", sent)
        if not sent:
            saved_indicator = prev_indicator

    _save_state(state_path, {"indicator": saved_indicator, "checked_at": datetime.now(timezone.utc).isoformat()})
