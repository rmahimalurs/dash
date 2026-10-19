import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.routers import admin, auth, automation, dashboard, maintenance, monitoring, profile, github, jira
from app.services import audit

_log_level = getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO)
logging.basicConfig(
    level=_log_level,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def _audit_cleanup_loop() -> None:
    """Run audit log garbage collection once per day."""
    from app.config import get_settings
    while True:
        await asyncio.sleep(86400)
        try:
            settings = get_settings()
            deleted = audit.cleanup_old_logs(settings.AUDIT_RETENTION_DAYS)
            if deleted:
                logger.info(
                    "Audit GC: removed %d log file(s) older than %d days",
                    deleted,
                    settings.AUDIT_RETENTION_DAYS,
                )
        except Exception as exc:
            logger.error("Audit GC failed: %s", exc)


async def _maint_reminder_loop() -> None:
    """Once per day, send the maintenance-ticket reminder when 13 days out."""
    from app.services import deployment
    if deployment.skip_unless_primary("the maintenance reminder"):
        return
    while True:
        try:
            from app.services.maint_notify import reminder_tick
            reminder_tick()
        except Exception as exc:  # noqa: BLE001
            logger.error("Maintenance reminder tick failed: %s", exc)
        await asyncio.sleep(86400)


async def _sonarqube_loc_loop() -> None:
    """Hourly: check SonarQube's server-wide licensed LOC usage and email on
    a status escalation. See CLDSPT-112879."""
    from app.config import get_settings
    from app.services import deployment
    if deployment.skip_unless_primary("the SonarQube LOC alert"):
        return
    while True:
        try:
            from app.services.sonarqube_loc import loc_alert_tick
            loc_alert_tick(get_settings())
        except Exception as exc:  # noqa: BLE001
            logger.error("SonarQube LOC alert tick failed: %s", exc)
        await asyncio.sleep(3600)


async def _github_status_loop() -> None:
    """Every 5 minutes: check githubstatus.com and post to Slack
    #cms-cloud-devops-internal on a status change, not on every tick."""
    from app.config import get_settings
    from app.services import deployment
    if deployment.skip_unless_primary("the GitHub status alert"):
        return
    while True:
        try:
            from app.services.github_status import status_alert_tick
            await asyncio.to_thread(status_alert_tick, get_settings())
        except Exception as exc:  # noqa: BLE001
            logger.error("GitHub status alert tick failed: %s", exc)
        await asyncio.sleep(300)


def _seconds_until(hour: int, tz_name: str) -> float:
    """Seconds from now until the next occurrence of ``hour``:00 in ``tz_name``."""
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    try:
        tz = ZoneInfo(tz_name)
    except Exception:  # noqa: BLE001 — bad tz falls back to UTC
        tz = ZoneInfo("UTC")
    now = datetime.now(tz)
    target = now.replace(hour=hour % 24, minute=0, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


def _run_scheduled_sweeps() -> None:
    """Trigger the daily background sweeps (controller-user audit both envs + CBJ
    podTemplate prod-east). Each start_* call spawns its own worker thread and
    returns immediately; failures are logged, never fatal."""
    try:
        from app.services import controller_users
        for env in controller_users.ENVS:
            res = controller_users.start_background_sweep(env)
            logger.info("Scheduled controller-user sweep (%s): %s", env, res)
    except Exception as exc:  # noqa: BLE001
        logger.error("Scheduled controller-user sweep failed to start: %s", exc)
    try:
        from app.services import cbj_podtemplate_config
        res = cbj_podtemplate_config.start_background_sweep()
        logger.info("Scheduled podTemplate sweep: %s", res)
    except Exception as exc:  # noqa: BLE001
        logger.error("Scheduled podTemplate sweep failed to start: %s", exc)
    try:
        from app.services import artifactory_users
        for env in artifactory_users.ENVS:
            res = artifactory_users.start_background_sweep(env)
            logger.info("Scheduled Artifactory-user sweep (%s): %s", env, res)
    except Exception as exc:  # noqa: BLE001
        logger.error("Scheduled Artifactory-user sweep failed to start: %s", exc)
    try:
        from app.services import cloudbees_access
        for env in cloudbees_access.ENVS:
            res = cloudbees_access.start_background_sweep(env)
            logger.info("Scheduled CloudBees-access sweep (%s): %s", env, res)
    except Exception as exc:  # noqa: BLE001
        logger.error("Scheduled CloudBees-access sweep failed to start: %s", exc)
    try:
        from app.services import cldspt_tickets
        res = cldspt_tickets.start_background_sweep()
        logger.info("Scheduled CLDSPT ticket sweep: %s", res)
    except Exception as exc:  # noqa: BLE001
        logger.error("Scheduled CLDSPT ticket sweep failed to start: %s", exc)


async def _daily_sweep_loop() -> None:
    """Fire _run_scheduled_sweeps() once per day at the configured hour/tz."""
    from app.config import get_settings
    settings = get_settings()
    if not settings.SCHEDULED_SWEEPS_ENABLED:
        logger.info("Scheduled sweeps disabled (SCHEDULED_SWEEPS_ENABLED=false)")
        return
    logger.info("Scheduled sweeps enabled: daily at %02d:00 %s",
                settings.SCHEDULED_SWEEP_HOUR, settings.SCHEDULED_SWEEP_TZ)
    while True:
        delay = _seconds_until(settings.SCHEDULED_SWEEP_HOUR, settings.SCHEDULED_SWEEP_TZ)
        await asyncio.sleep(delay)
        try:
            _run_scheduled_sweeps()
        except Exception as exc:  # noqa: BLE001
            logger.error("Scheduled sweep tick failed: %s", exc)
        # Guard against a same-second re-fire before the clock advances past the hour.
        await asyncio.sleep(60)


async def _announce_release() -> None:
    """Tell the team channel about this release, once per version."""
    from app.services import release_announce

    from app.services import deployment
    if deployment.skip_unless_primary("the release announcement"):
        return

    try:
        result = await asyncio.to_thread(release_announce.announce)
        if not result.get("posted"):
            logger.info(
                "Release %s not announced: %s",
                result.get("version"), result.get("reason"),
            )
    except Exception as exc:  # noqa: BLE001 — never hold up the API for this
        logger.warning("Release announcement failed: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.config import get_settings
    settings = get_settings()
    logger.info(
        "DevOps Dashboard API starting up (log_level=%s, audit_retention=%d days)",
        settings.LOG_LEVEL,
        settings.AUDIT_RETENTION_DAYS,
    )
    from app.services import identity_migration
    identity_migration.run()

    announce_task = asyncio.create_task(_announce_release())

    cleanup_task = asyncio.create_task(_audit_cleanup_loop())
    reminder_task = asyncio.create_task(_maint_reminder_loop())
    sweep_task = asyncio.create_task(_daily_sweep_loop())
    sonarqube_loc_task = asyncio.create_task(_sonarqube_loc_loop())
    github_status_task = asyncio.create_task(_github_status_loop())
    yield
    for t in (announce_task, cleanup_task, reminder_task, sweep_task, sonarqube_loc_task, github_status_task):
        t.cancel()
        try:
            await t
        except asyncio.CancelledError:
            pass
    logger.info("DevOps Dashboard API shutting down")


app = FastAPI(
    title="DevOps Dashboard API",
    description="Backend API for the CMS DMSC DevOps Dashboard",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

# --------------------------------------------------------------------------- #
# CORS - allow frontend dev server (Vite default port 5173)                    #
# --------------------------------------------------------------------------- #

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --------------------------------------------------------------------------- #
# Routers                                                                       #
# --------------------------------------------------------------------------- #

app.include_router(auth.router, prefix="/api")
app.include_router(admin.router, prefix="/api")
app.include_router(dashboard.router, prefix="/api")
app.include_router(maintenance.router, prefix="/api")
app.include_router(automation.router, prefix="/api")
app.include_router(monitoring.router, prefix="/api")
app.include_router(profile.router, prefix="/api")
app.include_router(github.router, prefix="/api")
app.include_router(jira.router, prefix="/api")

# --------------------------------------------------------------------------- #
# Exception handlers                                                            #
# --------------------------------------------------------------------------- #


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    logger.error("Unhandled exception on %s %s: %s", request.method, request.url.path, exc, exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "An internal server error occurred."},
    )


# --------------------------------------------------------------------------- #
# Static files - serve built frontend from ../frontend/dist                    #
# --------------------------------------------------------------------------- #

_frontend_dist = Path(__file__).parent.parent.parent / "frontend" / "dist"
if _frontend_dist.is_dir():
    # Mount the SPA assets; the catch-all below handles HTML5 history routing.
    app.mount("/assets", StaticFiles(directory=str(_frontend_dist / "assets")), name="assets")

    from fastapi.responses import FileResponse

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str):
        """Serve the SPA index.html for all non-API routes."""
        if full_path.startswith("api/"):
            return JSONResponse(status_code=404, content={"detail": "Not found"})
        index = _frontend_dist / "index.html"
        if index.exists():
            return FileResponse(str(index))
        return JSONResponse(status_code=404, content={"detail": "Frontend not built"})
else:
    logger.warning(
        "Frontend dist directory not found at %s; static file serving is disabled.",
        _frontend_dist,
    )
