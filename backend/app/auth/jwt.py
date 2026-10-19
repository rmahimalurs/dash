import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Cookie, HTTPException, status
from jose import JWTError, jwt

from app.config import get_settings

logger = logging.getLogger(__name__)

ALGORITHM = "HS256"


def create_token(data: dict) -> str:
    """Create a signed JWT token containing the provided data payload."""
    settings = get_settings()
    payload = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.JWT_EXPIRE_MINUTES)
    payload.update({"exp": expire, "iat": datetime.now(timezone.utc)})
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=ALGORITHM)


def verify_token(token: str) -> dict | None:
    """
    Verify a JWT token and return its payload.

    Returns None if the token is invalid or expired.
    """
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[ALGORITHM])
        return payload
    except JWTError as exc:
        logger.debug("JWT verification failed: %s", exc)
        return None


def get_current_user(access_token: Optional[str] = Cookie(default=None)) -> dict:
    """
    FastAPI dependency that extracts and validates the current user from the
    'access_token' httponly cookie.

    Raises HTTP 401 if the token is missing or invalid.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if not access_token:
        raise credentials_exception

    payload = verify_token(access_token)
    if payload is None:
        raise credentials_exception

    username: str = payload.get("sub")
    if not username:
        raise credentials_exception

    return {
        "username": username,
        "display_name": payload.get("display_name", username),
        "email": payload.get("email", ""),
        "groups": payload.get("groups", []),
        "role": payload.get("role", "user"),
        # Session copies preserve existing Jenkins action authentication.
        "jenkins_token": payload.get("jenkins_token"),
        "jenkins_token_uuid": payload.get("jenkins_token_uuid"),
        "jenkins_dev_token": payload.get("jenkins_dev_token"),
        "jenkins_dev_token_uuid": payload.get("jenkins_dev_token_uuid"),
        "jenkins_persistent_envs": payload.get("jenkins_persistent_envs", []),
    }
