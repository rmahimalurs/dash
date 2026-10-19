"""
Controller user audit + cleanup.

Lists the user accounts registered on a CloudBees managed controller (prod-east
or gc-prod-west), cross-references each against Active Directory, and flags the
ones whose AD account is **disabled** (the leaver signal). Disabled users can
then be deleted from the controller.

"Deactivated" = the user id (== EUA == AD sAMAccountName) exists in AD with the
ACCOUNTDISABLE bit set (via ``ldap_accounts.get_disabled_status``). Users whose
AD status is unknown (AD unreachable) or who aren't found in AD are NOT treated
as deletable by default — deletion targets only confirmed-disabled accounts.

Everything runs through each controller's Jenkins Script Console (Groovy), reusing
the same auth model as the CBJ waste / podTemplate features. gc-prod-west uses the
GovCloud prod token.
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
from app.services.copy_controller import _strip_cjoc, _detect_groovy_trace
from app.services.jenkins import run_groovy_script

logger = logging.getLogger(__name__)

ENVS = ("prod-east", "gc-prod-west")

# Sweep cache (per env) at /app/data on EFS. Mirrors cbj_podtemplate_config.
CACHE_PATH = Path(__file__).resolve().parents[2] / "data" / "controller_user_audit_sweep.json"
SWEEP_CONCURRENCY = 6

# Jenkins "user" ids that are framework/system accounts, never real people — never
# offered for deletion and excluded from the disabled count.
_SYSTEM_IDS = {"unknown", "sysadmin", "admin", "anonymous"}


# ─── Env → URL / auth ─────────────────────────────────────────────────────────

def _env_base(env: str) -> str:
    s = get_settings()
    if env == "prod-east":
        return _strip_cjoc(s.CLOUDBEES_EAST_PROD_URL)
    if env == "gc-prod-west":
        return _strip_cjoc(s.CLOUDBEES_GOV_PROD_URL)
    raise ValueError(f"Unknown env '{env}'")


def _env_auth(env: str):
    s = get_settings()
    if env == "prod-east":
        token = s.JENKINS_EAST_PROD_TOKEN or s.JENKINS_TOKEN
        return (s.JENKINS_PROD_USER, token) if token else None
    if env == "gc-prod-west":
        token = s.JENKINS_GOV_PROD_TOKEN
        return (s.JENKINS_PROD_USER, token) if token else None
    raise ValueError(f"Unknown env '{env}'")


def _cjoc_url(env: str) -> str:
    return f"{_env_base(env)}/cjoc"


def _controller_url(env: str, controller: str) -> str:
    # CJOC lists controllers by display name (may be upper-case, e.g. "MDP") but
    # the URL path segment is lower-cased — mirror cbj_podtemplate_config's fix.
    return f"{_env_base(env)}/{controller.lower()}"


# ─── Groovy ───────────────────────────────────────────────────────────────────

_GROOVY_LIST_CONTROLLERS = r"""
import com.cloudbees.opscenter.server.model.ManagedMaster
import groovy.json.JsonOutput
println JsonOutput.toJson(Jenkins.instance.getAllItems(ManagedMaster).collect { it.name }.sort())
"""

# Enumerate every user known to this controller. lastGranted (ms since epoch) is a
# best-effort "last active" signal via LastGrantedAuthoritiesProperty when present.
_GROOVY_LIST_USERS = r"""
import hudson.model.User
import groovy.json.JsonOutput
def out = User.getAll().collect { u ->
  Long last = null
  try {
    def p = u.getProperty(hudson.security.LastGrantedAuthoritiesProperty)
    if (p != null && p.hasProperty('timestamp')) { last = p.timestamp }
  } catch (ignored) {}
  [id: u.getId(), fullName: u.getFullName(), lastGranted: last]
}
println JsonOutput.toJson(out)
"""

_GROOVY_DELETE_USERS = r"""
import hudson.model.User
import groovy.json.JsonOutput
def ids = "__IDS__".split("\u0001").findAll { it }
def deleted = []
def failed = []
ids.each { id ->
  try {
    def u = User.getById(id, false)
    if (u != null) { u.delete(); deleted << id }
    else { failed << [id: id, error: "user not found on controller"] }
  } catch (e) { failed << [id: id, error: (e.message ?: e.toString())] }
}
println JsonOutput.toJson([deleted: deleted, failed: failed])
"""


def _last_json_line(raw: str):
    return json.loads(raw.strip().splitlines()[-1])


# ─── Public API ───────────────────────────────────────────────────────────────

def list_controllers(env: str) -> dict:
    """Every managed-controller name registered on the env's CJOC."""
    if env not in ENVS:
        return {"controllers": [], "error": f"Unknown environment '{env}'"}
    auth = _env_auth(env)
    if not auth:
        return {"controllers": [], "error": f"No Jenkins credentials configured for {env}"}
    try:
        raw = run_groovy_script(_cjoc_url(env), _GROOVY_LIST_CONTROLLERS, auth, timeout=30)
    except httpx.HTTPError as exc:
        return {"controllers": [], "error": f"CJOC Script Console call failed: {exc}"}
    trace = _detect_groovy_trace(raw)
    if trace:
        return {"controllers": [], "error": f"CJOC Groovy error: {trace}"}
    try:
        return {"controllers": _last_json_line(raw), "error": None}
    except (json.JSONDecodeError, IndexError) as exc:
        return {"controllers": [], "error": f"Could not parse controller list: {exc}"}


