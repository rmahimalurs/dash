import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from ldap3 import Connection, Server, SUBTREE
from ldap3.core.exceptions import LDAPBindError, LDAPException, LDAPSocketOpenError

from app.config import get_settings
from app.ldap_util import make_ldap_server

logger = logging.getLogger(__name__)

# Cache service account results for 5 minutes to prevent bind flooding.
# A failed bind is also cached so a bad password doesn't retry on every page load.
_CACHE_TTL = timedelta(minutes=5)
_cache: dict[str, Any] = {"result": None, "fetched_at": None}

# Windows FILETIME: 100-ns ticks since 1601-01-01; subtract offset to get Unix epoch seconds
_FILETIME_EPOCH_DIFF = 116444736000000000
_FILETIME_NEVER = 9223372036854775807   # 0x7FFFFFFFFFFFFFFF — "never expires"
_UF_DONT_EXPIRE_PASSWD = 0x10000


def _filetime_to_dt(filetime: int) -> datetime | None:
    if filetime <= 0 or filetime == _FILETIME_NEVER:
        return None
    return datetime.fromtimestamp((filetime - _FILETIME_EPOCH_DIFF) / 10_000_000, tz=timezone.utc)


def password_expiry_info(uac, raw_expiry) -> dict:
    """Compute password-expiry info from an AD account's ``userAccountControl`` and
    ``msDS-UserPasswordExpiryTimeComputed`` values. Pure (no LDAP), so any caller
    that already has an entry (e.g. the AD unlock/status check) can reuse it.

    Returns ``{expiry_date, days_remaining, never_expires, error}``.
    """
    try:
        uac_int = int(uac) if uac is not None else 0
    except (TypeError, ValueError):
        uac_int = 0
    if uac_int & _UF_DONT_EXPIRE_PASSWD:
        return {"expiry_date": None, "days_remaining": None, "never_expires": True, "error": None}

    if raw_expiry is None:
        return {"expiry_date": None, "days_remaining": None, "never_expires": False, "error": "Expiry attribute unavailable"}

    try:
        filetime = int(raw_expiry)
    except (TypeError, ValueError):
        return {"expiry_date": None, "days_remaining": None, "never_expires": False, "error": "Could not parse expiry timestamp"}
    if filetime == _FILETIME_NEVER or filetime == 0:
        return {"expiry_date": None, "days_remaining": None, "never_expires": True, "error": None}

    expiry_dt = _filetime_to_dt(filetime)
    if expiry_dt is None:
        return {"expiry_date": None, "days_remaining": None, "never_expires": False, "error": "Could not parse expiry timestamp"}

    days_remaining = (expiry_dt - datetime.now(timezone.utc)).days
    return {
        "expiry_date": expiry_dt.isoformat(),
        "days_remaining": days_remaining,
        "never_expires": False,
        "error": None,
    }


def _query_one(conn: Connection, base_dn: str, sam: str) -> dict:
    conn.search(
        search_base=base_dn,
        search_filter=f"(sAMAccountName={sam})",
        search_scope=SUBTREE,
        attributes=["sAMAccountName", "msDS-UserPasswordExpiryTimeComputed", "userAccountControl"],
    )
    if not conn.entries:
        return {"expiry_date": None, "days_remaining": None, "never_expires": False, "error": "Account not found"}

    entry = conn.entries[0]
    uac = entry.userAccountControl.value if entry.userAccountControl else None
    raw = entry["msDS-UserPasswordExpiryTimeComputed"].value if "msDS-UserPasswordExpiryTimeComputed" in entry else None
    return password_expiry_info(uac, raw)


def expiry_status(info: dict) -> str:
    if info.get("error"):
        return "unknown"
    if info.get("never_expires"):
        return "never_expires"
    days = info.get("days_remaining")
    if days is None:
        return "unknown"
    if days <= 0:
        return "expired"
    if days < 14:
        return "critical"
    if days < 30:
        return "warning"
    return "ok"


def _error_row(label: str, sam: str, error: str) -> dict:
    return {
        "label": label,
        "username": sam or "(not configured)",
        "expiry_date": None,
        "days_remaining": None,
        "never_expires": False,
        "status": "unknown",
        "error": error,
    }


