import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.auth.jwt import get_current_user
from app.config import get_settings
from app.services import user_secrets, github_auth, rbac

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/profile", tags=["profile"])

_ALLOWED_AVATAR_TYPES = {
    "image/jpeg": "jpg",
    "image/png":  "png",
    "image/webp": "webp",
    "image/gif":  "gif",
}


class ProfileUpdate(BaseModel):
    display_name: str | None = None
    team: str | None = None
    job_title: str | None = None
    slack_handle: str | None = None
    phone: str | None = None


def _profiles_dir() -> Path:
    """Return the on-disk profiles directory, ensuring it exists."""
    path = Path(get_settings().PROFILES_DIR)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe_username(username: str) -> str:
    # Case-folded via rbac.canonical for the same reason roles are: a different
    # casing at login used to mean a second profile, losing the stored PAT.
    safe = rbac.canonical(username)
    return "".join(c for c in safe if c.isalnum() or c in ("-", "_", "."))


def _profile_path(username: str) -> Path:
    return _profiles_dir() / f"{_safe_username(username)}.json"


def load_profile(username: str) -> dict:
    """Load a user's stored profile from disk; return empty dict if absent."""
    path = _profile_path(username)
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.error("Failed to load profile for %s: %s", username, exc)
    return {}


def save_profile(username: str, data: dict) -> None:
    """Persist a user's profile to disk. Raises HTTPException on failure."""
    path = _profile_path(username)
    try:
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError as exc:
        logger.error("Failed to save profile for %s: %s", username, exc)
        raise HTTPException(status_code=500, detail=f"Could not save profile: {exc}") from exc


def find_avatar(username: str) -> Path | None:
    """Return the path to an existing avatar file for username, or None."""
    base = _profiles_dir() / _safe_username(username)
    for ext in _ALLOWED_AVATAR_TYPES.values():
        candidate = base.with_suffix(f".avatar.{ext}")
        if candidate.exists():
            return candidate
    return None


def avatar_url_for(username: str) -> str | None:
    """Return a stable URL for a user's avatar, or None if no avatar is stored."""
    p = find_avatar(username)
    if not p:
        return None
    # Include mtime for cache-busting after upload
    return f"/api/profile/avatar/{_safe_username(username)}?v={int(p.stat().st_mtime)}"


# ─── Profile data ─────────────────────────────────────────────────────────────


@router.get("")
async def get_profile(current_user: dict = Depends(get_current_user)):
    """Return the current user's profile, merging JWT claims with stored preferences."""
    username = current_user["username"]
    stored = load_profile(username)
    return {
        "username":     username,
        "display_name": stored.get("display_name") or current_user.get("display_name", username),
        "email":        current_user.get("email", ""),
        "groups":       current_user.get("groups", []),
        "team":         stored.get("team", ""),
        "job_title":    stored.get("job_title", stored.get("role", "")),
        "slack_handle": stored.get("slack_handle", ""),
        "phone":        stored.get("phone", ""),
        "avatar_url":   avatar_url_for(username),
    }


@router.put("")
async def update_profile_put(
    updates: ProfileUpdate,
    current_user: dict = Depends(get_current_user),
):
    """Update the current user's stored profile preferences."""
    username = current_user["username"]
    stored = load_profile(username)
    stored.update(updates.model_dump(exclude_none=True))
    save_profile(username, stored)
    return await get_profile(current_user)


# ─── GitHub PAT (per-user, vault-encrypted with the user's AD-password key) ────

class GitHubPatUpdate(BaseModel):
    pat: str


def _pat_status(username: str, gp: dict | None) -> dict:
    """Status only — never returns the token. locked=vault key not in memory
    (re-login needed); needs_reentry=key can't decrypt it (AD password changed)."""
    key = user_secrets.get_session_key(username)
    if not gp or not gp.get("blob"):
        return {"set": False, "locked": key is None}
    needs_reentry = False
    if key is not None:
        try:
            user_secrets.decrypt(key, gp["blob"])
        except Exception:  # noqa: BLE001
            needs_reentry = True
    return {
        "set": True,
        "login": gp.get("login"),
        "scopes": gp.get("scopes"),
        "validated_at": gp.get("validated_at"),
        "locked": key is None,
        "needs_reentry": needs_reentry,
    }


@router.get("/github-pat")
async def get_github_pat(current_user: dict = Depends(get_current_user)):
    u = current_user["username"]
    return _pat_status(u, load_profile(u).get("github_pat"))


