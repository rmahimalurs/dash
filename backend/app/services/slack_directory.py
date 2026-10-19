"""
Slim Slack directory (email -> handle) staged on EFS.

The dashboard backend cannot run `slack-cli` itself — that tool authenticates
with a browser session token (xoxc/xoxd) that only exists on an engineer's
laptop. So an admin uploads the local `slack-cli` users cache (or an
already-slim map) through the admin endpoint; we trim it to just what we need
and persist it to `SLACK_DIRECTORY_FILE` on the shared EFS volume.

Used by the controller-PVC cleanup flow to turn an ADO's Jenkins email address
into a Slack @handle the engineer can message for sign-off.
"""
import json
import logging
from pathlib import Path

from app.config import get_settings

logger = logging.getLogger(__name__)


def _path() -> Path:
    return Path(get_settings().SLACK_DIRECTORY_FILE)


def slim_from_raw(raw: dict | list) -> dict:
    """
    Build a slim {email: {handle, id, name}} map from either:
      - the raw slack-cli cache: {"fetched_at": ..., "payload": [members...]}
      - a bare list of Slack member objects
      - an already-slim {email: {...}} map (passed through)

    Deleted users and members without an email are skipped. Email keys are
    lower-cased so lookups are case-insensitive.
    """
    # Already slim?  Values are dicts carrying a handle/id — pass through.
    if isinstance(raw, dict) and "payload" not in raw and "members" not in raw:
        looks_slim = all(isinstance(v, dict) and ("handle" in v or "id" in v) for v in raw.values()) if raw else False
        if looks_slim:
            return {str(k).lower(): v for k, v in raw.items()}

    if isinstance(raw, dict):
        members = raw.get("payload") or raw.get("members") or []
    else:
        members = raw

    slim: dict = {}
    for m in members:
        if not isinstance(m, dict) or m.get("deleted"):
            continue
        profile = m.get("profile") or {}
        email = (profile.get("email") or "").strip().lower()
        if not email:
            continue
        slim[email] = {
            "handle": m.get("name") or "",
            "id": m.get("id") or "",
            "name": profile.get("real_name") or profile.get("display_name") or m.get("name") or "",
        }
    return slim


def save_directory(raw: dict | list) -> dict:
    """Slim `raw`, persist to EFS, and return {count, fetched_at}."""
    slim = slim_from_raw(raw)
    fetched_at = raw.get("fetched_at") if isinstance(raw, dict) else None
    doc = {"fetched_at": fetched_at, "count": len(slim), "entries": slim}
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(doc))
    tmp.replace(path)  # atomic swap so a concurrent read never sees a half-written file
    logger.info("Saved slim Slack directory: %d entries -> %s", len(slim), path)
    return {"count": len(slim), "fetched_at": fetched_at}


def load_directory() -> dict:
    """Return the slim {email: {handle,id,name}} map, or {} if not staged yet."""
    path = _path()
    if not path.exists():
        return {}
    try:
        doc = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        logger.error("Failed to read Slack directory %s: %s", path, exc)
        return {}
    return doc.get("entries", {})


def directory_meta() -> dict:
    """Return {staged, count, fetched_at} without loading the whole entry map into the response."""
    path = _path()
    if not path.exists():
        return {"staged": False, "count": 0, "fetched_at": None}
    try:
        doc = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {"staged": False, "count": 0, "fetched_at": None}
    return {"staged": True, "count": doc.get("count", 0), "fetched_at": doc.get("fetched_at")}


def resolve(email: str) -> dict | None:
    """
    Resolve an email address to {handle, id, name}, or None if not found.
    Case-insensitive.
    """
    if not email:
        return None
    return load_directory().get(email.strip().lower())
