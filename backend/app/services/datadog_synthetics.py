"""Datadog Synthetics service-account rotation helpers.

The DevOps team's Datadog Synthetic tests log into CMS apps using two AD service
accounts, ``dso-synthetics-a`` and ``dso-synthetics-b``. Each account's password
is stored as a *secure Datadog Global Variable* (Org Settings > Synthetic Tests >
Global Variables) that the tests read at runtime. Rotating an account therefore
means: reset the AD password (elsewhere), then write the new password into the
matching global variable here.

The generic rotation core (`_rotate_svc_account` in routers/automation.py) drives
this via two callables, both keyed by the selector ``sel`` ("a" | "b"):
  - ``update_global_variable(sel, password)`` — the "tool update" step.
  - ``test_synthetics_ldap(sel, password)``   — a soft LDAP-bind verification.
"""
import logging

import httpx
from ldap3 import Connection
from ldap3.core.exceptions import LDAPException

from app.config import get_settings
from app.ldap_util import make_ldap_server

logger = logging.getLogger(__name__)


def _dd_headers() -> dict:
    s = get_settings()
    return {
        "DD-API-KEY": s.DATADOG_API_KEY,
        "DD-APPLICATION-KEY": s.DATADOG_APP_KEY,
        "Content-Type": "application/json",
    }


def _resolve(sel: str) -> tuple[str, str]:
    """Map a selector to (sAMAccountName, datadog_variable_id). Raises on bad input."""
    s = get_settings()
    table = {
        "a": (s.SA_DATADOG_SYNTHETICS_PROD, s.DATADOG_SYNTHETICS_VAR_A),
        "b": (s.SA_DATADOG_SYNTHETICS_DEV, s.DATADOG_SYNTHETICS_VAR_B),
    }
    key = (sel or "").strip().lower()
    if key not in table:
        raise ValueError("Datadog synthetics selector must be 'a' or 'b'")
    return table[key]


def account_for(sel: str) -> str:
    """The AD sAMAccountName rotated for this selector (used for the AD reset)."""
    return _resolve(sel)[0]


def _upn_suffix() -> str:
    """Derive the UPN domain (e.g. awscloud.cms.local) from the configured base DN."""
    base = get_settings().LDAP_BASE_DN or ""
    dcs = [p.split("=", 1)[1] for p in base.split(",") if p.strip().lower().startswith("dc=")]
    return ".".join(dcs) if dcs else "awscloud.cms.local"


def update_global_variable(sel: str, password: str) -> dict:
    """Write ``password`` into the Datadog secure global variable for this SA.

    GETs the current variable to preserve its name/description/tags, then PUTs it
    back with the new secure value. Raises RuntimeError on any non-2xx so the
    rotation core records it as a tool error (the account is still rotated in AD).
    """
    s = get_settings()
    if not (s.DATADOG_API_KEY and s.DATADOG_APP_KEY):
        raise RuntimeError("Datadog API/APP keys are not configured")
    _, var_id = _resolve(sel)
    base = s.DATADOG_API_BASE
    url = f"{base}/api/v1/synthetics/variables/{var_id}"

    cur = httpx.get(url, headers=_dd_headers(), timeout=20, verify=True)
    if not cur.is_success:
        raise RuntimeError(f"Datadog GET variable {var_id} failed: {cur.status_code}: {cur.text[:300]}")
    v = cur.json()

    payload = {
        "name": v.get("name"),
        "description": v.get("description") or "",
        "tags": v.get("tags") or [],
        "value": {"secure": True, "value": password},
    }
    resp = httpx.put(url, json=payload, headers=_dd_headers(), timeout=20, verify=True)
    if not resp.is_success:
        raise RuntimeError(f"Datadog PUT variable {var_id} failed: {resp.status_code}: {resp.text[:300]}")

    return {
        "ok": True,
        "id": var_id,
        "name": v.get("name"),
        "status_code": resp.status_code,
        "message": f"Updated Datadog global variable {v.get('name')}",
    }


def test_synthetics_ldap(sel: str, password: str) -> dict:
    """Soft verification: attempt a single LDAP simple bind as the SA with the new
    password. Never raises — a failure is reported, not fatal (the caller does not
    gate the Datadog write on this). One bind, no retry (AD-lockout safety)."""
    s = get_settings()
    sam, _ = _resolve(sel)
    url = s.AD_UNLOCK_URL or (s.LDAP_QUERY_URL or s.LDAP_URL)
    user = f"{sam}@{_upn_suffix()}"
    conn = None
    try:
        server = make_ldap_server(url, connect_timeout=8)
        conn = Connection(server, user=user, password=password, auto_bind=True, raise_exceptions=True)
        return {"ok": True, "message": f"LDAP bind succeeded for {user}"}
    except LDAPException as exc:
        logger.warning("Synthetics LDAP bind failed for %s: %s", user, exc)
        return {"ok": False, "message": f"LDAP bind failed for {user}: {exc}"}
    except Exception as exc:  # noqa: BLE001 — verification must never break the rotation
        logger.warning("Synthetics LDAP verify error for %s: %s", user, exc)
        return {"ok": False, "message": f"LDAP verify error: {exc}"}
    finally:
        try:
            if conn is not None:
                conn.unbind()
        except Exception:  # noqa: BLE001
            pass
