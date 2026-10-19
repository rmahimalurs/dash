import copy
import logging

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

# LDAP settings templates sourced from Confluence runbook:
# "Runbook: Artifactory Product Configuration" (ID: 57727873)
# PUT /access/api/v1/ldap/settings   Authorization: Bearer <jfrog-admin-token>
_LDAP_TEMPLATES: dict = {
    "prod": {
        "key": "CMS-LDAP",
        "enabled": True,
        "ldap_url": "ldaps://e1ss-prd-dmc02.awscloud.cms.local/DC=awscloud,DC=cms,DC=local",
        "user_dn_pattern": "",
        "search": {
            "search_filter": "(&(objectClass=User)(sAMAccountName={0}))",
            "search_base": "OU=Accounts,OU=CMS",
            "search_sub_tree": True,
            "manager_dn": "jfrog-svc-prod",
            "manager_password": None,
        },
        "auto_create_user": True,
        "email_attribute": "mail",
        "ldap_poisoning_protection": False,
        "allow_user_to_access_profile": True,
        "paging_support_enabled": True,
    },
    "dev": {
        "key": "CMS-LDAP",
        "enabled": True,
        "ldap_url": "ldaps://e1ss-prd-dmc02.awscloud.cms.local/DC=awscloud,DC=cms,DC=local",
        "user_dn_pattern": "",
        "search": {
            "search_filter": "(&(objectClass=User)(sAMAccountName={0}))",
            "search_base": "OU=Accounts,OU=CMS",
            "search_sub_tree": True,
            "manager_dn": "dso-ss-jfrog-dev",
            "manager_password": None,
        },
        "auto_create_user": True,
        "email_attribute": "mail",
        "ldap_poisoning_protection": False,
        "allow_user_to_access_profile": True,
        "paging_support_enabled": True,
    },
}


def _resolve_env(env: str) -> tuple[str, str, str]:
    """Return (base_url, admin_token, manager_account) for env."""
    settings = get_settings()
    if env == "prod":
        token = settings.ARTIFACTORY_PROD_ADMIN_TOKEN
        if not token:
            raise RuntimeError("ARTIFACTORY_PROD_ADMIN_TOKEN is not configured")
        return settings.ARTIFACTORY_PROD_URL, token, settings.SA_ARTIFACTORY_PROD
    if env == "dev":
        token = settings.ARTIFACTORY_DEV_TOKEN
        if not token:
            raise RuntimeError("ARTIFACTORY_DEV_TOKEN is not configured")
        return settings.ARTIFACTORY_DEV_URL, token, settings.SA_ARTIFACTORY_DEV
    raise ValueError(f"Unknown env: {env!r}")


def _build_ldap_settings(env: str, new_password: str) -> dict:
    payload = copy.deepcopy(_LDAP_TEMPLATES[env])
    payload["search"]["manager_password"] = new_password
    return payload


def get_jfrog_manager_account(env: str) -> str:
    """Return the AD service account name JFrog binds as for this env."""
    if env not in _LDAP_TEMPLATES:
        raise ValueError(f"Unknown env: {env!r}")
    return _LDAP_TEMPLATES[env]["search"]["manager_dn"]


