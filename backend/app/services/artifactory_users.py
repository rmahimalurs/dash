"""
Artifactory user audit + cleanup, scoped by Artifactory Project.

Mirrors ``controller_users`` (project ≈ controller): sweep every Artifactory
project, list its members, cross-reference each against Active Directory, and
surface the projects that have **deactivated** members (people whose AD account
is disabled — i.e. leavers). Drill into a project to delete those users.

Deletion is **global**: a flagged user is removed from Artifactory entirely
(Access API), which also drops them from every project. The project view is just
how you discover them. Artifactory never disables an LDAP user locally, so AD is
the source of truth.

APIs:
  GET    /access/api/v1/projects                    — list projects
  GET    /access/api/v1/projects/{key}/users        — project members
  DELETE /access/api/v2/users/{username}            — delete user globally
Auth = the same admin token/creds as the license check.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

ENVS = ("prod", "dev")
_TIMEOUT = 30
SWEEP_CONCURRENCY = 8
CACHE_PATH = Path(__file__).resolve().parents[2] / "data" / "artifactory_user_audit_sweep.json"


# ─── Connection ───────────────────────────────────────────────────────────────

def _conn(env: str):
    """Return (base_url, headers, auth) for the env, or (base, None, None) if unset."""
    s = get_settings()
    if env == "prod":
        base = s.ARTIFACTORY_PROD_URL.rstrip("/")
        if s.ARTIFACTORY_PROD_ADMIN_TOKEN:
            return base, {"Authorization": f"Bearer {s.ARTIFACTORY_PROD_ADMIN_TOKEN}"}, None
        if s.ARTIFACTORY_PROD_USER and s.ARTIFACTORY_PROD_PASSWORD:
            return base, None, (s.ARTIFACTORY_PROD_USER, s.ARTIFACTORY_PROD_PASSWORD)
        return base, None, None
    if env == "dev":
        base = s.ARTIFACTORY_DEV_URL.rstrip("/")
        if s.ARTIFACTORY_DEV_TOKEN:
            return base, {"Authorization": f"Bearer {s.ARTIFACTORY_DEV_TOKEN}"}, None
        if s.ARTIFACTORY_DEV_USER and s.ARTIFACTORY_DEV_PASSWORD:
            return base, None, (s.ARTIFACTORY_DEV_USER, s.ARTIFACTORY_DEV_PASSWORD)
        return base, None, None
    raise ValueError(f"Unknown env '{env}'")


def _client(env: str):
    base, headers, auth = _conn(env)
    if not base or (headers is None and auth is None):
        return None, None
    return base, httpx.Client(headers=headers, auth=auth, timeout=_TIMEOUT, verify=True)


# ─── Projects + members ───────────────────────────────────────────────────────

def list_projects(env: str) -> dict:
    """All Artifactory projects: [{key, name}]."""
    if env not in ENVS:
        return {"projects": [], "error": f"Unknown environment '{env}'"}
    base, client = _client(env)
    if client is None:
        return {"projects": [], "error": f"No Artifactory credentials configured for {env}"}
    try:
        with client:
            resp = client.get(f"{base}/access/api/v1/projects")
            resp.raise_for_status()
            projects = [
                {"key": p.get("project_key"), "name": p.get("display_name") or p.get("project_key")}
                for p in resp.json() if p.get("project_key")
            ]
        return {"projects": projects, "error": None}
    except httpx.HTTPStatusError as exc:
        return {"projects": [], "error": f"Projects API {exc.response.status_code}"}
    except httpx.HTTPError as exc:
        return {"projects": [], "error": f"Projects API error: {exc}"}


def _project_members(base: str, client: httpx.Client, key: str) -> tuple[list[dict], str | None]:
    """Members of one project: [{name, roles}]. Returns (members, error)."""
    try:
        resp = client.get(f"{base}/access/api/v1/projects/{key}/users")
        resp.raise_for_status()
        return resp.json().get("members", []), None
    except httpx.HTTPStatusError as exc:
        return [], f"members API {exc.response.status_code}"
    except httpx.HTTPError as exc:
        return [], f"members API error: {exc}"


def _annotate(members: list[dict], ad_status: dict[str, str]) -> tuple[list[dict], dict]:
    """Annotate project members with AD status. Returns (users, counts)."""
    out = []
    n_deact = n_unknown = 0
    for m in members:
        uid = (m.get("name") or "").strip()
        if not uid:
            continue
        status = ad_status.get(uid.lower(), "unknown")
        deactivated = status == "disabled"
        if deactivated:
            n_deact += 1
        elif status == "unknown":
            n_unknown += 1
        out.append({
            "id": uid,
            "full_name": uid,          # membership API returns no display name
            "roles": m.get("roles") or [],
            "ad_status": status,       # disabled | active | not_found | unknown
            "deactivated": deactivated,
        })
    out.sort(key=lambda x: (not x["deactivated"], x["id"].lower()))
    return out, {"total": len(out), "deactivated": n_deact, "unknown": n_unknown}


def audit_project(env: str, key: str) -> dict:
    """Live: one project's members annotated with AD status (drill-in)."""
    from app.services import ldap_accounts

    if env not in ENVS:
        return {"error": f"Unknown environment '{env}'", "users": []}
    base, client = _client(env)
    if client is None:
        return {"error": f"No Artifactory credentials configured for {env}", "users": []}
    with client:
        members, error = _project_members(base, client, key)
    if error:
        return {"error": error, "users": []}
    ids = [(m.get("name") or "").strip() for m in members if m.get("name")]
    ad_status = ldap_accounts.get_disabled_status(ids)
    users, counts = _annotate(members, ad_status)
    return {"env": env, "project": key, "users": users, "counts": counts, "error": None}


