import logging
from ldap3 import Server, Connection, ALL, NTLM, SUBTREE, ALL_ATTRIBUTES
from app.ldap_util import make_ldap_server
from ldap3.core.exceptions import LDAPException, LDAPBindError, LDAPSocketOpenError

from app.config import get_settings

logger = logging.getLogger(__name__)


class AccountStateError(Exception):
    """AD rejected the bind for a reason the user can act on.

    AD reports why in its bind error ("... data 775 ..."), but every one of
    those arrives as the same LDAPBindError, so without reading the sub-code
    a locked account, an expired password and a genuinely wrong password are
    indistinguishable on the login page. That cost real debugging time.
    """

    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason
        self.message = message


# AD's sub-codes, as they appear in the bind error's diagnostic string.
_AD_BIND_REASONS: dict[str, tuple[str, str]] = {
    "525": ("user_not_found", "That account does not exist in Active Directory."),
    "530": ("logon_time_restricted", "Your account is not permitted to sign in at this time."),
    "531": ("workstation_restricted", "Your account is not permitted to sign in from here."),
    "532": ("password_expired",
            "Your Active Directory password has expired. Reset it, then sign in again."),
    "533": ("account_disabled", "Your Active Directory account is disabled."),
    "701": ("account_expired", "Your Active Directory account has expired."),
    "773": ("password_must_change",
            "Your Active Directory password must be changed before you can sign in."),
    "775": ("account_locked",
            "Your Active Directory account is locked. It unlocks on its own 120 minutes "
            "after the last failed attempt, or a teammate can clear it from the "
            "Automation page."),
}


def _bind_failure_reason(exc: Exception) -> tuple[str, str] | None:
    """The reason behind a bind rejection, when AD names one.

    52e is a plain wrong password and is deliberately absent from the table:
    it needs no special message, and naming it would only tell someone
    guessing that the account itself exists.
    """
    text = str(exc)
    for code, reason in _AD_BIND_REASONS.items():
        if f"data {code}" in text:
            return reason
    return None


class AccessGroupError(Exception):
    """Raised when a user's credentials are valid but they are not a member of
    the required AD access group. Distinct from a plain None (bad credentials)
    so the router can surface a specific 'not in the Access group' message."""


def authenticate_user(username: str, password: str) -> dict | None:
    settings = get_settings()
    if settings.DEV_MODE:
        logger.warning("DEV_MODE: bypassing LDAP for user '%s'", username)
        return {
            "username": username,
            "display_name": username.replace(".", " ").title(),
            "email": f"{username}@cms.hhs.gov",
            "groups": ["cms-cloud-devops"],
        }

    """
    Authenticate a user against Active Directory via LDAP.

    Returns a dict with username, display_name, email, and groups on success.
    Returns None if authentication fails or the user is not found.
    """
    settings = get_settings()

    if not username or not password:
        return None

    # Build the bind DN for the service account
    # The template uses {AD_SA_USERNAME} placeholder which comes from env
    service_bind_dn = settings.LDAP_BIND_DN  # e.g. svcaccount@awscloud.cms.local

    try:
        server = make_ldap_server(settings.LDAP_URL, get_info=ALL, connect_timeout=5)

        # Bind with service account to search for the user
        with Connection(
            server,
            user=service_bind_dn,
            password=settings.LDAP_BIND_PASSWORD,
            auto_bind=True,
        ) as service_conn:
            # Search for the user by sAMAccountName
            search_filter = f"(sAMAccountName={username})"
            service_conn.search(
                search_base=settings.LDAP_BASE_DN,
                search_filter=search_filter,
                search_scope=SUBTREE,
                attributes=["distinguishedName", "displayName", "mail", "memberOf", "sAMAccountName"],
            )

            if not service_conn.entries:
                logger.warning("LDAP: user not found: %s", username)
                return None

            entry = service_conn.entries[0]
            user_dn = str(entry.distinguishedName)

    except LDAPSocketOpenError as exc:
        logger.error("LDAP: cannot connect to server %s: %s", settings.LDAP_URL, exc)
        return None
    except LDAPBindError as exc:
        logger.error("LDAP: service account bind failed: %s", exc)
        return None
    except LDAPException as exc:
        logger.error("LDAP: unexpected error during user search: %s", exc)
        return None

    # Now bind as the actual user to verify their password
    try:
        server = make_ldap_server(settings.LDAP_URL, get_info=ALL, connect_timeout=5)
        with Connection(
            server,
            user=user_dn,
            password=password,
            auto_bind=True,
        ) as user_conn:
            if not user_conn.bound:
                logger.info("LDAP: authentication failed for user: %s", username)
                return None

            # Extract attributes from the earlier search entry
            display_name = str(entry.displayName) if entry.displayName else username
            email = str(entry.mail) if entry.mail else ""

            # AD matches sAMAccountName case-insensitively, so take the spelling
            # from AD rather than the login form: keying roles and profiles off
            # what was typed created one identity per casing.
            canonical = str(entry.sAMAccountName) if entry.sAMAccountName else username

            raw_groups = entry.memberOf.values if entry.memberOf else []
            groups = [_parse_cn(g) for g in raw_groups]

            # Access-group gate: credentials are valid, but only members of the
            # configured AD group are allowed into the dashboard.
            required_group = _parse_cn(settings.LDAP_ACCESS_GROUP.strip())
            if required_group:
                member_cns = {g.lower() for g in groups}
                if required_group.lower() not in member_cns:
                    logger.warning(
                        "LDAP: user '%s' authenticated but is not a member of access group '%s'",
                        username, required_group,
                    )
                    raise AccessGroupError(required_group)

            logger.info("LDAP: authentication successful for user: %s", canonical)
            return {
                "username": canonical,
                "display_name": display_name,
                "email": email,
                "groups": groups,
            }

    except LDAPBindError as exc:
        found = _bind_failure_reason(exc)
        if found:
            reason, message = found
            logger.info("LDAP: bind refused for user %s: %s", username, reason)
            raise AccountStateError(reason, message) from exc
        logger.info("LDAP: invalid password for user: %s", username)
        return None
    except LDAPException as exc:
        logger.error("LDAP: error during user bind: %s", exc)
        return None


def _parse_cn(distinguished_name: str) -> str:
    """Extract the CN value from a distinguished name string."""
    for part in distinguished_name.split(","):
        part = part.strip()
        if part.upper().startswith("CN="):
            return part[3:]
    return distinguished_name
