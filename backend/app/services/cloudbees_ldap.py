"""
CloudBees Jenkins LDAP manager password rotation.

Covers four CJOCs:
  dev-east, prod-east, gc-dev-west, gc-prod-west

Reads the current manager DN by running Groovy on the CJOC's Script Console,
validates a candidate new password via direct ldap3 bind against AD, then
saves to the CJOC by running another Groovy script that reflects on each
LDAPConfiguration in the security realm and replaces its
`managerPasswordSecret` field. The reflection approach avoids the
constructor-signature drift that the Jenkins LDAP plugin has historically
had across versions.
"""

from __future__ import annotations

import logging
import re

from app.config import get_settings
from app.services.jenkins import run_groovy_script

logger = logging.getLogger(__name__)


# ─── Environment registry ─────────────────────────────────────────────────────

# Public env keys used by the frontend dropdown. The label is what gets
# rendered. The url + auth tuple keys resolve from runtime Settings.
_ENVS: dict[str, dict] = {
    "dev-east":     {"label": "Dev East",          "url_attr": "CLOUDBEES_EAST_DEV_URL",  "user_attr": "JENKINS_DEV_USER",  "token_attrs": ["JENKINS_EAST_DEV_TOKEN"]},
    "prod-east":    {"label": "Prod East",         "url_attr": "CLOUDBEES_EAST_PROD_URL", "user_attr": "JENKINS_PROD_USER", "token_attrs": ["JENKINS_EAST_PROD_TOKEN"]},
    "gc-dev-west":  {"label": "GovCloud Dev West", "url_attr": "CLOUDBEES_GOV_DEV_URL",   "user_attr": "JENKINS_DEV_USER",  "token_attrs": ["JENKINS_GOV_DEV_TOKEN"]},
    "gc-prod-west": {"label": "GovCloud Prod West","url_attr": "CLOUDBEES_GOV_PROD_URL",  "user_attr": "JENKINS_PROD_USER", "token_attrs": ["JENKINS_GOV_PROD_TOKEN"]},
}


def known_envs() -> list[dict]:
    return [{"key": k, "label": v["label"]} for k, v in _ENVS.items()]


def _resolve_env(env: str) -> tuple[str, tuple[str, str]]:
    """Return (cjoc_url, (user, token)) for env."""
    if env not in _ENVS:
        raise ValueError(f"Unknown env: {env!r}")
    cfg = _ENVS[env]
    settings = get_settings()
    url = getattr(settings, cfg["url_attr"], "") or ""
    if not url:
        raise RuntimeError(f"{cfg['url_attr']} is not configured")
    user = getattr(settings, cfg["user_attr"], "") or ""
    token = ""
    for attr in cfg["token_attrs"]:
        token = getattr(settings, attr, "") or ""
        if token:
            break
    if not user or not token:
        raise RuntimeError(f"No credentials configured for env {env!r}")
    return url, (user, token)


# ─── Discover current LDAP manager DN ─────────────────────────────────────────

_GROOVY_DISCOVER_LDAP = r"""
import jenkins.model.Jenkins
import hudson.security.LDAPSecurityRealm

def realm = Jenkins.instance.getSecurityRealm()
if (realm == null) { println "NO_REALM"; return }
if (!(realm instanceof LDAPSecurityRealm)) {
  println "NOT_LDAP_REALM: " + realm.class.name
  return
}

def confs = []
try { confs = realm.getConfigurations() ?: [] } catch (Throwable ignored) {}
if (confs.isEmpty()) {
  println "NO_CONFIGS"
  return
}

def first = confs[0]
def managerDN = ""
def server    = ""
try { managerDN = first.getManagerDN() ?: "" } catch (Throwable ignored) {}
try { server    = first.getServer() ?: "" } catch (Throwable ignored) {}

println "MANAGER_DN=" + managerDN
println "LDAP_URL=" + server
println "CONFIG_COUNT=" + confs.size()
"""


def _detect_groovy_trace(out: str) -> str | None:
    if "Exception" in out and ("at " in out or "Script1.groovy" in out):
        first = out.splitlines()[0] if out.splitlines() else "Groovy error"
        return first[:200]
    return None


def discover_manager_account(env: str) -> dict:
    """Return the LDAP manager DN currently configured on the CJOC."""
    url, auth = _resolve_env(env)
    try:
        out = run_groovy_script(url, _GROOVY_DISCOVER_LDAP, auth=auth)
    except Exception as exc:
        logger.warning("CloudBees %s LDAP discovery failed: %s", env, exc)
        return {"account": None, "ldap_url": None, "error": f"CJOC lookup failed: {exc}"}

    out = (out or "").strip()
    if out.startswith("NO_REALM"):
        return {"account": None, "ldap_url": None, "error": "CJOC has no security realm configured"}
    if out.startswith("NOT_LDAP_REALM"):
        return {"account": None, "ldap_url": None, "error": out}
    if out == "NO_CONFIGS":
        return {"account": None, "ldap_url": None, "error": "LDAP realm has no configurations"}
    trace = _detect_groovy_trace(out)
    if trace:
        return {"account": None, "ldap_url": None, "error": f"Groovy error: {trace}"}

    parsed: dict[str, str] = {}
    for line in out.splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            parsed[k.strip()] = v.strip()

    manager_dn = parsed.get("MANAGER_DN") or None
    ldap_url   = parsed.get("LDAP_URL") or None
    if not manager_dn:
        return {"account": None, "ldap_url": ldap_url, "error": "Manager DN not set on CJOC LDAP config"}

    # If the manager DN is a full LDAP DN (CN=svc-foo,OU=..), extract the CN
    # for display; otherwise show as-is. The full DN is what we keep for save.
    short = manager_dn
    m = re.match(r"^CN=([^,]+),", manager_dn, re.IGNORECASE)
    if m:
        short = m.group(1)

    return {
        "account":      short,
        "account_full": manager_dn,
        "ldap_url":     ldap_url,
        "error":        None,
    }


