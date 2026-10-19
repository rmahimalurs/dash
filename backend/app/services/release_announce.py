"""Announce a new dashboard release in Slack.

Posts a short summary of the current release to the team channel, once per
version. The marker is claimed before the message is sent and released again
if the send fails, so a restart retries rather than going quiet, and a second
replica coming up cannot post the same release twice.
"""
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from app.config import get_settings
from app.services import deployment, release_notes, slack

logger = logging.getLogger(__name__)

CHANNEL = "cms-cloud-devops-internal"
_DASHBOARD_URL = "https://devops-dashboard.cloud.cms.gov"

# Long enough to carry the point of a highlight, short enough that a release
# with six of them is still readable in a channel.
_BODY_LIMIT = 220


def _path() -> Path:
    return Path(get_settings().RELEASE_ANNOUNCE_STATE_FILE)


def read_state() -> dict:
    try:
        return json.loads(_path().read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _write_state(state: dict) -> None:
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + f".tmp.{os.getpid()}")
    tmp.write_text(json.dumps(state, indent=2))
    os.replace(tmp, p)


def _shorten(body: str) -> str:
    """The first sentence or two of a highlight, up to the body limit."""
    text = " ".join((body or "").split())
    if len(text) <= _BODY_LIMIT:
        return text
    # Prefer cutting at a sentence end so the summary does not read as truncated.
    window = text[:_BODY_LIMIT + 60]
    ends = [m.end() for m in re.finditer(r"[.!?](?:\s|$)", window) if m.end() <= _BODY_LIMIT + 40]
    if ends:
        return window[:ends[-1]].strip()
    return text[:_BODY_LIMIT].rsplit(" ", 1)[0] + "…"


def build_message(release: dict | None = None) -> str:
    """The Slack text for a release, in mrkdwn."""
    rel = release or release_notes.current_release()
    lines = [
        f":rocket: *DevOps Dashboard {rel['version']}* — {rel['title']}",
        f"_Released {rel['date']}_",
        "",
    ]
    for h in rel.get("highlights", []):
        lines.append(f"• *{h['title']}* — {_shorten(h.get('body', ''))}")
    lines += [
        "",
        f"<{_DASHBOARD_URL}|Open the dashboard> to see the full notes.",
    ]
    return "\n".join(lines)


def hold(version: str | None = None, by: str = "") -> dict:
    """Mark a version as deliberately not announced.

    Recorded rather than left to whoever is deploying to remember: a held
    version reads as held on the Admin card instead of looking like a post that
    already happened, and the next start will not announce it.
    """
    rel_version = version or release_notes.current_release()["version"]
    state = {
        "version": rel_version,
        "at": datetime.now(timezone.utc).isoformat(),
        "by": by or "held",
        "held": True,
    }
    _write_state(state)
    logger.info("Release %s marked as held, not announced", rel_version)
    return state


def announce(force: bool = False, by: str = "startup", allow_duplicate: bool = False) -> dict:
    """Post the current release to the team channel unless it already went out.

    Returns what happened, so a caller can report it without reading the log.
    """
    settings = get_settings()
    rel = release_notes.current_release()
    version = rel["version"]
    state = read_state()
    same_version = state.get("version") == version
    already_posted = same_version and not state.get("held")

    if not settings.RELEASE_ANNOUNCE_ENABLED:
        return {"posted": False, "version": version, "reason": "disabled"}

    if not force and same_version:
        return {
            "posted": False,
            "version": version,
            "reason": "held, not announced" if state.get("held") else "already announced",
            "at": state.get("at"),
            "by": state.get("by"),
            "held": bool(state.get("held")),
        }

    # force gets past "already announced", but not past a second copy of a post
    # that demonstrably landed. A release went out twice four minutes apart
    # because the startup post and a manual one each believed they were the
    # only one; the channel does not need telling twice.
    if force and already_posted and not allow_duplicate:
        return {
            "posted": False,
            "version": version,
            "reason": (
                f"already posted at {state.get('at')} by {state.get('by')}. "
                "Pass allow_duplicate to send a second copy anyway."
            ),
            "at": state.get("at"),
            "by": state.get("by"),
            "duplicate_blocked": True,
        }

    if not slack.webhook_url_for(CHANNEL) and not settings.SLACK_BOT_TOKEN:
        return {"posted": False, "version": version, "reason": "no Slack credentials"}

    message = build_message(rel)
    claim = {"version": version, "at": datetime.now(timezone.utc).isoformat(),
             "by": by, "held": False}
    _write_state(claim)

    if not slack.send_message(CHANNEL, message):
        # Put the marker back so the next start tries again instead of
        # believing the release was announced.
        if state:
            _write_state(state)
        else:
            _path().unlink(missing_ok=True)
        return {"posted": False, "version": version, "reason": "Slack rejected the message"}

    logger.info("Announced release %s in #%s", version, CHANNEL)
    return {"posted": True, "version": version, "at": claim["at"], "by": by, "message": message}
