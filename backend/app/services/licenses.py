import asyncio
import functools
import logging
from datetime import datetime, timezone

import httpx

logger = logging.getLogger(__name__)

_TIMEOUT = 10


def _days_remaining(expiry_dt: datetime) -> int:
    return (expiry_dt - datetime.now(timezone.utc)).days


def _status(days: int | None) -> str:
    if days is None:
        return "unknown"
    if days <= 0:
        return "critical"
    if days < 14:
        return "critical"
    if days < 30:
        return "warning"
    return "ok"


def _result(tool: str, env: str, expiry_dt: datetime | None, license_type: str = "", error: str | None = None) -> dict:
    days = _days_remaining(expiry_dt) if expiry_dt else None
    return {
        "tool": tool,
        "env": env,
        "expiry_date": expiry_dt.isoformat() if expiry_dt else None,
        "days_remaining": days,
        "status": "unknown" if error else _status(days),
        "notes": license_type,
        "error": error,
    }


def _manual(tool: str, env: str) -> dict:
    return {
        "tool": tool,
        "env": env,
        "expiry_date": None,
        "days_remaining": None,
        "status": "check_manually",
        "notes": "",
        "error": None,
    }


# --------------------------------------------------------------------------- #
# Artifactory                                                                   #
# --------------------------------------------------------------------------- #

def check_artifactory_license(base_url: str, env: str, token: str = "", user: str = "", password: str = "") -> dict:
    """
    GET /artifactory/api/system/license
    Accepts a Bearer token (preferred) or basic auth credentials.
    Response: {"type": "Enterprise Plus", "validThrough": "Mar 31, 2027", "licensedTo": "..."}
    """
    url = f"{base_url.rstrip('/')}/artifactory/api/system/license"

    if token:
        headers = {"Authorization": f"Bearer {token}"}
        auth = None
    elif user and password:
        headers = {}
        auth = (user, password)
    else:
        return _manual("Artifactory", env)

    try:
        resp = httpx.get(url, headers=headers, auth=auth, timeout=_TIMEOUT, verify=True)
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPStatusError as exc:
        logger.warning("Artifactory license API %s returned %s", url, exc.response.status_code)
        return _result("Artifactory", env, None, error=f"HTTP {exc.response.status_code}")
    except Exception as exc:
        logger.warning("Artifactory license API %s failed: %s", url, exc)
        return _result("Artifactory", env, None, error=str(exc))

    valid_through = data.get("validThrough", "")
    license_type = data.get("type", "")

    if not valid_through:
        return _result("Artifactory", env, None, license_type, error="validThrough missing in response")

    # API returns dates like "Mar 31, 2027" — strip extra whitespace for single-digit days
    for fmt in ("%b %d, %Y", "%b  %d, %Y"):
        try:
            expiry_dt = datetime.strptime(valid_through.strip(), fmt).replace(tzinfo=timezone.utc)
            return _result("Artifactory", env, expiry_dt, license_type)
        except ValueError:
            continue

    return _result("Artifactory", env, None, license_type, error=f"Cannot parse date: {valid_through!r}")


# --------------------------------------------------------------------------- #
# SonarQube                                                                     #
# --------------------------------------------------------------------------- #

