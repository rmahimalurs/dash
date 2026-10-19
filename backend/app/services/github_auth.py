"""GitHub auth resolution: use the engineer's stored PAT when present and
unlocked, otherwise fall back to the service-account GITHUB_TOKEN. Commits
and writes made with an engineer's PAT are attributed to them by GitHub.
"""
from __future__ import annotations

import logging

import httpx

from app.config import get_settings
from app.services import user_secrets
from app.services.github_http import GH_API, auth_headers

logger = logging.getLogger(__name__)


def validate_pat(pat: str) -> dict:
    """Validate a GitHub PAT. Returns {valid, login, name, email, scopes, error}."""
    try:
        r = httpx.get(f"{GH_API}/user", headers=auth_headers(pat), timeout=15)
    except Exception as exc:  # noqa: BLE001
        return {"valid": False, "error": f"Could not reach GitHub: {exc}"}
    if r.status_code == 401:
        return {"valid": False, "error": "Token rejected by GitHub (401) — expired or invalid."}
    if r.status_code != 200:
        return {"valid": False, "error": f"GitHub returned {r.status_code}."}
    u = r.json()
    # Classic PATs report scopes in this header; fine-grained PATs don't (empty).
    scopes = r.headers.get("x-oauth-scopes", "")
    return {
        "valid": True,
        "login": u.get("login"),
        "name": u.get("name") or u.get("login"),
        "email": u.get("email") or (f"{u.get('login')}@users.noreply.github.com" if u.get("login") else None),
        "scopes": scopes,
    }


def resolve_github_auth(username: str | None) -> dict:
    """Resolve the GitHub token + commit identity for a write on this user's
    behalf. Returns {token, login, name, email, source}, source "user" (their
    PAT) or "service" (fallback GITHUB_TOKEN)."""
    settings = get_settings()
    if username:
        try:
            from app.routers.profile import load_profile  # local import avoids a cycle
            gp = (load_profile(username) or {}).get("github_pat")
            key = user_secrets.get_session_key(username)
            # Needs both a stored PAT and an unlocked session vault; a locked
            # vault (post-restart) or changed password (decrypt raises) falls
            # through to the service account below.
            if gp and gp.get("blob") and key:
                pat = user_secrets.decrypt(key, gp["blob"])
                return {
                    "token": pat,
                    "login": gp.get("login"),
                    "name": gp.get("name") or gp.get("login"),
                    "email": gp.get("email") or (f"{gp.get('login')}@users.noreply.github.com"
                                                 if gp.get("login") else None),
                    "source": "user",
                }
        except Exception as exc:  # noqa: BLE001 — never block a write on PAT resolution
            logger.warning("Falling back to service GitHub token for %s: %s", username, exc)
    return {
        "token": settings.GITHUB_TOKEN,
        "login": None,
        "name": settings.GITHUB_COMMIT_NAME,
        "email": settings.GITHUB_COMMIT_EMAIL,
        "source": "service",
    }


def has_personal_pat(username: str) -> dict:
    """Whether this user has a usable personal PAT on file -- gates writes
    that must be attributed to them, not the shared service account."""
    auth = resolve_github_auth(username)
    return {"can_send": auth["source"] == "user", "login": auth.get("login")}


def list_accessible_orgs(username: str) -> dict:
    """Orgs for an org picker, restricted to ones where the caller's own PAT
    holds the admin (owner) role (GET /user/memberships/orgs) rather than
    every org they merely belong to -- a plain-member org would only fail
    when used, so leaving it out doubles as a guardrail against picking an
    org that was never going to work.

    The configured default org is always included regardless of what the
    lookup says; the write call itself still enforces the real permission
    either way. Returns {orgs, default}, falling back to [default] alone
    with no personal PAT to ask, or when the lookup fails.
    """
    settings = get_settings()
    default_org = settings.GITHUB_ORG
    auth = resolve_github_auth(username)
    if auth["source"] != "user":
        return {"orgs": [default_org], "default": default_org}

    try:
        r = httpx.get(
            f"{GH_API}/user/memberships/orgs",
            headers=auth_headers(auth["token"]),
            params={"state": "active", "per_page": 100},
            timeout=15,
        )
        r.raise_for_status()
        admin_logins = sorted(
            {m["organization"]["login"] for m in r.json() if m.get("role") == "admin"},
            key=str.casefold,
        )
    except Exception as exc:  # noqa: BLE001
        # A failed lookup is "unknown", not "no" -- keep offering the
        # default rather than an empty picker, same as before. Only a
        # *successful* lookup that conclusively excludes the default org
        # is trusted enough to stop recommending it below.
        logger.warning("Could not list orgs for %s: %s", username, exc)
        return {"orgs": [default_org], "default": default_org}

    if not admin_logins:
        # Lookup succeeded and found no admin org at all for this caller.
        # Defaulting to the configured org here would select one we just
        # confirmed will fail; offer nothing rather than a guaranteed-bad pick.
        return {"orgs": [], "default": ""}

    if default_org.casefold() in {o.casefold() for o in admin_logins}:
        others = [o for o in admin_logins if o.casefold() != default_org.casefold()]
        return {"orgs": [default_org, *others], "default": default_org}

    # The caller admins other orgs but not the configured default -- select
    # a real eligible one instead of defaulting to one known to fail.
    return {"orgs": admin_logins, "default": admin_logins[0]}
