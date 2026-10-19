import json
import logging
from pathlib import Path
from typing import Literal

from app.config import get_settings

logger = logging.getLogger(__name__)

RoleType = Literal["admin", "user"]


def _roles_file() -> Path:
    return Path(get_settings().ROLES_FILE)


def canonical(username: str) -> str:
    """Canonical storage key for a username.

    EUAs are case-insensitive in AD, so every lookup and every stored key folds
    to one spelling. Without this, signing in as RWRW rather than rwrw produced
    a second account that did not carry the first one's role.
    """
    return (username or "").strip().upper()


def _admin_usernames() -> set[str]:
    raw = get_settings().ADMIN_USERS
    return {canonical(u) for u in raw.split(",") if u.strip()}


def _load() -> dict:
    path = _roles_file()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception as exc:
        logger.error("Failed to read roles file: %s", exc)
        return {}


def _save(data: dict) -> None:
    path = _roles_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))


def get_role(username: str) -> RoleType:
    # ADMIN_USERS setting always wins — works even before roles.json exists
    key = canonical(username)
    if key in _admin_usernames():
        return "admin"
    entry = _load().get(key, {})
    return entry.get("role", "user")


def set_role(username: str, role: RoleType, *, display_name: str = "", email: str = "") -> None:
    data = _load()
    key = canonical(username)
    entry = data.get(key, {})
    entry["role"] = role
    if display_name:
        entry["display_name"] = display_name
    if email:
        entry["email"] = email
    data[key] = entry
    _save(data)


def register_user(username: str, display_name: str, email: str, admin_usernames: list[str] | None = None) -> RoleType:
    """Register a user on first login and return their role.

    Admin bootstrap: if the username appears in admin_usernames or ADMIN_USERS setting,
    the role is always set to admin, even on subsequent logins.
    """
    effective_admins = {canonical(u) for u in (admin_usernames or [])} | _admin_usernames()
    data = _load()
    key = canonical(username)
    entry = data.get(key, {})

    if key in effective_admins:
        entry["role"] = "admin"
    elif "role" not in entry:
        entry["role"] = "user"

    entry["display_name"] = display_name
    entry["email"] = email
    data[key] = entry
    _save(data)
    return entry["role"]


def list_users() -> list[dict]:
    data = _load()
    return [
        {
            "username": k,
            "display_name": v.get("display_name", k),
            "email": v.get("email", ""),
            "role": v.get("role", "user"),
        }
        for k, v in data.items()
    ]