# ─── Delete (global) ──────────────────────────────────────────────────────────

def delete_users(env: str, ids: list[str], only_deactivated: bool = True) -> dict:
    """Delete users from Artifactory globally. When only_deactivated (default),
    each id is re-checked against a FRESH AD lookup and refused unless confirmed-
    disabled."""
    from app.services import ldap_accounts

    if env not in ENVS:
        return {"error": f"Unknown environment '{env}'", "deleted": [], "failed": []}
    base, client = _client(env)
    if client is None:
        return {"error": f"No Artifactory credentials configured for {env}", "deleted": [], "failed": []}

    requested = [i.strip() for i in ids if i and i.strip()]
    if not requested:
        return {"error": "No user ids provided", "deleted": [], "failed": []}

    refused: list[str] = []
    to_delete = requested
    if only_deactivated:
        status = ldap_accounts.get_disabled_status(requested)
        to_delete, refused = [], []
        for i in requested:
            (to_delete if status.get(i.lower()) == "disabled" else refused).append(i)
        if not to_delete:
            return {"error": "None of the selected users are AD-deactivated — nothing deleted.",
                    "deleted": [], "failed": [], "refused": refused}

    deleted: list[str] = []
    failed: list[dict] = []
    with client:
        for uid in to_delete:
            try:
                resp = client.delete(f"{base}/access/api/v2/users/{uid}")
                if resp.is_success or resp.status_code == 404:
                    deleted.append(uid)
                else:
                    failed.append({"id": uid, "error": f"HTTP {resp.status_code}"})
            except httpx.HTTPError as exc:
                failed.append({"id": uid, "error": str(exc)[:120]})

    _invalidate_cache(env)
    return {"deleted": deleted, "failed": failed, "refused": refused, "error": None}


# ─── Sweep: rank projects by deactivated members (cached, background) ──────────