def get_service_account_expiry(accounts: list[tuple[str, str]], force_refresh: bool = False) -> list[dict]:
    """
    Check AD password expiry for a list of (display_label, sAMAccountName) pairs.
    Opens one LDAP connection (port 389) and queries all accounts in sequence.
    Results are cached for 5 minutes to prevent bind flooding against AD.
    """
    now = datetime.now(timezone.utc)
    if not force_refresh and _cache["result"] is not None and _cache["fetched_at"] is not None:
        if now - _cache["fetched_at"] < _CACHE_TTL:
            return _cache["result"]

    result = _fetch_service_account_expiry(accounts)
    _cache["result"] = result
    _cache["fetched_at"] = now
    return result


def _fetch_service_account_expiry(accounts: list[tuple[str, str]]) -> list[dict]:
    settings = get_settings()

    if settings.DEV_MODE:
        return [_error_row(label, sam, "DEV_MODE: LDAP unavailable") for label, sam in accounts]

    # GC port 3268 doesn't expose msDS-UserPasswordExpiryTimeComputed; use 389
    query_url = settings.LDAP_QUERY_URL or settings.LDAP_URL.replace(":3268", ":389")

    try:
        server = make_ldap_server(query_url, connect_timeout=5)
        with Connection(server, user=settings.LDAP_BIND_DN, password=settings.LDAP_BIND_PASSWORD, auto_bind=True) as conn:
            results = []
            for label, sam in accounts:
                if not sam:
                    results.append(_error_row(label, sam, "Username not configured"))
                    continue
                try:
                    info = _query_one(conn, settings.LDAP_BASE_DN, sam)
                except LDAPException as exc:
                    logger.error("LDAP query failed for %s: %s", sam, exc)
                    results.append(_error_row(label, sam, str(exc)))
                    continue
                results.append({
                    "label": label,
                    "username": sam,
                    "expiry_date": info.get("expiry_date"),
                    "days_remaining": info.get("days_remaining"),
                    "never_expires": info.get("never_expires", False),
                    "status": expiry_status(info),
                    "error": info.get("error"),
                })
            return results

    except LDAPSocketOpenError as exc:
        logger.error("LDAP: cannot connect to %s: %s", query_url, exc)
        return [_error_row(l, s, f"Cannot connect to LDAP: {exc}") for l, s in accounts]
    except LDAPBindError as exc:
        logger.error("LDAP: bind failed: %s", exc)
        return [_error_row(l, s, f"LDAP bind failed") for l, s in accounts]
    except LDAPException as exc:
        logger.error("LDAP: unexpected error: %s", exc)
        return [_error_row(l, s, str(exc)) for l, s in accounts]


# ─── Account deactivation (ACCOUNTDISABLE) ────────────────────────────────────

_UF_ACCOUNTDISABLE = 0x0002


def _ldap_escape(value: str) -> str:
    """Escape LDAP filter special chars (RFC 4515) in a sAMAccountName."""
    out = []
    for ch in value:
        if ch in "\\*()\x00":
            out.append("\\%02x" % ord(ch))
        else:
            out.append(ch)
    return "".join(out)


def get_groups(sams: list[str]) -> dict[str, list[str]]:
    """Return {sam_lower: [group CN, ...]} for a list of sAMAccountNames.

    One read-only bind with batched searches, same shape as
    get_disabled_status, so it cannot contribute to an AD lockout. Used to
    guess which application a GitHub request belongs to when the ticket does
    not say: CMS group names encode it, as in ct-ado-<application>-<role>.
    """
    uniq = sorted({(s or "").strip() for s in sams if s and s.strip()})
    if not uniq:
        return {}

    settings = get_settings()
    if settings.DEV_MODE:
        return {}

    query_url = settings.LDAP_QUERY_URL or settings.LDAP_URL.replace(":3268", ":389")
    out: dict[str, list[str]] = {}
    try:
        server = make_ldap_server(query_url, connect_timeout=5)
        with Connection(server, user=settings.LDAP_BIND_DN,
                        password=settings.LDAP_BIND_PASSWORD, auto_bind=True) as conn:
            for i in range(0, len(uniq), 50):
                chunk = uniq[i:i + 50]
                filt = "(|" + "".join(f"(sAMAccountName={_ldap_escape(s)})" for s in chunk) + ")"
                conn.search(search_base=settings.LDAP_BASE_DN, search_filter=filt,
                            search_scope=SUBTREE,
                            attributes=["sAMAccountName", "memberOf", "department"])
                for e in conn.entries:
                    sam = str(e.sAMAccountName.value).lower()
                    groups = list(e.memberOf.values) if "memberOf" in e else []
                    cns = []
                    for dn in groups:
                        m = re.match(r"CN=([^,]+)", str(dn))
                        if m:
                            cns.append(m.group(1))
                    out[sam] = cns
    except (LDAPSocketOpenError, LDAPBindError) as exc:
        logger.error("LDAP group bind/connect failed: %s", exc)
        return {}
    except LDAPException as exc:
        logger.error("LDAP group lookup error: %s", exc)
        return {}
    return out


