"""SonarQube server-wide licensed lines-of-code (LOC) tracking.

CMS's SonarQube Data Center Edition license caps total lines of code
server-wide (across every project combined), not per-project. When the
running total gets close to the cap, new analyses are rejected outright by
the Compute Engine (see CLDSPT-112879) — this surfaced with almost no
warning because nothing was tracking the running total against the cap.

Reuses the SonarQube admin credentials already configured for the license
check (SONARQUBE_*_USER/PASSWORD) — no new secrets.

Confirmed against live prod: /api/system/info returns the total under
System."Lines of Code". _find_ncloc() searches the response recursively
for an ncloc/"lines of code"/loc key rather than hardcoding that exact
path, so it tolerates SonarQube's nesting if it ever changes.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

import httpx

logger = logging.getLogger(__name__)

_TIMEOUT = 15.0


def _find_ncloc(obj) -> int | None:
    """Recursively search a system/info-style nested JSON body for an 'ncloc'
    (or 'lines of code') key, case-insensitive. Returns the first match."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(k, str) and k.strip().lower() in ("ncloc", "lines of code", "loc"):
                try:
                    return int(v)
                except (TypeError, ValueError):
                    continue
        for v in obj.values():
            found = _find_ncloc(v)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = _find_ncloc(item)
            if found is not None:
                return found
    return None


def _status(percent: float | None) -> str:
    if percent is None:
        return "unknown"
    if percent >= 95:
        return "critical"
    if percent >= 85:
        return "warning"
    return "ok"


def _manual(env: str) -> dict:
    return {
        "tool": "SonarQube",
        "env": env,
        "total_ncloc": None,
        "cap": None,
        "percent_used": None,
        "status": "check_manually",
        "error": None,
    }


def check_sonarqube_loc(base_url: str, env: str, user: str, password: str, cap: int) -> dict:
    """
    GET /api/system/info (requires System Administer permission).
    Looks for the server-wide 'ncloc' total anywhere in the response body.
    """
    if not user or not password:
        return _manual(env)

    url = f"{base_url.rstrip('/')}/api/system/info"

    try:
        resp = httpx.get(url, auth=(user, password), timeout=_TIMEOUT, verify=True)
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPStatusError as exc:
        logger.warning("SonarQube system/info API %s returned %s", url, exc.response.status_code)
        return {
            "tool": "SonarQube", "env": env, "total_ncloc": None, "cap": cap,
            "percent_used": None, "status": "unknown", "error": f"HTTP {exc.response.status_code}",
        }
    except Exception as exc:
        logger.warning("SonarQube system/info API %s failed: %s", url, exc)
        return {
            "tool": "SonarQube", "env": env, "total_ncloc": None, "cap": cap,
            "percent_used": None, "status": "unknown", "error": str(exc),
        }

    total_ncloc = _find_ncloc(data)
    if total_ncloc is None:
        logger.warning(
            "SonarQube system/info API %s: could not find an ncloc field. Top-level keys: %s",
            url, list(data.keys()) if isinstance(data, dict) else type(data),
        )
        return {
            "tool": "SonarQube", "env": env, "total_ncloc": None, "cap": cap,
            "percent_used": None, "status": "unknown",
            "error": "Could not find server-wide ncloc in /api/system/info response — endpoint/field needs confirming.",
        }

    percent = round((total_ncloc / cap) * 100, 2) if cap else None
    return {
        "tool": "SonarQube",
        "env": env,
        "total_ncloc": total_ncloc,
        "cap": cap,
        "percent_used": percent,
        "status": _status(percent),
        "error": None,
    }


async def get_all_sonarqube_loc(settings) -> list[dict]:
    import asyncio
    import functools

    loop = asyncio.get_event_loop()
    tasks = [
        loop.run_in_executor(None, functools.partial(check_sonarqube_loc,
            settings.SONARQUBE_PROD_URL, "Prod",
            settings.SONARQUBE_PROD_USER, settings.SONARQUBE_PROD_PASSWORD,
            settings.SONARQUBE_LOC_CAP,
        )),
    ]
    return list(await asyncio.gather(*tasks))