@router.post("/github-pat")
async def set_github_pat(body: GitHubPatUpdate, current_user: dict = Depends(get_current_user)):
    u = current_user["username"]
    key = user_secrets.get_session_key(u)
    if key is None:
        raise HTTPException(status_code=409, detail="Your secret vault is locked — please log in again, then save your PAT.")
    pat = (body.pat or "").strip()
    if not pat:
        raise HTTPException(status_code=400, detail="PAT is required.")
    v = github_auth.validate_pat(pat)
    if not v.get("valid"):
        raise HTTPException(status_code=400, detail=f"PAT rejected by GitHub: {v.get('error')}")
    prof = load_profile(u)
    prof["github_pat"] = {
        "blob": user_secrets.encrypt(key, pat),
        "login": v.get("login"), "name": v.get("name"), "email": v.get("email"),
        "scopes": v.get("scopes"), "validated_at": datetime.now(timezone.utc).isoformat(),
    }
    save_profile(u, prof)
    return _pat_status(u, prof["github_pat"])


@router.post("/github-pat/validate")
async def validate_github_pat(current_user: dict = Depends(get_current_user)):
    u = current_user["username"]
    prof = load_profile(u)
    gp = prof.get("github_pat")
    if not gp or not gp.get("blob"):
        raise HTTPException(status_code=404, detail="No PAT saved.")
    key = user_secrets.get_session_key(u)
    if key is None:
        raise HTTPException(status_code=409, detail="Your secret vault is locked — please log in again to validate.")
    try:
        pat = user_secrets.decrypt(key, gp["blob"])
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=409, detail="Your saved PAT can't be unlocked (AD password changed). Please re-enter it.")
    v = github_auth.validate_pat(pat)
    gp["login"] = v.get("login") or gp.get("login")
    gp["scopes"] = v.get("scopes", gp.get("scopes"))
    gp["validated_at"] = datetime.now(timezone.utc).isoformat()
    save_profile(u, prof)
    return {**_pat_status(u, gp), "valid": v.get("valid"), "error": v.get("error")}


@router.delete("/github-pat")
async def delete_github_pat(current_user: dict = Depends(get_current_user)):
    u = current_user["username"]
    prof = load_profile(u)
    prof.pop("github_pat", None)
    save_profile(u, prof)
    return {"set": False, "locked": user_secrets.get_session_key(u) is None}


# ─── Avatar upload / serve / delete ───────────────────────────────────────────


@router.post("/avatar")
async def upload_avatar(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
):
    """Upload (or replace) the current user's profile picture."""
    settings = get_settings()
    content_type = (file.content_type or "").lower()
    if content_type not in _ALLOWED_AVATAR_TYPES:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported image type: {content_type!r}. Use jpg, png, webp, or gif.",
        )

    body = await file.read()
    if len(body) > settings.AVATAR_MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Avatar exceeds the {settings.AVATAR_MAX_BYTES // 1024 // 1024} MiB size limit.",
        )
    if not body:
        raise HTTPException(status_code=400, detail="Empty file.")

    username = current_user["username"]
    safe = _safe_username(username)
    new_ext = _ALLOWED_AVATAR_TYPES[content_type]

    # Remove any prior avatar with a different extension
    for ext in _ALLOWED_AVATAR_TYPES.values():
        prior = _profiles_dir() / f"{safe}.avatar.{ext}"
        if ext != new_ext and prior.exists():
            try:
                prior.unlink()
            except OSError as exc:
                logger.warning("Could not delete prior avatar %s: %s", prior, exc)

    out_path = _profiles_dir() / f"{safe}.avatar.{new_ext}"
    try:
        out_path.write_bytes(body)
    except OSError as exc:
        logger.error("Failed to save avatar for %s: %s", username, exc)
        raise HTTPException(status_code=500, detail=f"Could not save avatar: {exc}") from exc

    return {"avatar_url": avatar_url_for(username)}


@router.delete("/avatar")
async def delete_avatar(current_user: dict = Depends(get_current_user)):
    """Remove the current user's avatar."""
    username = current_user["username"]
    path = find_avatar(username)
    if path:
        try:
            path.unlink()
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"Could not delete avatar: {exc}") from exc
    return {"avatar_url": None}


@router.get("/avatar/{username}")
async def serve_avatar(
    username: str,
    _current_user: dict = Depends(get_current_user),
):
    """Serve any authenticated user's avatar image."""
    path = find_avatar(username)
    if not path:
        raise HTTPException(status_code=404, detail="No avatar set")
    ext = path.suffix.lstrip(".")
    media_type = next(
        (mime for mime, e in _ALLOWED_AVATAR_TYPES.items() if e == ext),
        "application/octet-stream",
    )
    return FileResponse(
        path,
        media_type=media_type,
        headers={"Cache-Control": "private, max-age=300"},
    )