def check_sonarqube_license(base_url: str, env: str, user: str, password: str) -> dict:
    """
    GET /api/editions/show_license  (requires admin credentials)
    Response: {"expiresAt": "2026-06-23", "edition": "Data Center Edition", "isExpired": false, ...}
    """
    if not user or not password:
        return _manual("SonarQube", env)

    url = f"{base_url.rstrip('/')}/api/editions/show_license"

    try:
        resp = httpx.get(url, auth=(user, password), timeout=_TIMEOUT, verify=True)
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPStatusError as exc:
        logger.warning("SonarQube license API %s returned %s", url, exc.response.status_code)
        return _result("SonarQube", env, None, error=f"HTTP {exc.response.status_code}")
    except Exception as exc:
        logger.warning("SonarQube license API %s failed: %s", url, exc)
        return _result("SonarQube", env, None, error=str(exc))

    edition = data.get("edition", "")
    raw_expiry = data.get("expiresAt", "")

    if not raw_expiry:
        return _result("SonarQube", env, None, edition, error="expiresAt missing in license response")

    try:
        expiry_dt = datetime.strptime(raw_expiry, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        return _result("SonarQube", env, expiry_dt, edition)
    except ValueError:
        return _result("SonarQube", env, None, edition, error=f"Cannot parse date: {raw_expiry!r}")


# --------------------------------------------------------------------------- #
# CloudBees CI                                                                  #
# --------------------------------------------------------------------------- #

def check_cloudbees_license(cjoc_url: str, env: str, jenkins_user: str, jenkins_token: str, manual_expiry: str = "") -> dict:
    """
    Run a Groovy script against the CJOC Script Console to read the CloudBees license expiry.
    Falls back to manual_expiry (YYYY-MM-DD) if credentials are absent or the script call fails.
    """
    from app.services.jenkins import run_groovy_script, _CLOUDBEES_LICENSE_SCRIPT

    if jenkins_user and jenkins_token:
        try:
            result = run_groovy_script(cjoc_url, _CLOUDBEES_LICENSE_SCRIPT, (jenkins_user, jenkins_token))
            if result and result != "No expiration found":
                expiry_dt = datetime.strptime(result, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                return _result("CloudBees", env, expiry_dt, "CloudBees CI")
            logger.warning("CloudBees license script on %s returned: %r", cjoc_url, result)
        except Exception as exc:
            logger.warning("CloudBees license script on %s failed: %s", cjoc_url, exc)

    if manual_expiry:
        try:
            expiry_dt = datetime.strptime(manual_expiry, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            return _result("CloudBees", env, expiry_dt, "CloudBees CI")
        except ValueError:
            pass

    return _manual("CloudBees", env)


# --------------------------------------------------------------------------- #
# Snyk (SaaS)                                                                   #
# --------------------------------------------------------------------------- #

def check_snyk_license(token: str, group_id: str, tenant_id: str = "",
                       api_url: str = "https://api.snyk.io", env: str = "SaaS",
                       manual_expiry: str = "") -> dict:
    """Read the Snyk subscription end date from the (hidden) billing API.

    Mirrors the "Your Plan" page call. Resolves the tenant from the group when
    ``tenant_id`` is blank, then reads
    ``data[0].attributes.billing.contract_end_date``. When no token is configured
    (the live billing call needs a personal token), falls back to the
    manually-configured expiry (``SNYK_LICENSE_EXPIRY``, currently 2027-09-30).
    """
    if not token:
        if manual_expiry:
            try:
                expiry_dt = datetime.strptime(manual_expiry[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
                return _result("Snyk", env, expiry_dt, "Enterprise Bundle Plan")
            except ValueError:
                pass
        return _manual("Snyk", env)

    headers = {"Authorization": f"token {token}", "Accept": "application/vnd.api+json"}
    ver = {"version": "2024-10-15"}
    try:
        if not tenant_id:
            gresp = httpx.get(f"{api_url.rstrip('/')}/rest/groups/{group_id}",
                              params=ver, headers=headers, timeout=_TIMEOUT, verify=True)
            gresp.raise_for_status()
            tenant_id = (gresp.json().get("data", {})
                         .get("relationships", {}).get("tenant", {})
                         .get("data", {}).get("id", ""))
        if not tenant_id:
            return _result("Snyk", env, None, "Enterprise", error="could not resolve Snyk tenant")

        presp = httpx.get(
            f"{api_url.rstrip('/')}/hidden/tenants/{tenant_id}/billing_account/plan_capabilities",
            params=ver, headers=headers, timeout=_TIMEOUT, verify=True)
        presp.raise_for_status()
        data = presp.json().get("data", [])
        if not data:
            return _result("Snyk", env, None, "", error="no billing data returned")
        billing = data[0].get("attributes", {}).get("billing", {}) or {}
        raw = billing.get("contract_end_date", "")
        plan = data[0].get("attributes", {}).get("name") or "Enterprise"
    except httpx.HTTPStatusError as exc:
        logger.warning("Snyk billing API returned %s", exc.response.status_code)
        return _result("Snyk", env, None, "", error=f"HTTP {exc.response.status_code}")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Snyk billing API failed: %s", exc)
        return _result("Snyk", env, None, "", error=str(exc)[:120])

    if not raw:
        return _result("Snyk", env, None, plan, error="contract_end_date missing")
    try:
        expiry_dt = datetime.strptime(raw[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        return _result("Snyk", env, expiry_dt, plan)
    except ValueError:
        return _result("Snyk", env, None, plan, error=f"cannot parse date: {raw!r}")


# --------------------------------------------------------------------------- #
# Aggregate                                                                     #
# --------------------------------------------------------------------------- #

async def get_all_licenses(settings) -> list[dict]:
    loop = asyncio.get_event_loop()
    default_token = settings.JENKINS_TOKEN

    tasks = [
        loop.run_in_executor(None, functools.partial(check_artifactory_license,
            settings.ARTIFACTORY_PROD_URL, "Prod",
            user=settings.ARTIFACTORY_PROD_USER,
            password=settings.ARTIFACTORY_PROD_PASSWORD,
        )),
        loop.run_in_executor(None, functools.partial(check_artifactory_license,
            settings.ARTIFACTORY_DEV_URL, "Dev",
            token=settings.ARTIFACTORY_DEV_TOKEN,
            user=settings.ARTIFACTORY_DEV_USER,
            password=settings.ARTIFACTORY_DEV_PASSWORD,
        )),
        loop.run_in_executor(None, functools.partial(check_sonarqube_license,
            settings.SONARQUBE_PROD_URL, "Prod",
            user=settings.SONARQUBE_PROD_USER,
            password=settings.SONARQUBE_PROD_PASSWORD,
        )),
        loop.run_in_executor(None, functools.partial(check_sonarqube_license,
            settings.SONARQUBE_DEV_URL, "Dev",
            user=settings.SONARQUBE_DEV_USER,
            password=settings.SONARQUBE_DEV_PASSWORD,
        )),
    ]

    # CloudBees CI — Groovy script against each CJOC's Script Console
    # CLOUDBEES_*_URL settings already include /cjoc — do not append it again
    # Falls back to manually-configured date if credentials are absent or the call fails
    for env, cjoc_url, user, env_token, manual_expiry in [
        ("Dev East",  settings.CLOUDBEES_EAST_DEV_URL,  settings.JENKINS_DEV_USER,  settings.JENKINS_EAST_DEV_TOKEN,  settings.LICENSE_EXPIRY_CLOUDBEES_EAST_DEV),
        ("Prod East", settings.CLOUDBEES_EAST_PROD_URL, settings.JENKINS_PROD_USER, settings.JENKINS_EAST_PROD_TOKEN, settings.LICENSE_EXPIRY_CLOUDBEES_EAST_PROD),
        ("Gov Dev",   settings.CLOUDBEES_GOV_DEV_URL,   settings.JENKINS_DEV_USER,  settings.JENKINS_GOV_DEV_TOKEN,   settings.LICENSE_EXPIRY_CLOUDBEES_GOV_DEV),
        ("Gov Prod",  settings.CLOUDBEES_GOV_PROD_URL,  settings.JENKINS_PROD_USER, settings.JENKINS_GOV_PROD_TOKEN,  settings.LICENSE_EXPIRY_CLOUDBEES_GOV_PROD),
    ]:
        tasks.append(loop.run_in_executor(None, functools.partial(check_cloudbees_license,
            cjoc_url, env,
            jenkins_user=user,
            jenkins_token=env_token or default_token,
            manual_expiry=manual_expiry,
        )))

    # Snyk (SaaS) — subscription end date from the hidden billing API
    tasks.append(loop.run_in_executor(None, functools.partial(check_snyk_license,
        settings.SNYK_TOKEN, settings.SNYK_GROUP_ID,
        tenant_id=settings.SNYK_TENANT_ID, api_url=settings.SNYK_API_URL,
        manual_expiry=settings.SNYK_LICENSE_EXPIRY,
    )))

    return list(await asyncio.gather(*tasks))
