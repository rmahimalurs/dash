"""Active Directory account unlock + password reset via LDAP.

- Unlock: resets ``lockoutTime`` to 0 (the standard AD "unlock account" op). Works
  over plain LDAP or LDAPS.
- Reset password: sets ``unicodePwd`` via ldap3's AD helper. AD **requires an
  encrypted channel** (LDAPS/StartTLS) for password writes, so this refuses to run
  over plain ldap://.

Both require a bind account with the matching delegated permission (Reset account
lockout / Reset password) over the target OU, and a *writable* domain controller on
389/636 — NOT the Global Catalog (3268), which is read-only for writes.

Safety: exactly ONE bind attempt per request, never retried, so a misconfigured bind
account cannot flood AD with failed binds and lock itself out.
"""
import logging
from datetime import datetime, timedelta, timezone

from ldap3 import Connection, SUBTREE, MODIFY_REPLACE
from ldap3.core.exceptions import LDAPBindError, LDAPException, LDAPSocketOpenError
from ldap3.extend.microsoft.modifyPassword import ad_modify_password

from app.config import get_settings
from app.ldap_util import make_ldap_server
from app.services.ldap_accounts import password_expiry_info, expiry_status

logger = logging.getLogger(__name__)

_INVALID_SAM_CHARS = "()*\\/,=+<>;\"\x00"


def _domain_root(base_dn: str) -> str:
    """Extract the DC=... domain root from a base DN."""
    parts = [p.strip() for p in base_dn.split(",") if p.strip().lower().startswith("dc=")]
    return ",".join(parts)


def _unlock_url(settings) -> str:
    if settings.AD_UNLOCK_URL:
        return settings.AD_UNLOCK_URL
    # Fall back to a writable-DC port (389), never the Global Catalog (3268).
    base = settings.LDAP_QUERY_URL or settings.LDAP_URL
    return base.replace(":3268", ":389")


# AD's own lockout bit on msDS-User-Account-Control-Computed.
UF_LOCKOUT = 0x10

# lockoutTime of zero is sent as the start of the FILETIME epoch, not as 0.
_FILETIME_EPOCH_YEAR = 1601


