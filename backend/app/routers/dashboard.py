import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException

from app.auth.jwt import get_current_user
from app.config import get_settings
from app.services.certificates import TOOLS, check_cert
from app.services.ldap_accounts import get_service_account_expiry
from app.services.licenses import get_all_licenses
from app.services.sonarqube_loc import get_all_sonarqube_loc
from app.services.victorops_service import get_current_oncall
from app.services.jira_service import get_maintenance_overview
from app.services import maintenance_mode
from app.services import release_notes

logger = logging.getLogger(__name__)

from pydantic import BaseModel


class WhatsNewAck(BaseModel):
    version: str


router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/health")
async def health():
    """Kubernetes liveness/readiness probe endpoint. No auth required.

    Carries the version so the footer can state what is deployed without
    waiting on an authenticated call.
    """
    return {"status": "ok", "version": release_notes.APP_VERSION}


@router.get("/maintenance-mode")
async def maintenance_mode_status():
    """Public: whether the site is in maintenance mode (drives the Under Maintenance page)."""
    s = maintenance_mode.get_state()
    return {"enabled": s["enabled"], "message": s["message"]}


@router.get("/certificates")
async def certificates(current_user: dict = Depends(get_current_user)):
    """
    Check TLS certificate expiry for all configured tools.

    Returns a list of {tool, env, domain, expiry_date, days_remaining, status}.
    Status is 'ok' (>30 days), 'warning' (14-30 days), or 'critical' (<14 days).
    """
    loop = asyncio.get_event_loop()
    entries = list(TOOLS.items())

    cert_infos = await asyncio.gather(
        *[loop.run_in_executor(None, check_cert, hostname) for _, hostname in entries]
    )

    results = []
    for ((tool, env), hostname), cert_info in zip(entries, cert_infos):
        days = cert_info.get("days_remaining")

        if days is None:
            cert_status = "unknown"
        elif days < 14:
            cert_status = "critical"
        elif days < 30:
            cert_status = "warning"
        else:
            cert_status = "ok"

        results.append(
            {
                "tool": tool,
                "env": env,
                "domain": hostname,
                "expiry_date": cert_info.get("expiry_date"),
                "days_remaining": days,
                "status": cert_status,
                "error": cert_info.get("error"),
            }
        )

    return results


@router.get("/licenses")
async def licenses(current_user: dict = Depends(get_current_user)):
    """
    Check license expiry for Artifactory, SonarQube, and CloudBees CI.
    Returns a list of {tool, env, expiry_date, days_remaining, status, notes, error}.
    Status: ok (>30d), warning (14-30d), critical (<14d / expired), unknown (error), check_manually (no creds).
    """
    settings = get_settings()
    return await get_all_licenses(settings)


@router.get("/sonarqube-loc")
async def sonarqube_loc(current_user: dict = Depends(get_current_user)):
    """
    Server-wide licensed lines-of-code usage for SonarQube (Prod only — Dev
    isn't tracked here).
    Returns a list of {tool, env, total_ncloc, cap, percent_used, status, error}.
    Status: ok (<85%), warning (85-95%), critical (>=95%), unknown (error),
    check_manually (no creds configured). See CLDSPT-112879.
    """
    settings = get_settings()
    return await get_all_sonarqube_loc(settings)


@router.get("/service-accounts")
async def service_accounts(current_user: dict = Depends(get_current_user)):
    """
    Check AD password expiry for configured LDAP service accounts.
    Returns a list of {label, username, expiry_date, days_remaining, never_expires, status, error}.
    """
    settings = get_settings()
    accounts = [
        ("CloudBees / Prod A",       settings.SA_CLOUDBEES_PROD_A),
        ("CloudBees / Prod B",       settings.SA_CLOUDBEES_PROD_B),
        ("CloudBees / Dev A",        settings.SA_CLOUDBEES_DEV_A),
        ("CloudBees / Dev B",        settings.SA_CLOUDBEES_DEV_B),
        ("CloudBees / GovCloud",     settings.SA_CLOUDBEES_GOVCLOUD),
        ("CloudBees / Sandbox",      settings.SA_CLOUDBEES_SANDBOX),
        ("Artifactory / Prod",       settings.SA_ARTIFACTORY_PROD),
        ("Artifactory / Dev",        settings.SA_ARTIFACTORY_DEV),
        ("SonarQube / Prod",         settings.SA_SONARQUBE_PROD),
        ("SonarQube / Dev",          settings.SA_SONARQUBE_DEV),
        ("Datadog Synthetics / Prod", settings.SA_DATADOG_SYNTHETICS_PROD),
        ("Datadog Synthetics / Dev",  settings.SA_DATADOG_SYNTHETICS_DEV),
        ("SMTP Relay / Prod",        settings.SA_SMTP_PROD),
        ("SMTP Relay / Dev",         settings.SA_SMTP_DEV),
    ]
    return get_service_account_expiry(accounts)


