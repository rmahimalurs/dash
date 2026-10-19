import os
from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response, status
from pydantic import BaseModel

from app.auth.jwt import create_token, get_current_user
from app.auth.ldap import AccessGroupError, AccountStateError, authenticate_user
from app.config import get_settings
from app.routers.profile import avatar_url_for, load_profile, save_profile
from app.services import audit, rbac
from app.services import jenkins_auth

router = APIRouter(prefix="/auth", tags=["auth"])

COOKIE_NAME = "access_token"
COOKIE_MAX_AGE = 60 * 480  # 8 hours in seconds


@router.post("/login")
async def login(
    request: Request,
    response: Response,
    username: str = Form(...),
    password: str = Form(...),
):
    """
    Authenticate with AD credentials.
    On success, sets an httponly 'access_token' cookie and returns user info.
    Reuses one encrypted personal Jenkins token per required environment. A
    token is created only the first time (or after it is revoked), not on each
    login. Existing Jenkins actions continue under the engineer's identity.
    """
    client_ip = request.client.host if request.client else None

    try:
        user = authenticate_user(username, password)
    except AccessGroupError:
        # Valid credentials, but the user is not in the required AD access group.
        audit.log_event(
            "auth.login", username,
            details={"success": False, "reason": "not_in_access_group"}, ip=client_ip,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not part of the Access group.",
        )
    except AccountStateError as exc:
        # The password may well be right; AD refused for a reason worth naming.
        audit.log_event(
            "auth.login", username,
            details={"success": False, "reason": exc.reason}, ip=client_ip,
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=exc.message)
    if user is None:
        audit.log_event("auth.login", username, details={"success": False}, ip=client_ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    settings = get_settings()

    # Register user and resolve their role (respects ADMIN_USERS bootstrap list)
    role = rbac.register_user(user["username"], user["display_name"], user["email"])

    # Derive + cache the user's secret-vault key from their AD password so their
    # stored GitHub PAT can be decrypted during this session. Best-effort; held
    # only in memory, never persisted or put in the JWT.
    from app.services import user_secrets
    user_secrets.unlock_session(user["username"], password)

    token_data: dict = {
        "sub": user["username"],
        "display_name": user["display_name"],
        "email": user["email"],
        "groups": user["groups"],
        "role": role,
    }

    # Jenkins tokens are generated once per engineer/environment and kept
    # encrypted in that engineer's password-derived profile vault. Existing
    # credentials are checked and reused across login sessions.
    persistent_jenkins_envs: list[str] = []
    if not settings.DEV_MODE and settings.JENKINS_CJOC_URL:
        prod_info, prod_persistent = await jenkins_auth.get_or_create_jenkins_token(
            settings.JENKINS_CJOC_URL, user["username"], password, "prod-east",
        )
        if prod_info and prod_info.get("token_value"):
            token_data["jenkins_token"] = prod_info["token_value"]
            token_data["jenkins_token_uuid"] = prod_info.get("token_uuid")
            if prod_persistent:
                persistent_jenkins_envs.append("prod-east")

    if not settings.DEV_MODE and settings.JENKINS_DEV_EAST_CJOC_URL:
        dev_info, dev_persistent = await jenkins_auth.get_or_create_jenkins_token(
            settings.JENKINS_DEV_EAST_CJOC_URL, user["username"], password, "dev-east",
        )
        if dev_info and dev_info.get("token_value"):
            token_data["jenkins_dev_token"] = dev_info["token_value"]
            token_data["jenkins_dev_token_uuid"] = dev_info.get("token_uuid")
            if dev_persistent:
                persistent_jenkins_envs.append("dev-east")

    if persistent_jenkins_envs:
        token_data["jenkins_persistent_envs"] = persistent_jenkins_envs

    token = create_token(token_data)

    is_secure = os.getenv("DEV_MODE", "false").lower() != "true"
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        secure=is_secure,
        samesite="lax",
        max_age=COOKIE_MAX_AGE,
        path="/",
    )

    audit.log_event("auth.login", user["username"], details={"success": True}, ip=client_ip)

    authorized_emails = {e.strip().lower() for e in settings.ITC_AUTHORIZED_EMAIL.split(",") if e.strip()}
    authorized_users  = {u.strip().lower() for u in settings.ITC_AUTHORIZED_USERS.split(",") if u.strip()}

    # Merge stored profile + avatar into the login response so a fresh login
    # reflects saved profile details/picture without needing a hard reload
    # (mirrors _enrich_user, which only runs on GET /auth/me).
    stored = load_profile(user["username"])

    return {
        "username": user["username"],
        "display_name": stored.get("display_name") or user["display_name"],
        "email": user["email"],
        "groups": user["groups"],
        "role": role,
        "team": stored.get("team", ""),
        "job_title": stored.get("job_title", stored.get("role", "")),
        "slack_handle": stored.get("slack_handle", ""),
        "phone": stored.get("phone", ""),
        "avatar_url": avatar_url_for(user["username"]),
        "jira_authorized": (
            user["email"].lower() in authorized_emails
            or user["username"].lower() in authorized_users
        ),
    }


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    current_user: dict = Depends(get_current_user),
):
    """
    Clear the cookie. Revoke legacy/session-only tokens; retain encrypted
    per-user tokens so later sessions can reuse them.
    """
    settings = get_settings()
    username = current_user.get("username", "")
    client_ip = request.client.host if request.client else None

    # Drop the in-memory vault key so a stored PAT can't be used after logout.
    from app.services import user_secrets
    user_secrets.lock_session(username)

    prod_token       = current_user.get("jenkins_token")
    prod_token_uuid  = current_user.get("jenkins_token_uuid")
    persistent_envs = set(current_user.get("jenkins_persistent_envs", []))
    if prod_token and prod_token_uuid and settings.JENKINS_CJOC_URL and "prod-east" not in persistent_envs:
        await jenkins_auth.revoke_jenkins_token(
            settings.JENKINS_CJOC_URL, username, prod_token, prod_token_uuid
        )

    dev_token      = current_user.get("jenkins_dev_token")
    dev_token_uuid = current_user.get("jenkins_dev_token_uuid")
    if dev_token and dev_token_uuid and settings.JENKINS_DEV_EAST_CJOC_URL and "dev-east" not in persistent_envs:
        await jenkins_auth.revoke_jenkins_token(
            settings.JENKINS_DEV_EAST_CJOC_URL, username, dev_token, dev_token_uuid
        )

    audit.log_event("auth.logout", username, ip=client_ip)
    response.delete_cookie(key=COOKIE_NAME, path="/")
    return {"message": "Logged out successfully"}


