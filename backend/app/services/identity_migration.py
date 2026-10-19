"""One-time merge of per-user state that was split by username casing.

Logins used to be keyed by whatever casing the engineer typed, so one person
could end up with several identities: duplicate rows in the Admin console, and a
role, GitHub PAT or What's-new acknowledgment attached to only one of them.
``authenticate_user`` now takes the spelling from AD and ``rbac.canonical``
folds every key, so no new duplicates appear; this folds the existing ones.

Runs on startup and is idempotent: once every key is canonical it does nothing.
"""
from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path

from app.config import get_settings
from app.services import rbac

logger = logging.getLogger(__name__)

_ROLE_RANK = {"admin": 2, "user": 1}


def _merge_role_entries(entries: list[dict]) -> dict:
    """Fold duplicate role entries, keeping the highest role and richest fields."""
    merged: dict = {}
    for entry in sorted(entries, key=lambda e: _ROLE_RANK.get(e.get("role", "user"), 0)):
        for key, value in entry.items():
            # Later (higher-ranked) entries win, but never overwrite with blanks.
            if value or key not in merged:
                merged[key] = value
    return merged


def migrate_roles() -> dict:
    """Collapse roles.json onto canonical keys. Returns a summary."""
    path = Path(get_settings().ROLES_FILE)
    if not path.exists():
        return {"merged": 0, "groups": []}

    try:
        data = json.loads(path.read_text())
    except Exception as exc:  # noqa: BLE001
        logger.error("identity migration: could not read %s: %s", path, exc)
        return {"merged": 0, "groups": [], "error": str(exc)}

    grouped: dict[str, list[tuple[str, dict]]] = {}
    for name, entry in data.items():
        grouped.setdefault(rbac.canonical(name), []).append((name, entry))

    collisions = {k: v for k, v in grouped.items() if len(v) > 1 or v[0][0] != k}
    if not collisions:
        return {"merged": 0, "groups": []}

    shutil.copyfile(path, path.with_suffix(".json.pre-canonical"))

    rebuilt = {k: _merge_role_entries([e for _, e in v]) for k, v in grouped.items()}
    path.write_text(json.dumps(rebuilt, indent=2))

    groups = []
    for key, members in sorted(collisions.items()):
        names = [n for n, _ in members]
        groups.append({"canonical": key, "from": names, "role": rebuilt[key].get("role")})
        logger.warning("identity migration: merged %s -> %s (role=%s)",
                       names, key, rebuilt[key].get("role"))
    return {"merged": len(collisions), "groups": groups}


def _profile_richness(path: Path) -> tuple:
    """Prefer the profile carrying real state over an emptier duplicate."""
    try:
        data = json.loads(path.read_text())
    except Exception:  # noqa: BLE001
        return (0, 0, 0.0)
    has_pat = 1 if data.get("github_pat") else 0
    return (has_pat, len(data), path.stat().st_mtime)


def migrate_profiles() -> dict:
    """Rename profile and avatar files onto canonical keys, keeping the richest."""
    directory = Path(get_settings().PROFILES_DIR)
    if not directory.is_dir():
        return {"renamed": 0, "dropped": 0}

    renamed = dropped = 0

    # Profile JSON: group by canonical stem, keep the richest, drop the rest.
    groups: dict[str, list[Path]] = {}
    for f in directory.glob("*.json"):
        if f.name.endswith(".pre-canonical"):
            continue
        groups.setdefault(rbac.canonical(f.stem), []).append(f)

    for key, files in groups.items():
        target = directory / f"{key}.json"
        if len(files) == 1 and files[0] == target:
            continue
        best = max(files, key=_profile_richness)
        for f in files:
            if f != best:
                logger.warning("identity migration: dropping duplicate profile %s (kept %s)",
                               f.name, best.name)
                f.unlink(missing_ok=True)
                dropped += 1
        if best != target:
            best.replace(target)
            logger.warning("identity migration: profile %s -> %s", best.name, target.name)
            renamed += 1

    # Avatars live beside the profiles as <user>.avatar.<ext>.
    for f in directory.iterdir():
        if ".avatar." not in f.name:
            continue
        stem, _, rest = f.name.partition(".avatar.")
        key = rbac.canonical(stem)
        if stem == key:
            continue
        target = directory / f"{key}.avatar.{rest}"
        if target.exists():
            f.unlink(missing_ok=True)
            dropped += 1
            continue
        f.replace(target)
        logger.warning("identity migration: avatar %s -> %s", f.name, target.name)
        renamed += 1

    return {"renamed": renamed, "dropped": dropped}


def run() -> dict:
    """Run both migrations, logging a summary. Never raises."""
    try:
        roles = migrate_roles()
        profiles = migrate_profiles()
    except Exception as exc:  # noqa: BLE001 — must never block startup
        logger.error("identity migration failed: %s", exc)
        return {"error": str(exc)}

    if roles.get("merged") or profiles.get("renamed") or profiles.get("dropped"):
        logger.warning("identity migration: %s role group(s) merged, "
                       "%s profile file(s) renamed, %s dropped",
                       roles.get("merged", 0), profiles.get("renamed", 0),
                       profiles.get("dropped", 0))
    return {"roles": roles, "profiles": profiles}
