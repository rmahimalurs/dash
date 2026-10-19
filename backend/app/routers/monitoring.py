import logging

from fastapi import APIRouter, Depends, HTTPException

from app.auth.jwt import get_current_user
from app.services.cbj_resource_analysis import get_cbj_resource_analysis
from app.services import cbj_podtemplate_config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/monitoring", tags=["monitoring"])

_ENVS = ("prod-east", "gc-prod-west")
_TARGETS = ("agents", "controllers")


@router.get("/cbj-resource-analysis/{env}")
async def cbj_resource_analysis(
    env: str,
    target: str = "agents",
    current_user: dict = Depends(get_current_user),
):
    """
    CBJ Resource Analysis for one environment (prod-east or gc-prod-west, kept
    separate — never combined into one result set) and one target:
    - "agents" (default): ephemeral build/agent containers.
    - "controllers": the always-on `jenkins` controller container, one per team.

    Compares Reserved/Limit (a short recent window, since these rarely change
    intra-day and a week-old peak could already be fixed) against Used at
    Peak (busiest moment in the last 7 days, to catch bursty usage). Sorted by
    CPU wasted, biggest first. Status: critical (<10% of reserved CPU actually
    used), warning (10-30%), ok (>30%).
    """
    if env not in _ENVS:
        raise HTTPException(status_code=404, detail=f"Unknown environment '{env}'")
    if target not in _TARGETS:
        raise HTTPException(status_code=400, detail=f"Unknown target '{target}', expected 'agents' or 'controllers'")
    try:
        return await get_cbj_resource_analysis(env, target)
    except Exception as exc:
        logger.warning("cbj-resource-analysis fetch failed for %s/%s: %s", env, target, exc)
        raise HTTPException(status_code=502, detail=f"Could not fetch CBJ resource analysis data for {env}: {exc}")


@router.get("/cbj-podtemplate-config")
async def cbj_podtemplate_config_data(current_user: dict = Depends(get_current_user)):
    """
    DMSC-479: configured podTemplate CPU/memory/ephemeral-storage request/
    limit per prod-east controller, read from each job's last build (console
    log primary, Replay fallback) — not CloudWatch, so it still shows jobs
    that haven't run recently. Cached from the last sweep; POST /sweep to
    refresh (slow — hits every prod-east controller, ~196 as of this
    writing). Each container row is joined live against CloudWatch's actual
    peak usage on every request, so "actually used" stays fresh independent
    of the sweep — a row with no CloudWatch match just hasn't run recently.
    """
    cached = cbj_podtemplate_config.load_cache()
    if cached is None:
        return {"swept_at": None, "controller_count": 0, "results": []}
    return await cbj_podtemplate_config.join_cloudwatch_usage(cached)


@router.post("/cbj-podtemplate-config/sweep")
async def cbj_podtemplate_config_sweep(current_user: dict = Depends(get_current_user)):
    """Kick off a fresh sweep in the background. Real load against prod-east
    Jenkins (196 controllers) — refuses to start a second one concurrently."""
    return cbj_podtemplate_config.start_background_sweep()


@router.get("/cbj-podtemplate-config/sweep-status")
async def cbj_podtemplate_config_sweep_status(current_user: dict = Depends(get_current_user)):
    return cbj_podtemplate_config.sweep_status()