def sweep_env(env: str, on_progress=None) -> dict:
    """List members of every project, cross-reference AD once, return per-project
    deactivated counts."""
    from app.services import ldap_accounts

    if env not in ENVS:
        return {"env": env, "error": f"Unknown environment '{env}'", "projects": []}
    listed = list_projects(env)
    if listed.get("error"):
        return {"env": env, "error": listed["error"], "projects": []}
    projects = listed["projects"]

    base, headers, auth = _conn(env)
    per_project: dict[str, list[dict]] = {}
    errors: dict[str, str] = {}
    done, total = 0, len(projects)

    def _fetch(key: str):
        with httpx.Client(headers=headers, auth=auth, timeout=_TIMEOUT, verify=True) as c:
            return _project_members(base, c, key)

    with ThreadPoolExecutor(max_workers=SWEEP_CONCURRENCY) as pool:
        futures = {pool.submit(_fetch, p["key"]): p["key"] for p in projects}
        for fut in as_completed(futures):
            key = futures[fut]
            try:
                members, err = fut.result()
            except Exception as exc:  # noqa: BLE001
                members, err = [], str(exc)
            if err:
                errors[key] = err
            per_project[key] = members
            done += 1
            if on_progress:
                on_progress(done, total, key)

    all_ids = {
        (m.get("name") or "").strip()
        for members in per_project.values() for m in members if m.get("name")
    }
    ad_status = ldap_accounts.get_disabled_status(sorted(all_ids))

    rows = []
    for p in projects:
        _, counts = _annotate(per_project.get(p["key"], []), ad_status)
        rows.append({
            "project": p["key"],
            "name": p["name"],
            "total": counts["total"],
            "deactivated": counts["deactivated"],
            "unknown": counts["unknown"],
            "error": errors.get(p["key"]),
        })
    rows.sort(key=lambda x: (-x["deactivated"], x["project"].lower()))
    return {
        "env": env, "error": None, "swept_at": int(time.time()),
        "project_count": total, "projects": rows,
    }


def _save_cache(env: str, payload: dict) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    cache = load_cache() or {}
    cache[env] = payload
    tmp = CACHE_PATH.with_suffix(CACHE_PATH.suffix + f".tmp.{os.getpid()}")
    tmp.write_text(json.dumps(cache))
    os.replace(tmp, CACHE_PATH)


def load_cache() -> dict | None:
    if not CACHE_PATH.exists():
        return None
    try:
        return json.loads(CACHE_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def _invalidate_cache(env: str) -> None:
    """After a global delete, drop the deleted-from-a-project counts by re-sweeping
    lazily: clear this env's cache so the next summary triggers a fresh scan hint."""
    cache = load_cache()
    if cache and env in cache:
        cache.pop(env, None)
        try:
            tmp = CACHE_PATH.with_suffix(CACHE_PATH.suffix + f".tmp.{os.getpid()}")
            tmp.write_text(json.dumps(cache))
            os.replace(tmp, CACHE_PATH)
        except OSError:
            pass


_SWEEP_STATE: dict[str, dict] = {
    e: {"running": False, "done": 0, "total": 0, "started_at": None, "last_error": None}
    for e in ENVS
}
_sweep_lock = threading.Lock()


def sweep_status(env: str) -> dict:
    return dict(_SWEEP_STATE.get(env, {}))


def start_background_sweep(env: str) -> dict:
    if env not in ENVS:
        return {"started": False, "error": f"Unknown environment '{env}'"}
    with _sweep_lock:
        if _SWEEP_STATE[env]["running"]:
            return {"started": False, "already_running": True}
        _SWEEP_STATE[env].update(running=True, done=0, total=0,
                                 started_at=int(time.time()), last_error=None)

    def _worker():
        try:
            result = sweep_env(env, on_progress=lambda d, t, k: _SWEEP_STATE[env].update(done=d, total=t))
            if result.get("error"):
                _SWEEP_STATE[env]["last_error"] = result["error"]
            else:
                _save_cache(env, result)
        except Exception as exc:  # noqa: BLE001
            logger.exception("artifactory-user sweep failed for %s", env)
            _SWEEP_STATE[env]["last_error"] = str(exc)
        finally:
            _SWEEP_STATE[env]["running"] = False

    threading.Thread(target=_worker, daemon=True).start()
    return {"started": True, "already_running": False}


def summary(env: str, only_deactivated: bool = True) -> dict:
    """Cached per-project deactivated counts. Never blocks on a sweep."""
    cache = (load_cache() or {}).get(env)
    state = sweep_status(env)
    if not cache:
        return {"env": env, "swept_at": None, "projects": [], "sweep": state, "error": None}
    projects = cache.get("projects", [])
    if only_deactivated:
        projects = [p for p in projects if p.get("deactivated", 0) > 0]
    return {
        "env": env, "swept_at": cache.get("swept_at"),
        "project_count": cache.get("project_count"),
        "projects": projects, "sweep": state, "error": None,
    }