def get_mail(sams: list[str]) -> dict[str, dict]:
    """Return {sam_lower: {'mail', 'display_name'}} for a list of sAMAccountNames.

    One read-only bind and batched searches, exactly as get_disabled_status
    does, so this cannot contribute to an AD lockout. Accounts AD does not
    return are simply absent from the result.
    """
    uniq = sorted({(s or "").strip() for s in sams if s and s.strip()})
    if not uniq:
        return {}

    settings = get_settings()
    if settings.DEV_MODE:
        return {}

    query_url = settings.LDAP_QUERY_URL or settings.LDAP_URL.replace(":3268", ":389")
    out: dict[str, dict] = {}
    try:
        server = make_ldap_server(query_url, connect_timeout=5)
        with Connection(server, user=settings.LDAP_BIND_DN,
                        password=settings.LDAP_BIND_PASSWORD, auto_bind=True) as conn:
            for i in range(0, len(uniq), 50):
                chunk = uniq[i:i + 50]
                filt = "(|" + "".join(f"(sAMAccountName={_ldap_escape(s)})" for s in chunk) + ")"
                conn.search(search_base=settings.LDAP_BASE_DN, search_filter=filt,
                            search_scope=SUBTREE,
                            attributes=["sAMAccountName", "mail", "displayName"])
                for e in conn.entries:
                    sam = str(e.sAMAccountName.value).lower()
                    out[sam] = {
                        "mail": str(e.mail.value) if "mail" in e and e.mail.value else None,
                        "display_name": str(e.displayName.value) if "displayName" in e and e.displayName.value else None,
                    }
    except (LDAPSocketOpenError, LDAPBindError) as exc:
        logger.error("LDAP mail bind/connect failed: %s", exc)
        return {}
    except LDAPException as exc:
        logger.error("LDAP mail lookup error: %s", exc)
        return {}
    return out


def get_disabled_status(sams: list[str]) -> dict[str, str]:
    """Return {sam_lower: 'disabled' | 'active' | 'not_found' | 'unknown'} for a
    list of sAMAccountNames.

    One read-only bind (LDAP_BIND_DN on the query URL) + batched searches on the
    ACCOUNTDISABLE bit of userAccountControl — never a per-user bind, so it can't
    flood AD. Any account not returned by AD is 'not_found'. On connection/bind
    failure every account is 'unknown' (callers must treat unknown as NOT
    deactivated, i.e. do not exclude/delete on uncertainty).
    """
    uniq = sorted({(s or "").strip() for s in sams if s and s.strip()})
    if not uniq:
        return {}

    settings = get_settings()
    if settings.DEV_MODE:
        return {s.lower(): "unknown" for s in uniq}

    query_url = settings.LDAP_QUERY_URL or settings.LDAP_URL.replace(":3268", ":389")
    out: dict[str, str] = {s.lower(): "not_found" for s in uniq}
    try:
        server = make_ldap_server(query_url, connect_timeout=5)
        with Connection(server, user=settings.LDAP_BIND_DN,
                        password=settings.LDAP_BIND_PASSWORD, auto_bind=True) as conn:
            for i in range(0, len(uniq), 50):
                chunk = uniq[i:i + 50]
                filt = "(|" + "".join(f"(sAMAccountName={_ldap_escape(s)})" for s in chunk) + ")"
                conn.search(search_base=settings.LDAP_BASE_DN, search_filter=filt,
                            search_scope=SUBTREE,
                            attributes=["sAMAccountName", "userAccountControl"])
                for e in conn.entries:
                    sam = str(e.sAMAccountName.value).lower()
                    uac = e.userAccountControl.value if "userAccountControl" in e else None
                    try:
                        disabled = bool(int(uac) & _UF_ACCOUNTDISABLE)
                    except (TypeError, ValueError):
                        disabled = False
                    out[sam] = "disabled" if disabled else "active"
    except (LDAPSocketOpenError, LDAPBindError) as exc:
        logger.error("LDAP disabled-status bind/connect failed: %s", exc)
        return {s.lower(): "unknown" for s in uniq}
    except LDAPException as exc:
        logger.error("LDAP disabled-status error: %s", exc)
        return {s.lower(): "unknown" for s in uniq}
    return out