# ─── Test new credentials via ldap3 bind ──────────────────────────────────────

# AD sub-status codes carried in the diagnosticMessage of an invalidCredentials response
_AD_CODES = {
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


def test_credentials(env: str, new_password: str) -> dict:
    """
    Validate a candidate LDAP manager password by binding directly against AD
    via ldap3. Same path the dashboard's own login flow uses; same AD forest
    each CJOC binds to. Returns {ok, message, status_code: None}.
    """
    account_info = discover_manager_account(env)
    if account_info.get("error") or not account_info.get("account"):
        return {"ok": False, "message": account_info.get("error", "Unknown manager account"), "status_code": None}

    settings = get_settings()
    # AD bind uses the userPrincipalName form; extract the sAMAccountName from the CN/short form
    short_name = account_info["account"]
    upn = f"{short_name}@awscloud.cms.local"

    try:
        from ldap3 import Server, Connection

        from app.ldap_util import make_ldap_server
        from ldap3.core.exceptions import LDAPBindError, LDAPException, LDAPSocketOpenError
    except ImportError:
        return {"ok": False, "message": "ldap3 not installed", "status_code": None}

    try:
        server = make_ldap_server(settings.LDAP_URL, connect_timeout=5)
        conn = Connection(server, user=upn, password=new_password)
        if conn.bind():
            conn.unbind()
            return {
                "ok":          True,
                "message":     f"LDAP bind succeeded as {upn} against {settings.LDAP_URL}",
                "status_code": None,
            }

        result = conn.result or {}
        desc = result.get("description") or "bind failed"
        diag = (result.get("message") or "").lower()
        ad_reason = None
        for code, label in _AD_CODES.items():
            if f"data {code}" in diag:
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


# ─── Update password on the CJOC ──────────────────────────────────────────────

# Reflection-based update: walk each LDAPConfiguration in the security realm
# and replace the private `managerPasswordSecret` field. Avoids constructor
# signature drift across LDAP-plugin versions.
_GROOVY_UPDATE_LDAP_PASSWORD = r"""
import hudson.util.Secret
import jenkins.model.Jenkins
import hudson.security.LDAPSecurityRealm
import java.lang.reflect.Field

def newPassword = '__NEW_PASSWORD_B64__'.decodeBase64()
def newPwStr = new String(newPassword, "UTF-8")

def realm = Jenkins.instance.getSecurityRealm()
if (!(realm instanceof LDAPSecurityRealm)) {
  println "NOT_LDAP_REALM: " + realm.class.name
  return
}

def confs = []
try { confs = realm.getConfigurations() ?: [] } catch (Throwable t) { println "NO_CONFIGS_API: " + t.message; return }
if (confs.isEmpty()) { println "NO_CONFIGS"; return }

def updated = 0
confs.each { conf ->
  Field f = null
  // Try the most common field name first, then a couple of alternates.
  ["managerPasswordSecret", "managerPassword"].each { fname ->
    if (f != null) return
    try { f = conf.class.getDeclaredField(fname) } catch (NoSuchFieldException ignored) {}
    if (f == null) {
      // Some classes keep it on a parent
      def cls = conf.class.superclass
      while (cls != null && f == null) {
        try { f = cls.getDeclaredField(fname) } catch (NoSuchFieldException ignored) {}
        cls = cls.superclass
      }
    }
  }
  if (f == null) {
    println "NO_PASSWORD_FIELD on " + conf.class.name
    return
  }
  f.setAccessible(true)
  f.set(conf, Secret.fromString(newPwStr))
  updated++
}

Jenkins.instance.save()
println "OK updated=" + updated
"""


def _b64(s: str) -> str:
    import base64
    return base64.b64encode(s.encode("utf-8")).decode("ascii")


def update_password(env: str, new_password: str) -> dict:
    """Apply the new manager password to the CJOC via Script Console Groovy."""
    url, auth = _resolve_env(env)
    script = _GROOVY_UPDATE_LDAP_PASSWORD.replace("__NEW_PASSWORD_B64__", _b64(new_password))

    try:
        out = run_groovy_script(url, script, auth=auth)
    except Exception as exc:
        logger.error("CloudBees %s LDAP password update failed: %s", env, exc)
        raise RuntimeError(f"CJOC update failed: {exc}") from exc

    out = (out or "").strip()
    trace = _detect_groovy_trace(out)
    if trace:
        raise RuntimeError(f"Groovy error during update: {trace}")
    if not out.startswith("OK"):
        raise RuntimeError(f"Unexpected update response: {out[:200]}")

    return {"status": "ok", "env": env, "output": out}