def _list_users_raw(env: str, controller: str) -> tuple[list[dict], str | None]:
    """Run the user-list Groovy on one controller. Returns (raw_users, error)."""
    auth = _env_auth(env)
    if not auth:
        return [], f"No Jenkins credentials configured for {env}"
    try:
        raw = run_groovy_script(_controller_url(env, controller), _GROOVY_LIST_USERS, auth, timeout=45)
    except httpx.HTTPError as exc:
        return [], f"Controller Script Console call failed: {exc}"
    trace = _detect_groovy_trace(raw)
    if trace:
        return [], f"Controller Groovy error: {trace}"
    try:
        return _last_json_line(raw), None
    except (json.JSONDecodeError, IndexError) as exc:
        return [], f"Could not parse user list: {exc}"


def _annotate_users(raw_users: list[dict], ad_status: dict[str, str]) -> tuple[list[dict], dict]:
    """Turn raw {id,fullName,lastGranted} into annotated user dicts + counts,
    given a precomputed {sam_lower: status} map."""
    users = []
    n_deact = n_unknown = 0
    for u in raw_users:
        uid = u.get("id", "") or ""
        is_system = uid.lower() in _SYSTEM_IDS
        status = "system" if is_system else ad_status.get(uid.lower(), "unknown")
        deactivated = status == "disabled"
        if deactivated:
            n_deact += 1
        elif status == "unknown":
            n_unknown += 1
        users.append({
            "id": uid,
            "full_name": u.get("fullName") or uid,
            "last_granted": u.get("lastGranted"),
            "ad_status": status,
            "deactivated": deactivated,
            "is_system": is_system,
        })
    users.sort(key=lambda x: (not x["deactivated"], x["id"].lower()))
    return users, {"total": len(users), "deactivated": n_deact, "unknown": n_unknown}


def audit_users(env: str, controller: str) -> dict:
    """List the controller's users, annotated with AD status.

    Returns {env, controller, users:[{id, full_name, last_granted, ad_status,
    deactivated, is_system}], counts:{total, deactivated, unknown}, error}.
    """
    from app.services import ldap_accounts

    if env not in ENVS:
        return {"error": f"Unknown environment '{env}'", "users": []}
    raw_users, error = _list_users_raw(env, controller)
    if error:
        return {"error": error, "users": []}

    ids = [u.get("id", "") for u in raw_users
           if u.get("id") and u["id"].lower() not in _SYSTEM_IDS]
    ad_status = ldap_accounts.get_disabled_status(ids)
    users, counts = _annotate_users(raw_users, ad_status)
    return {"env": env, "controller": controller, "users": users, "counts": counts, "error": None}


def delete_users(env: str, controller: str, ids: list[str], only_deactivated: bool = True) -> dict:
    """Delete the given user ids from the controller.

    When ``only_deactivated`` (default), the requested ids are re-checked against
    the live audit and any that are NOT confirmed AD-disabled are refused — a
    safety net so a stale UI selection can't delete an active user. System ids are
    always refused.
    """
    if env not in ENVS:
        return {"error": f"Unknown environment '{env}'", "deleted": [], "failed": []}
    auth = _env_auth(env)
    if not auth:
        return {"error": f"No Jenkins credentials configured for {env}", "deleted": [], "failed": []}

    requested = [i.strip() for i in ids if i and i.strip()]
    if not requested:
        return {"error": "No user ids provided", "deleted": [], "failed": []}

    refused = []
    to_delete = requested
    if only_deactivated:
        audit = audit_users(env, controller)
        if audit.get("error"):
            return {"error": f"Pre-delete audit failed: {audit['error']}", "deleted": [], "failed": []}
        disabled_ids = {u["id"].lower() for u in audit["users"] if u["deactivated"]}
        to_delete, refused = [], []
        for i in requested:
            (to_delete if i.lower() in disabled_ids else refused).append(i)
        if not to_delete:
            return {"error": "None of the selected users are AD-deactivated — nothing deleted.",
                    "deleted": [], "failed": [], "refused": refused}

    # \x01 separator: user ids can't contain it, and it sidesteps comma issues.
    script = _GROOVY_DELETE_USERS.replace("__IDS__", "\u0001".join(to_delete))
    try:
        raw = run_groovy_script(_controller_url(env, controller), script, auth, timeout=60)
    except httpx.HTTPError as exc:
        return {"error": f"Delete Script Console call failed: {exc}", "deleted": [], "failed": []}
    trace = _detect_groovy_trace(raw)
    if trace:
        return {"error": f"Delete Groovy error: {trace}", "deleted": [], "failed": []}
    try:
        result = _last_json_line(raw)
    except (json.JSONDecodeError, IndexError) as exc:
        return {"error": f"Could not parse delete result: {exc}", "deleted": [], "failed": []}
    result["refused"] = refused
    result["error"] = None
    return result