def test_jfrog_ldap_credentials(env: str, new_password: str) -> dict:
    """
    Validate the candidate LDAP manager password before saving by binding
    directly against AD via ldap3.

    We deliberately do NOT use JFrog's /access/api/v1/ldap/settings/test
    endpoint: it returns "Failed to authenticate user" even when the password
    is correct if the username and manager_dn refer to the same account
    (which they do in our flow). Going through ldap3 against the same AD
    forest JFrog binds to gives a clean true/false answer with a real
    underlying error message on failure.

    Returns {ok: bool, message: str, status_code: int | None}.
    status_code is always None here (we don't go through HTTP); the field
    is retained for the response shape the frontend expects.
    """
    settings = get_settings()
    _base_url, _token, account = _resolve_env(env)
    upn = f"{account}@awscloud.cms.local"

    try:
        from ldap3 import Server, Connection

        from app.ldap_util import make_ldap_server
        from ldap3.core.exceptions import LDAPBindError, LDAPException, LDAPSocketOpenError
    except ImportError:
        return {"ok": False, "message": "ldap3 is not installed in this build", "status_code": None}

    # AD sub-status codes carried in the diagnosticMessage of an
    # invalidCredentials response. The user wants to know whether they typed
    # the wrong password vs. the account is expired/locked/disabled.
    AD_CODES = {
        "525": "user not found",
        "52e": "invalid credentials (bad password)",
        "530": "not permitted to logon at this time",
        "531": "not permitted to logon from this workstation",
        "532": "password expired",
        "533": "account disabled",
        "701": "account expired",
        "773": "must change password at next logon",
        "775": "account locked out",
    }

    try:
        server = make_ldap_server(settings.LDAP_URL, connect_timeout=5)
        conn = Connection(server, user=upn, password=new_password)
        bound = conn.bind()
        if bound:
            conn.unbind()
            return {
                "ok":          True,
                "message":     f"LDAP bind succeeded as {upn} against {settings.LDAP_URL}",
                "status_code": None,
            }

        # Bind returned False — extract the most specific reason AD gave us.
        result = conn.result or {}
        desc = result.get("description") or "bind failed"
        diag = result.get("message") or ""
        # AD diagnosticMessage looks like: "80090308: LdapErr: ..., data 52e, v23f0"
        ad_reason = None
        for code, label in AD_CODES.items():
            if f"data {code}" in diag.lower():
                ad_reason = f"{label} (AD code {code})"
                break

        msg = f"AD rejected {upn}: {desc}"
        if ad_reason:
            msg += f" — {ad_reason}"
        elif diag:
            msg += f" — {diag[:200]}"
        return {"ok": False, "message": msg, "status_code": None}
    except LDAPBindError as exc:
        return {"ok": False, "message": f"AD bind error for {upn}: {exc}", "status_code": None}
    except LDAPSocketOpenError as exc:
        return {"ok": False, "message": f"Could not reach LDAP server {settings.LDAP_URL}: {exc}", "status_code": None}
    except LDAPException as exc:
        return {"ok": False, "message": f"LDAP error: {exc}", "status_code": None}
    except Exception as exc:
        return {"ok": False, "message": f"Unexpected error: {exc}", "status_code": None}


def update_jfrog_ldap_password(env: str, new_password: str) -> dict:
    """
    Update the LDAP manager password in Artifactory via the JFrog Access API.
    Password is never logged.
    """
    base_url, token, _account = _resolve_env(env)

    payload = _build_ldap_settings(env, new_password)

    resp = httpx.put(
        f"{base_url}/access/api/v1/ldap/settings",
        json=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        timeout=20,
        verify=True,
    )

    if not resp.is_success:
        raise RuntimeError(
            f"Artifactory LDAP API returned {resp.status_code}: {resp.text[:400]}"
        )

    logger.info("JFrog %s LDAP manager password updated by automation", env)
    return {"status": "ok", "env": env, "account": _LDAP_TEMPLATES[env]["search"]["manager_dn"]}


def unlock_artifactory_user(env: str, username: str) -> dict:
    """Unlock a locked-out Artifactory user via the security API.

    POST /artifactory/api/security/unlockUsers/{user} with the admin Bearer token.
    Idempotent — unlocking a user that is not locked returns success.
    """
    username = (username or "").strip()
    if not username:
        raise RuntimeError("Username is required")

    base_url, token, _account = _resolve_env(env)

    resp = httpx.post(
        f"{base_url}/artifactory/api/security/unlockUsers/{username}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=20,
        verify=True,
    )

    if not resp.is_success:
        raise RuntimeError(
            f"Artifactory unlock API returned {resp.status_code}: {resp.text[:400]}"
        )

    logger.info("Artifactory %s user %s unlocked by automation", env, username)
    return {"status": "ok", "env": env, "username": username}