class ProfilePatch(BaseModel):
    display_name: str | None = None
    team: str | None = None
    job_title: str | None = None
    slack_handle: str | None = None
    phone: str | None = None


def _enrich_user(current_user: dict) -> dict:
    """Resolve role + jira_authorized + stored profile fields + avatar_url onto the JWT user."""
    settings = get_settings()
    username = current_user["username"]

    current_user["role"] = rbac.get_role(username)

    authorized_emails = {e.strip().lower() for e in settings.ITC_AUTHORIZED_EMAIL.split(",") if e.strip()}
    authorized_users  = {u.strip().lower() for u in settings.ITC_AUTHORIZED_USERS.split(",") if u.strip()}
    current_user["jira_authorized"] = (
        current_user.get("email", "").lower() in authorized_emails
        or username.lower() in authorized_users
    )

    stored = load_profile(username)
    if stored.get("display_name"):
        current_user["display_name"] = stored["display_name"]
    current_user["team"]         = stored.get("team", "")
    current_user["job_title"]    = stored.get("job_title", "")
    current_user["slack_handle"] = stored.get("slack_handle", "")
    current_user["phone"]        = stored.get("phone", "")
    current_user["avatar_url"]   = avatar_url_for(username)
    return current_user


@router.get("/me")
async def me(current_user: dict = Depends(get_current_user)):
    """Return the currently authenticated user's info, with profile + role + jira_authorized merged."""
    return _public_user(_enrich_user(current_user))


@router.patch("/me")
async def patch_me(
    updates: ProfilePatch,
    current_user: dict = Depends(get_current_user),
):
    """Update the current user's stored profile preferences. Returns the merged user."""
    username = current_user["username"]
    stored = load_profile(username)
    stored.update(updates.model_dump(exclude_none=True))
    save_profile(username, stored)
    return _public_user(_enrich_user(current_user))


def _public_user(user: dict) -> dict:
    """Keep backend Jenkins credentials out of browser-visible auth responses."""
    return {key: value for key, value in user.items() if not key.startswith("jenkins_")}
