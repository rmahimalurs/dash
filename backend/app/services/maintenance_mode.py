"""
Site-wide maintenance mode.

A small file-backed flag (EFS-persisted) that, when enabled, causes the
frontend to show an "Under Maintenance" page to everyone except admins.
"""
import json
import logging
import os
from datetime import datetime, timezone

from app.config import get_settings

logger = logging.getLogger(__name__)

DEFAULT_MESSAGE = "Under Maintenance - Go have a chai"


def _path() -> str:
    return get_settings().MAINTENANCE_STATE_FILE


def get_state() -> dict:
    """Return the current maintenance state. Defaults to disabled."""
    try:
        with open(_path()) as f:
            data = json.load(f)
        return {
            "enabled": bool(data.get("enabled", False)),
            "message": data.get("message") or DEFAULT_MESSAGE,
            "updated_by": data.get("updated_by"),
            "updated_at": data.get("updated_at"),
        }
    except (FileNotFoundError, json.JSONDecodeError):
        return {"enabled": False, "message": DEFAULT_MESSAGE, "updated_by": None, "updated_at": None}


def set_state(enabled: bool, by: str, message: str | None = None) -> dict:
    """Enable/disable maintenance mode and persist it."""
    state = {
        "enabled": bool(enabled),
        "message": (message or "").strip() or DEFAULT_MESSAGE,
        "updated_by": by,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    path = _path()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w") as f:
        json.dump(state, f)
    os.replace(tmp, path)
    logger.info("Maintenance mode set to %s by %s", state["enabled"], by)
    return state