def _lockout_time(value) -> datetime | None:
    """When the account was locked, or None for "never".

    ldap3 hands lockoutTime back as a timezone-aware datetime, not the raw
    FILETIME integer, and a cleared lockout arrives as the 1601 epoch rather
    than 0 or an absent attribute. Both shapes are accepted because a raw
    integer still turns up when the attribute is read without ldap3's
    formatter.
    """
    if value in (None, "", 0, "0"):
        return None
    if isinstance(value, datetime):
        return None if value.year <= _FILETIME_EPOCH_YEAR else value
    try:
        ticks = int(str(value))
    except (TypeError, ValueError):
        return None
    if ticks <= 0:
        return None
    return datetime(1601, 1, 1, tzinfo=timezone.utc) + timedelta(microseconds=ticks // 10)


def _is_locked(computed_uac, lockout_time) -> bool:
    """Whether AD considers the account locked right now.

    Asks the domain controller rather than working it out here:
    msDS-User-Account-Control-Computed is constructed per-request and already
    accounts for the lockout duration having elapsed, whereas lockoutTime
    stays set after an account frees itself and would read as still locked for
    the rest of the window. lockoutTime is only consulted when the computed
    attribute is unavailable.
    """
    if computed_uac not in (None, ""):
        try:
            return bool(int(computed_uac) & UF_LOCKOUT)
        except (TypeError, ValueError):
            pass
    return _lockout_time(lockout_time) is not None


def _validate_sam(sam_account_name: str) -> str:
    sam = (sam_account_name or "").strip()
    if not sam:
        raise RuntimeError("Account name is required")
    if any(c in sam for c in _INVALID_SAM_CHARS):
        raise RuntimeError("Account name contains invalid characters")
    return sam


def _connect(settings, url: str) -> Connection:
    """Single, no-retry bind as the delegated unlock/reset service account."""
    if not settings.AD_UNLOCK_BIND_DN or not settings.AD_UNLOCK_BIND_PASSWORD:
        raise RuntimeError(
            "AD unlock service account is not configured (AD_UNLOCK_BIND_DN / AD_UNLOCK_BIND_PASSWORD)"
        )
    try:
        server = make_ldap_server(url, connect_timeout=8)
        return Connection(
            server,
            user=settings.AD_UNLOCK_BIND_DN,
            password=settings.AD_UNLOCK_BIND_PASSWORD,
            auto_bind=True,
            raise_exceptions=True,
        )
    except LDAPBindError as exc:
        logger.error("AD: bind failed for unlock/reset svc account: %s", exc)
        raise RuntimeError("AD service account bind failed (check the delegated svc account credentials)") from exc
    except LDAPSocketOpenError as exc:
        logger.error("AD: cannot reach %s: %s", url, exc)
        raise RuntimeError(f"Could not reach the domain controller at {url}") from exc


def _find(conn: Connection, search_base: str, sam: str):
    """Return the ldap3 entry for a sAMAccountName, or None."""
    found = conn.search(
        search_base=search_base,
        search_filter=f"(sAMAccountName={sam})",
        search_scope=SUBTREE,
        attributes=[
            "distinguishedName", "lockoutTime", "userAccountControl", "badPwdCount",
            "msDS-User-Account-Control-Computed", "msDS-UserPasswordExpiryTimeComputed",
        ],
    )
    if not found or not conn.entries:
        return None
    return conn.entries[0]


def get_ad_account_status(sam_account_name: str) -> dict:
    """Read-only lookup of an AD account's lockout state. Does NOT modify anything.

    Uses the same single, no-retry bind as the unlock path, so it cannot flood AD
    with failed binds. Returns the current ``is_locked`` flag plus ``badPwdCount``.
    """
    sam = _validate_sam(sam_account_name)
    settings = get_settings()
    url = _unlock_url(settings)
    search_base = settings.AD_UNLOCK_SEARCH_BASE or _domain_root(settings.LDAP_BASE_DN)

    conn = _connect(settings, url)
    try:
        entry = _find(conn, search_base, sam)
        if entry is None:
            return {
                "status": "not_found",
                "account": sam,
                "message": f"No AD account found with sAMAccountName '{sam}'.",
            }

        raw_lockout = entry.lockoutTime.value if "lockoutTime" in entry else None
        computed_uac = (
            entry["msDS-User-Account-Control-Computed"].value
            if "msDS-User-Account-Control-Computed" in entry else None
        )
        is_locked = _is_locked(computed_uac, raw_lockout)
        locked_at = _lockout_time(raw_lockout) if is_locked else None
        bad_pwd_count = entry.badPwdCount.value if "badPwdCount" in entry else None

        # Password-expiry state, computed from the same constructed attribute the
        # Service Account widget uses (the LDAPS DC on 636/389 exposes it; the GC
        # on 3268 does not). Reuses the shared pure helper so the logic can't drift.
        uac = entry.userAccountControl.value if "userAccountControl" in entry else None
        raw_expiry = (
            entry["msDS-UserPasswordExpiryTimeComputed"].value
            if "msDS-UserPasswordExpiryTimeComputed" in entry else None
        )
        pw = password_expiry_info(uac, raw_expiry)
        pw_status = expiry_status(pw)  # ok | warning | critical | expired | never_expires | unknown
        password_expired = pw_status == "expired"

        if is_locked:
            when = f" (locked at {locked_at:%Y-%m-%d %H:%M} UTC)" if locked_at else ""
            message = f"Account '{sam}' is currently locked{when}."
        elif password_expired:
            message = f"Account '{sam}' is not locked, but its password has expired."
        else:
            message = f"Account '{sam}' is not locked."

        return {
            "status": "found",
            "account": sam,
            "dn": str(entry.entry_dn),
            "is_locked": is_locked,
            "locked_at": locked_at.isoformat() if locked_at else None,
            "bad_pwd_count": bad_pwd_count,
            "password_expired": password_expired,
            "password_status": pw_status,
            "password_expiry_date": pw["expiry_date"],
            "password_days_remaining": pw["days_remaining"],
            "password_never_expires": pw["never_expires"],
            "message": message,
        }
    except LDAPException as exc:
        logger.error("AD status: LDAP error for %s: %s", sam, exc)
        raise RuntimeError(f"LDAP error while checking '{sam}': {exc}") from exc
    finally:
        try:
            conn.unbind()
        except Exception:
            pass


def unlock_ad_account(sam_account_name: str) -> dict:
    """Look up an AD account by sAMAccountName and clear its lockout."""
    sam = _validate_sam(sam_account_name)
    settings = get_settings()
    url = _unlock_url(settings)
    search_base = settings.AD_UNLOCK_SEARCH_BASE or _domain_root(settings.LDAP_BASE_DN)

    conn = _connect(settings, url)
    try:
        entry = _find(conn, search_base, sam)
        if entry is None:
            return {"status": "not_found", "account": sam, "message": f"No AD account found with sAMAccountName '{sam}'."}

        dn = str(entry.entry_dn)
        was_locked = _is_locked(
            entry["msDS-User-Account-Control-Computed"].value
            if "msDS-User-Account-Control-Computed" in entry else None,
            entry.lockoutTime.value if "lockoutTime" in entry else None,
        )

        ok = conn.modify(dn, {"lockoutTime": [(MODIFY_REPLACE, ["0"])]})
        if not ok:
            r = conn.result or {}
            raise RuntimeError(f"AD rejected the unlock (modify lockoutTime): {r.get('description')} - {r.get('message')}")

        logger.info("AD unlock: cleared lockout for %s (dn=%s, was_locked=%s)", sam, dn, was_locked)
        return {
            "status": "unlocked",
            "account": sam,
            "dn": dn,
            "was_locked": was_locked,
            "message": (
                f"Account '{sam}' was locked and has been unlocked."
                if was_locked
                else f"Account '{sam}' was not locked; lockout cleared anyway (no-op)."
            ),
        }
    except LDAPException as exc:
        logger.error("AD unlock: LDAP error for %s: %s", sam, exc)
        raise RuntimeError(f"LDAP error while unlocking '{sam}': {exc}") from exc
    finally:
        try:
            conn.unbind()
        except Exception:
            pass


def reset_ad_password(sam_account_name: str, new_password: str) -> dict:
    """Reset an AD account's password (unicodePwd). Requires an LDAPS bind URL.

    The password is passed straight to ldap3's AD helper and is never logged.
    """
    sam = _validate_sam(sam_account_name)
    if not new_password:
        raise RuntimeError("New password is required")

    settings = get_settings()
    url = _unlock_url(settings)
    if not url.lower().startswith("ldaps://"):
        raise RuntimeError(
            "AD password reset requires an encrypted connection. Set AD_UNLOCK_URL to an ldaps:// DC (port 636)."
        )
    search_base = settings.AD_UNLOCK_SEARCH_BASE or _domain_root(settings.LDAP_BASE_DN)

    conn = _connect(settings, url)
    try:
        entry = _find(conn, search_base, sam)
        if entry is None:
            return {"status": "not_found", "account": sam, "message": f"No AD account found with sAMAccountName '{sam}'."}

        dn = str(entry.entry_dn)
        ok = ad_modify_password(conn, dn, new_password, old_password=None)
        if not ok:
            r = conn.result or {}
            raise RuntimeError(
                f"AD rejected the password reset: {r.get('description')} - {r.get('message')} "
                "(check password complexity/history policy and that the svc account has Reset Password delegation)"
            )

        logger.info("AD reset: password reset for %s (dn=%s) by automation", sam, dn)
        return {"status": "reset", "account": sam, "dn": dn, "message": f"Password for '{sam}' has been reset."}
    except LDAPException as exc:
        logger.error("AD reset: LDAP error for %s: %s", sam, exc)
        raise RuntimeError(f"LDAP error while resetting '{sam}': {exc}") from exc
    finally:
        try:
            conn.unbind()
        except Exception:
            pass
