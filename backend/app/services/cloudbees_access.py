"""
CloudBees "Check User Access".

Answers "what does <EUA> have access to across CloudBees?" — the per-controller
parallel to the SonarQube access tool. CloudBees RBAC (nectar plugin) grants
access via **groups** on each controller: a group has roles (Admin/Developer/...)
and members (user SIDs == EUAs). A user's access on a controller is the union of
the groups they belong to and the roles those groups carry.

RBAC is per-controller, so a live per-user lookup would have to Script-Console
every controller (~196 prod-east) — too slow for a modal. Instead a daily
background sweep (5 AM, alongside the other sweeps) dumps every controller's
groups→roles+members once and builds a reverse index {user: [{controller, groups,
roles}]}; the modal reads that cache instantly. On-demand re-scan is available.

Env/auth/URL helpers + the controller list are reused from ``controller_users``.
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

from app.services.controller_users import (
    ENVS, SWEEP_CONCURRENCY, _cjoc_url, _controller_url, _detect_groovy_trace,
    _env_auth, list_controllers,
)
from app.services.jenkins import run_groovy_script

logger = logging.getLogger(__name__)

CACHE_PATH = Path(__file__).resolve().parents[2] / "data" / "cloudbees_access_sweep.json"

# Sentinel "controller" key for Operations Center (CJOC) role assignments. CJOC
# roles are inherited by every controller, so a member here (esp. administer =
# global admin) has that access org-wide — they won't appear in any controller's
# LOCAL RBAC groups, which is why the CJOC must be swept separately.
CJOC_KEY = "CJOC · Operations Center"

# Dump every RBAC group on the controller as {group, roles[], members[]}.
# Generalizes copy_controller._GROOVY_LIST_ADMINS (which kept only admin groups).
_GROOVY_DUMP_RBAC = r"""
import groovy.json.JsonOutput
def strat = Jenkins.instance.authorizationStrategy
if (strat == null) { println JsonOutput.toJson([error: "NO_AUTH_STRATEGY"]); return }
def groups = []
try { groups = strat.getLocalGroups() ?: [] } catch (Throwable ignored) {}
if (groups.isEmpty()) { try { groups = strat.getGroups() ?: [] } catch (Throwable ignored) {} }
def out = []
groups.each { g ->
  def roles = []
  try { g.getRoles()?.each { r -> def s = (r?.toString() ?: ""); if (s) roles << s } } catch (Throwable ignored) {}
  def members = []
  try {
    g.getUsers()?.each { u ->
      def s = (u instanceof String) ? u : (u?.name ?: u?.toString())
      if (s && s != "anonymous") members << s.toString()
    }
  } catch (Throwable ignored) {}
  def name = (g?.name ?: g?.toString())
  out << [group: (name ?: "").toString(), roles: roles, members: members]
}
println JsonOutput.toJson(out)
"""


def _last_json_line(raw: str):
    return json.loads(raw.strip().splitlines()[-1])


def _dump_rbac_at(env: str, url: str) -> tuple[list[dict], str | None]:
    """Run the RBAC dump Groovy at an arbitrary Jenkins URL (controller or CJOC)."""
    auth = _env_auth(env)
    if not auth:
        return [], f"No Jenkins credentials configured for {env}"
    try:
        raw = run_groovy_script(url, _GROOVY_DUMP_RBAC, auth, timeout=45)
    except httpx.HTTPError as exc:
        return [], f"Script Console call failed: {exc}"
    trace = _detect_groovy_trace(raw)
    if trace:
        return [], f"Groovy error: {trace}"
    try:
        data = _last_json_line(raw)
    except (json.JSONDecodeError, IndexError) as exc:
        return [], f"Could not parse RBAC dump: {exc}"
    if isinstance(data, dict) and data.get("error"):
        return [], str(data["error"])
    return data if isinstance(data, list) else [], None


def _dump_controller_rbac(env: str, controller: str) -> tuple[list[dict], str | None]:
    """Return ([{group, roles, members}], error) for one controller."""
    return _dump_rbac_at(env, _controller_url(env, controller))


# ─── Sweep: build a per-user access index across all controllers ──────────────

def sweep_env(env: str, on_progress=None) -> dict:
    """Dump RBAC on every controller and build a reverse per-user index.

    Returns {env, swept_at, controller_count, users:{sid: [{controller, groups,
    roles}]}, errors:{controller: err}}.
    """
    if env not in ENVS:
        return {"env": env, "error": f"Unknown environment '{env}'", "users": {}}
    listed = list_controllers(env)
    if listed.get("error"):
        return {"env": env, "error": listed["error"], "users": {}}
    names = listed["controllers"]

    per_controller: dict[str, list[dict]] = {}
    errors: dict[str, str] = {}
    done, total = 0, len(names) + 1  # +1 for the CJOC

    # Operations Center (CJOC) RBAC — inherited by all controllers (global admins).
    cjoc_dump, cjoc_err = _dump_rbac_at(env, _cjoc_url(env))
    per_controller[CJOC_KEY] = cjoc_dump
    if cjoc_err:
        errors[CJOC_KEY] = cjoc_err
    done += 1
    if on_progress:
        on_progress(done, total, CJOC_KEY)

    with ThreadPoolExecutor(max_workers=SWEEP_CONCURRENCY) as pool:
        futures = {pool.submit(_dump_controller_rbac, env, c): c for c in names}
        for fut in as_completed(futures):
            c = futures[fut]
            try:
                dump, err = fut.result()
            except Exception as exc:  # noqa: BLE001
                dump, err = [], str(exc)
            if err:
                errors[c] = err
            per_controller[c] = dump
            done += 1
            if on_progress:
                on_progress(done, total, c)

    # Reverse index: user SID (lowercased) -> {controller: {groups:set, roles:set}}
    index: dict[str, dict[str, dict[str, set]]] = {}
    for controller, groups in per_controller.items():
        for grp in groups:
            gname = grp.get("group") or ""
            roles = grp.get("roles") or []
            for sid in grp.get("members") or []:
                key = sid.strip().lower()
                if not key:
                    continue
                slot = index.setdefault(key, {}).setdefault(controller, {"groups": set(), "roles": set()})
                if gname:
                    slot["groups"].add(gname)
                slot["roles"].update(roles)

    # Serialize sets → sorted lists; per-user list of controller-access dicts.
    users: dict[str, list[dict]] = {}
    for sid, controllers in index.items():
        users[sid] = sorted(
            (
                {"controller": c, "groups": sorted(v["groups"]), "roles": sorted(v["roles"])}
                for c, v in controllers.items()
            ),
            key=lambda x: x["controller"].lower(),
        )

    return {
        "env": env, "error": None, "swept_at": int(time.time()),
        "controller_count": len(names), "user_count": len(users),
        "users": users, "errors": errors,
    }


# ─── Cache (per env) ──────────────────────────────────────────────────────────

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
            result = sweep_env(env, on_progress=lambda d, t, c: _SWEEP_STATE[env].update(done=d, total=t))
            if result.get("error"):
                _SWEEP_STATE[env]["last_error"] = result["error"]
            else:
                _save_cache(env, result)
        except Exception as exc:  # noqa: BLE001
            logger.exception("cloudbees-access sweep failed for %s", env)
            _SWEEP_STATE[env]["last_error"] = str(exc)
        finally:
            _SWEEP_STATE[env]["running"] = False

    threading.Thread(target=_worker, daemon=True).start()
    return {"started": True, "already_running": False}


# ─── Per-user lookup (from cache) ─────────────────────────────────────────────

def lookup(env: str, eua: str) -> dict:
    """Return the user's CloudBees access across all controllers, from the cached
    sweep. Never raises for a missing user — returns found=False."""
    from app.services import ldap_accounts

    if env not in ENVS:
        return {"configured": True, "error": f"Unknown environment '{env}'"}
    cache = (load_cache() or {}).get(env)
    state = sweep_status(env)
    if not cache:
        return {"env": env, "eua": eua, "found": False, "swept_at": None,
                "sweep": state, "no_scan": True,
                "message": "No access scan yet for this environment — run a scan."}

    key = (eua or "").strip().lower()
    entries = cache.get("users", {}).get(key, [])
    ad = ldap_accounts.get_disabled_status([key]) if key else {}
    ad_status = ad.get(key, "unknown")

    # Split the CJOC (Operations Center) entry from per-controller entries.
    cjoc = next((e for e in entries if e["controller"] == CJOC_KEY), None)
    controllers = [e for e in entries if e["controller"] != CJOC_KEY]
    global_admin = bool(cjoc and any("administer" in r.lower() for r in cjoc.get("roles", [])))

    if not entries:
        return {
            "env": env, "eua": eua, "found": False, "swept_at": cache.get("swept_at"),
            "ad_status": ad_status, "controllers": [], "cjoc": None, "global_admin": False,
            "sweep": state,
            "message": f'"{eua}" has no CloudBees RBAC access on {env} (CJOC or any controller).',
        }

    total_roles = sorted({r for e in entries for r in e["roles"]})
    if global_admin:
        msg = (f'{eua} is a global admin at the Operations Center (CJOC) — '
               f'administer access across ALL {env} controllers'
               + (f'; plus explicit membership on {len(controllers)} controller(s)' if controllers else '')
               + '.')
    elif cjoc:
        msg = (f'{eua} has CJOC-level access ({", ".join(cjoc["roles"]) or "no named roles"})'
               + (f' and access to {len(controllers)} controller(s)' if controllers else '')
               + '.')
    else:
        msg = (f'{eua} has access to {len(controllers)} {env} controller(s) '
               f'({", ".join(total_roles) or "no named roles"}).')

    return {
        "env": env, "eua": eua, "found": True, "swept_at": cache.get("swept_at"),
        "ad_status": ad_status,
        "global_admin": global_admin,
        "cjoc": cjoc,
        "controller_count": len(controllers),
        "controllers": controllers,
        "roles_summary": total_roles,
        "sweep": state,
        "message": msg,
    }