@router.get("/maintenance-tickets")
async def maintenance_tickets(current_user: dict = Depends(get_current_user)):
    """
    Read-only snapshot of the current maintenance cycle's tickets, so the team
    can see what's outstanding without opening Jira: the latest prep ticket
    per tool (DMSC), plus the current cycle's ITC and MGGD change-management
    tickets. Each rolls over on its own once next cycle's tickets are created.
    Returns {prep: {tools: {...}}, itc: {key, url, status, is_closed} | None,
    mggd: {...} | None}.
    """
    try:
        return await asyncio.to_thread(get_maintenance_overview)
    except Exception as exc:
        logger.warning("Maintenance ticket overview fetch failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"Could not fetch maintenance tickets: {exc}")


@router.get("/oncall")
async def oncall(current_user: dict = Depends(get_current_user)):
    """Return the current and next on-call engineer from the VictorOps rotation."""
    try:
        return await asyncio.to_thread(get_current_oncall)
    except Exception as exc:
        logger.warning("VictorOps on-call fetch failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"Could not fetch on-call schedule: {exc}")


@router.get("/links")
async def links(current_user: dict = Depends(get_current_user)):
    """Return all configured tool URLs grouped by tool and environment."""
    settings = get_settings()
    return {
        "cloudbees": [
            {"env": "Dev East", "url": settings.CLOUDBEES_EAST_DEV_URL},
            {"env": "Prod East", "url": settings.CLOUDBEES_EAST_PROD_URL},
            {"env": "Gov Dev", "url": settings.CLOUDBEES_GOV_DEV_URL},
            {"env": "Gov Prod", "url": settings.CLOUDBEES_GOV_PROD_URL},
        ],
        "artifactory": [
            {"env": "Dev", "url": settings.ARTIFACTORY_DEV_URL},
            {"env": "Prod", "url": settings.ARTIFACTORY_PROD_URL},
        ],
        "sonarqube": [
            {"env": "Dev", "url": settings.SONARQUBE_DEV_URL},
            {"env": "Prod", "url": settings.SONARQUBE_PROD_URL},
        ],
        "jira": [
            {"env": "DMSC", "name": "Jira (DMSC)", "url": f"{settings.JIRA_URL}/secure/RapidBoard.jspa?rapidView=7118&projectKey=DMSC&quickFilter=51231#"},
            {"env": "CLDSPT", "name": "Jira (CLDSPT)", "url": f"{settings.JIRA_URL}/projects/CLDSPT/queues"},
            {"env": "CLDSPT", "name": "CLDSPT Dashboard", "url": f"{settings.JIRA_URL}/secure/Dashboard.jspa?selectPageId=72025"},
        ],
        "confluence": [
            {"env": "Production", "url": settings.CONFLUENCE_URL},
        ],
    }


@router.get("/whats-new")
async def whats_new(current_user: dict = Depends(get_current_user)):
    """The current release's highlights plus whether this user dismissed them."""
    from app.routers.profile import load_profile

    profile = load_profile(current_user["username"])
    return release_notes.whats_new_for(profile)


@router.post("/whats-new/ack")
async def acknowledge_whats_new(
    body: WhatsNewAck,
    current_user: dict = Depends(get_current_user),
):
    """Dismiss the popup for this user until the next release."""
    from app.routers.profile import load_profile, save_profile

    if not release_notes.release_for(body.version):
        raise HTTPException(status_code=400, detail=f"Unknown release: {body.version}")

    username = current_user["username"]
    save_profile(username, release_notes.mark_acknowledged(load_profile(username), body.version))
    return {"acknowledged": True, "version": body.version}