# ─── Hourly alert tick (dedupe: only email on a status escalation) ────────────

def _load_state(path: str) -> dict:
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return {}


def _save_state(path: str, state: dict) -> None:
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w") as f:
            json.dump(state, f)
    except Exception as exc:  # noqa: BLE001
        logger.warning("could not persist sonarqube-loc alert state: %s", exc)


_STATUS_RANK = {"ok": 0, "unknown": 0, "check_manually": 0, "warning": 1, "critical": 2}


def _alert_html(result: dict) -> str:
    pct = result.get("percent_used")
    pct_str = f"{pct:.1f}%" if pct is not None else "unknown"
    return (
        '<div style="font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;'
        'color:#1f2937;max-width:640px;margin:0 auto;padding:8px">'
        f'<div style="background:{"#b91c1c" if result["status"]=="critical" else "#b45309"};'
        f'color:#fff;padding:14px 18px;border-radius:8px 8px 0 0">'
        f'<div style="font-size:12px;letter-spacing:.5px;opacity:.85">CMS DMSC · CLOUD DEVOPS</div>'
        f'<div style="font-size:19px;font-weight:700">SonarQube {result["env"]}: licensed LOC at {pct_str}</div></div>'
        f'<div style="border:1px solid #e5e7eb;border-top:none;border-radius:0 0 8px 8px;padding:16px 18px">'
        f'<p style="margin:0 0 10px">Server-wide lines of code: <strong>{result.get("total_ncloc"):,}'
        f'</strong> / {result.get("cap"):,} ({pct_str}).</p>'
        f'<p style="margin:0 0 10px">New analyses are at risk of being rejected outright by the '
        f'Compute Engine once the cap is reached (as happened in '
        f'<a href="https://jiraent.cms.gov/browse/CLDSPT-112879">CLDSPT-112879</a>).</p>'
        f'<p style="margin:0"><a href="https://devops-dashboard.cloud.cms.gov" '
        f'style="background:#0b4f8a;color:#fff;text-decoration:none;padding:8px 14px;border-radius:6px;font-size:13px">'
        f'Open the dashboard</a></p></div>'
        '<div style="color:#8590a2;font-size:11px;margin-top:8px">Sent by the DevOps Dashboard · '
        'devops-dashboard.cloud.cms.gov</div></div>'
    )


def loc_alert_tick(settings) -> None:
    """Called hourly. Emails MAINT/DEVOPS distro only when a SonarQube env's
    status *escalates* (ok→warning, warning→critical, etc.) — not on every
    tick — so a sustained warning doesn't spam an email every hour."""
    from app.services.email_service import send_html_email

    state_path = settings.SONARQUBE_LOC_STATE_FILE
    state = _load_state(state_path)

    for env, url, user, password in [
        ("Prod", settings.SONARQUBE_PROD_URL, settings.SONARQUBE_PROD_USER, settings.SONARQUBE_PROD_PASSWORD),
    ]:
        try:
            result = check_sonarqube_loc(url, env, user, password, settings.SONARQUBE_LOC_CAP)
        except Exception as exc:  # noqa: BLE001
            logger.error("sonarqube-loc check failed for %s: %s", env, exc)
            continue

        prev_rank = state.get(env, {}).get("rank", 0)
        cur_rank = _STATUS_RANK.get(result["status"], 0)

        if cur_rank > prev_rank and cur_rank >= _STATUS_RANK["warning"]:
            recipients = [e.strip() for e in settings.SONARQUBE_LOC_NOTIFY_EMAILS.split(",") if e.strip()]
            if recipients:
                send_html_email(
                    recipients,
                    f"[SonarQube {env}] Licensed LOC at {result.get('percent_used')}% of cap",
                    _alert_html(result),
                )
                logger.info("sonarqube-loc alert sent for %s (status %s -> %s)", env, prev_rank, result["status"])

        state[env] = {
            "rank": cur_rank,
            "status": result["status"],
            "percent_used": result.get("percent_used"),
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }

    _save_state(state_path, state)
