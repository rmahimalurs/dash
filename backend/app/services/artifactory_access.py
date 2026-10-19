"""
Artifactory "Check User Access".

The JFrog parallel to the SonarQube access tool: enter an EUA, get whether the
user is provisioned and what they can reach —
  - identity: realm, admin, status, last login, email, groups
  - projects they're a member of, with role (from the user-audit project sweep
    cache so the modal stays fast; falls back to a live scan)
  - permission targets that grant them access (directly or via one of their
    groups), with the permissions (read/write/manage/...)

Reuses ``artifactory_users`` for the connection + project sweep cache.
"""
from __future__ import annotations

import logging

import httpx

from app.services.artifactory_users import ENVS, _conn

logger = logging.getLogger(__name__)

_TIMEOUT = 30


def _user_detail(base: str, client: httpx.Client, eua: str) -> dict | None:
    """GET /access/api/v2/users/{eua} → identity + groups. None if not found."""
    resp = client.get(f"{base}/access/api/v2/users/{eua}")
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.json()


def _projects_live(base: str, client: httpx.Client, eua: str) -> list[dict]:
    """Scan every project's members for this user. Heavier, but authoritative."""
    key = eua.strip().lower()
    out: list[dict] = []
    try:
        presp = client.get(f"{base}/access/api/v1/projects")
        presp.raise_for_status()
        projects = presp.json()
    except httpx.HTTPError as exc:
        logger.warning("artifactory-access: project list failed: %s", exc)
        return out
    for p in projects:
        pk = p.get("project_key")
        if not pk:
            continue
        try:
            mresp = client.get(f"{base}/access/api/v1/projects/{pk}/users")
            if not mresp.is_success:
                continue
            for m in mresp.json().get("members", []):
                if (m.get("name") or "").strip().lower() == key:
                    out.append({"project": pk, "name": p.get("display_name") or pk,
                                "roles": m.get("roles") or []})
                    break
        except httpx.HTTPError:
            continue
    out.sort(key=lambda x: x["project"].lower())
    return out


def _permission_targets(base: str, client: httpx.Client, eua: str, groups: list[str]) -> list[dict]:
    """Permission targets that reference the user directly or via one of their
    groups. Enumerates /artifactory/api/v2/security/permissions and inspects each."""
    key = eua.strip().lower()
    gset = {g.lower() for g in (groups or [])}
    out: list[dict] = []
    try:
        lresp = client.get(f"{base}/artifactory/api/v2/security/permissions")
        lresp.raise_for_status()
        names = [pt.get("name") for pt in lresp.json() if pt.get("name")]
    except httpx.HTTPError as exc:
        logger.warning("artifactory-access: permissions list failed: %s", exc)
        return out
    for name in names:
        try:
            dresp = client.get(f"{base}/artifactory/api/v2/security/permissions/{name}")
            if not dresp.is_success:
                continue
            detail = dresp.json()
        except httpx.HTTPError:
            continue
        repo = (detail.get("repo") or {})
        actions = repo.get("actions") or {}
        users = {u.lower(): perms for u, perms in (actions.get("users") or {}).items()}
        grps = {g.lower(): perms for g, perms in (actions.get("groups") or {}).items()}
        via = None
        perms: list[str] = []
        if key in users:
            via, perms = "user", users[key]
        else:
            hit = next((g for g in grps if g in gset), None)
            if hit:
                via, perms = f"group:{hit}", grps[hit]
        if via:
            out.append({
                "name": name,
                "via": via,
                "permissions": sorted(perms),
                "repositories": repo.get("repositories") or [],
            })
    out.sort(key=lambda x: x["name"].lower())
    return out


def get_user_access(env: str, eua: str) -> dict:
    """Look up an Artifactory user's access. Never raises for a missing user."""
    if env not in ENVS:
        return {"configured": True, "error": f"Unknown environment '{env}'"}
    base, headers, auth = _conn(env)
    if not base or (headers is None and auth is None):
        return {"configured": False, "env": env, "eua": eua,
                "message": f"Artifactory {env} credentials are not configured."}

    key = eua.strip()
    with httpx.Client(headers=headers, auth=auth, timeout=_TIMEOUT, verify=True) as client:
        try:
            detail = _user_detail(base, client, key)
        except httpx.HTTPError as exc:
            return {"configured": True, "env": env, "eua": eua,
                    "error": f"Artifactory user lookup failed: {exc}"}

        if detail is None:
            return {
                "configured": True, "found": False, "env": env, "eua": eua,
                "message": f'No Artifactory user "{eua}" found in {env}.',
            }

        groups = detail.get("groups") or []
        projects = _projects_live(base, client, key)
        perms = _permission_targets(base, client, key, groups)

    return {
        "configured": True, "found": True, "env": env, "eua": eua,
        "username": detail.get("username"),
        "email": detail.get("email"),
        "realm": detail.get("realm"),
        "admin": bool(detail.get("admin", False)),
        "status": detail.get("status"),
        "last_logged_in": detail.get("last_logged_in") or detail.get("lastLoggedIn"),
        "groups": sorted(groups),
        "projects": projects,
        "project_count": len(projects),
        "permission_targets": perms,
        "permission_target_count": len(perms),
        "message": (
            f'{detail.get("username")} is provisioned'
            + (" (admin)" if detail.get("admin") else "")
            + f" — {len(groups)} group(s), {len(projects)} project(s), "
            f"{len(perms)} permission target(s)."
        ),
    }