# ─── Sweep: find controllers with deactivated users (cached, background) ───────

def sweep_env(env: str, on_progress=None) -> dict:
    """List users on every controller in the env, cross-reference AD once, and
    return per-controller deactivated counts.

    All controllers' user lists are gathered concurrently; a SINGLE batched AD
    lookup covers every unique EUA across the env (efficient + consistent).
    """
    from app.services import ldap_accounts

    if env not in ENVS:
        return {"env": env, "error": f"Unknown environment '{env}'", "controllers": []}
    listed = list_controllers(env)
    if listed.get("error"):
        return {"env": env, "error": listed["error"], "controllers": []}
    names = listed["controllers"]

    # 1) Gather raw users per controller concurrently.
    per_controller: dict[str, list[dict]] = {}
    errors: dict[str, str] = {}
    done = 0
    total = len(names)
    with ThreadPoolExecutor(max_workers=SWEEP_CONCURRENCY) as pool:
        futures = {pool.submit(_list_users_raw, env, c): c for c in names}
        for fut in as_completed(futures):
            c = futures[fut]
            try:
                raw, err = fut.result()
            except Exception as exc:  # noqa: BLE001 — keep sweeping others
                raw, err = [], str(exc)
            if err:
                errors[c] = err
            per_controller[c] = raw
            done += 1
            if on_progress:
                on_progress(done, total, c)

    # 2) One AD lookup for every unique non-system EUA across the env.
    all_ids = {
        (u.get("id") or "").strip()
        for raw in per_controller.values() for u in raw
        if u.get("id") and u["id"].lower() not in _SYSTEM_IDS
    }
    ad_status = ldap_accounts.get_disabled_status(sorted(all_ids))

    # 3) Per-controller counts.
    controllers = []
    for c in names:
        _, counts = _annotate_users(per_controller.get(c, []), ad_status)
        controllers.append({
            "controller": c,
            "total": counts["total"],
            "deactivated": counts["deactivated"],
            "unknown": counts["unknown"],
            "error": errors.get(c),
        })
    controllers.sort(key=lambda x: (-x["deactivated"], x["controller"].lower()))
    return {
        "env": env,
        "error": None,
        "swept_at": int(time.time()),
        "controller_count": total,
        "controllers": controllers,
    }


def _save_cache(env: str, payload: dict) -> None:
    """Atomically merge one env's sweep result into the shared cache file."""
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


# Per-env background sweep state.
_SWEEP_STATE: dict[str, dict] = {
    e: {"running": False, "done": 0, "total": 0, "started_at": None, "last_error": None}
    for e in ENVS
}
_sweep_lock = threading.Lock()


def sweep_status(env: str) -> dict:
    return dict(_SWEEP_STATE.get(env, {}))


def start_background_sweep(env: str) -> dict:
    """Kick off sweep_env() on a background thread; refuse a second concurrent run."""
    if env not in ENVS:
        return {"started": False, "error": f"Unknown environment '{env}'"}
    with _sweep_lock:
        if _SWEEP_STATE[env]["running"]:
            return {"started": False, "already_running": True}
        _SWEEP_STATE[env].update(running=True, done=0, total=0,
                                 started_at=int(time.time()), last_error=None)

    def _worker():
        try:
            result = sweep_env(env, on_progress=lambda d, t, c: _SWEEP_STATE[env].update(done=d, total=t))
            if result.get("error"):
                _SWEEP_STATE[env]["last_error"] = result["error"]
            else:
                _save_cache(env, result)
        except Exception as exc:  # noqa: BLE001
            logger.exception("controller-user sweep failed for %s", env)
            _SWEEP_STATE[env]["last_error"] = str(exc)
        finally:
            _SWEEP_STATE[env]["running"] = False

    threading.Thread(target=_worker, daemon=True).start()
    return {"started": True, "already_running": False}


def summary(env: str, only_deactivated: bool = True) -> dict:
    """Cached per-controller deactivated counts for the env. Never blocks on a
    sweep — returns whatever is cached plus the running state so the UI can offer
    a refresh. controllers is filtered to those WITH deactivated users by default."""
    cache = (load_cache() or {}).get(env)
    state = sweep_status(env)
    if not cache:
        return {"env": env, "swept_at": None, "controllers": [],
                "sweep": state, "error": None}
    controllers = cache.get("controllers", [])
    if only_deactivated:
        controllers = [c for c in controllers if c.get("deactivated", 0) > 0]
    return {
        "env": env,
        "swept_at": cache.get("swept_at"),
        "controller_count": cache.get("controller_count"),
        "controllers": controllers,
        "sweep": state,
        "error": None,
    }
