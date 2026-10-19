"""
Maintenance date and window override.

The maintenance date normally computes as the 3rd Saturday of the month
(``jira_service.get_next_maintenance_date``). Occasionally a window is moved —
e.g. September 2026 runs on the 26th instead of the 3rd Saturday. An admin can
set an explicit override date here; while it is enabled AND still in the future,
every maintenance flow (prep, ITC/MGGD, reminders, IR plan) uses it instead of
the computed date. Turning the toggle off, or letting the override date pass,
falls back to the 3rd-Saturday default automatically.

The window times can be overridden the same way, independently of the date: a
window that runs late one month only needs the times set. Each time is optional
and falls back to the standard window, so overriding the date alone leaves the
times at 9 AM to 1 PM.

File-backed (EFS-persisted), same pattern as ``maintenance_mode``.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, timedelta, timezone

from app.config import get_settings

logger = logging.getLogger(__name__)

# The standard window. Overridable per month via the admin toggle.
DEFAULT_START_TIME = "09:00"
DEFAULT_END_TIME = "13:00"
# Datadog downtime runs an hour past the outage so monitors stay silenced
# while the team verifies.
DEFAULT_DOWNTIME_END_TIME = "14:00"

_TIME_KEYS = ("start_time", "end_time", "downtime_end_time")

# The Go/No-Go review normally sits 10 days before the window. When a window is
# arranged late that lands in the past, which Change Management rejects, so it
# can be set explicitly.
GO_NOGO_LEAD_DAYS = 10


def _path() -> str:
    return get_settings().MAINT_DATE_OVERRIDE_STATE_FILE


def get_state() -> dict:
    """Return {enabled, date, start_time, end_time, downtime_end_time,
    updated_by, updated_at}. Defaults to disabled.

    Time keys are absent from files written before they existed, so they read
    back as None, which means "use the standard window".
    """
    try:
        with open(_path()) as f:
            data = json.load(f)
        state = {
            "enabled": bool(data.get("enabled", False)),
            "date": data.get("date"),  # ISO "YYYY-MM-DD" or None
            "updated_by": data.get("updated_by"),
            "updated_at": data.get("updated_at"),
        }
        for key in _TIME_KEYS:
            state[key] = data.get(key) or None
        state["go_nogo_date"] = data.get("go_nogo_date") or None
        return state
    except (FileNotFoundError, json.JSONDecodeError):
        state = {"enabled": False, "date": None, "updated_by": None, "updated_at": None}
        for key in _TIME_KEYS:
            state[key] = None
        state["go_nogo_date"] = None
        return state


def _parse_time(value: str | None, label: str) -> str | None:
    """Normalize "H:MM" or "HH:MM" to "HH:MM", or raise."""
    if value in (None, ""):
        return None
    try:
        return datetime.strptime(str(value).strip(), "%H:%M").strftime("%H:%M")
    except ValueError as exc:
        raise ValueError(f"Invalid {label} {value!r} (expected 24-hour HH:MM).") from exc


def effective_window() -> dict:
    """The window every maintenance flow should use.

    Date and times override independently: an enabled override with only times
    set keeps the computed 3rd-Saturday date, and vice versa. Times apply while
    the override is enabled, and stop applying when it expires along with the
    date, so a forgotten toggle cannot move next month's window either.
    """
    state = get_state()
    active = get_override_date() is not None or (
        bool(state.get("enabled")) and not state.get("date")
    )

    times = {
        "start_time": DEFAULT_START_TIME,
        "end_time": DEFAULT_END_TIME,
        "downtime_end_time": DEFAULT_DOWNTIME_END_TIME,
    }
    overridden = []
    if active:
        for key in _TIME_KEYS:
            if state.get(key):
                times[key] = state[key]
                overridden.append(key)

    from app.services.jira_service import get_next_maintenance_date
    maint_date = get_next_maintenance_date()
    if get_override_date() is not None:
        overridden.append("date")

    # Go/No-Go: the explicit override when one is set and still active,
    # otherwise the standard lead time before the window.
    go_nogo = maint_date - timedelta(days=GO_NOGO_LEAD_DAYS)
    if active and state.get("go_nogo_date"):
        try:
            go_nogo = date.fromisoformat(state["go_nogo_date"])
            overridden.append("go_nogo_date")
        except (TypeError, ValueError):
            logger.warning("Go/No-Go override is unparseable: %r", state.get("go_nogo_date"))

    today = date.today()
    return {
        "date": maint_date.isoformat(),
        **times,
        "go_nogo_date": go_nogo.isoformat(),
        # Surfaced so the forms can refuse to submit a review date that has
        # already passed, which is what Change Management rejected on.
        "go_nogo_in_past": go_nogo < today,
        "lead_days": (maint_date - today).days,
        "go_nogo_lead_days": GO_NOGO_LEAD_DAYS,
        "overridden": overridden,
        "is_overridden": bool(overridden),
    }


def get_override_date() -> date | None:
    """Return the override date if enabled and not yet passed, else None.

    Auto-expires: an override whose date is in the past is ignored, so a forgotten
    toggle can't hijack the following month's window.
    """
    state = get_state()
    if not state.get("enabled") or not state.get("date"):
        return None
    try:
        d = date.fromisoformat(state["date"])
    except (TypeError, ValueError):
        logger.warning("Maintenance-date override has an unparseable date: %r", state.get("date"))
        return None
    if d < date.today():
        return None
    return d


def set_state(enabled: bool, override_date: str | None, by: str,
              start_time: str | None = None, end_time: str | None = None,
              downtime_end_time: str | None = None,
              go_nogo_date: str | None = None) -> dict:
    """Persist the override.

    ``override_date`` is "YYYY-MM-DD". Enabling requires either a date or at
    least one time, since an override that changes nothing is a no-op that
    would read as active on the Admin page.
    """
    parsed = None
    times = {
        "start_time": _parse_time(start_time, "start time"),
        "end_time": _parse_time(end_time, "end time"),
        "downtime_end_time": _parse_time(downtime_end_time, "Datadog downtime end time"),
    }

    if enabled:
        if override_date:
            try:
                parsed = date.fromisoformat(override_date).isoformat()
            except ValueError as exc:
                raise ValueError(f"Invalid override date {override_date!r} (expected YYYY-MM-DD).") from exc
        elif not any(times.values()) and not go_nogo_date:
            raise ValueError("Enabling the override needs a date, a time, a Go/No-Go date, or any combination.")

        start = times["start_time"] or DEFAULT_START_TIME
        end = times["end_time"] or DEFAULT_END_TIME
        if end <= start:
            raise ValueError(f"The window end ({end}) must be after its start ({start}).")
        downtime_end = times["downtime_end_time"] or DEFAULT_DOWNTIME_END_TIME
        if downtime_end < end:
            raise ValueError(
                f"The Datadog downtime end ({downtime_end}) cannot be before the "
                f"window end ({end}); monitors would alert during verification."
            )

    parsed_gng = None
    if go_nogo_date:
        try:
            parsed_gng = date.fromisoformat(go_nogo_date).isoformat()
        except ValueError as exc:
            raise ValueError(f"Invalid Go/No-Go date {go_nogo_date!r} (expected YYYY-MM-DD).") from exc
        if enabled and parsed and parsed_gng > parsed:
            raise ValueError("The Go/No-Go review has to be on or before the maintenance date.")

    state = {
        "enabled": bool(enabled),
        "date": parsed,
        "go_nogo_date": parsed_gng,
        **times,
        "updated_by": by,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    path = _path()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w") as f:
        json.dump(state, f)
    os.replace(tmp, path)
    logger.info("Maintenance override set to enabled=%s date=%s go_nogo=%s times=%s/%s/%s by %s",
                state["enabled"], state["date"], state["go_nogo_date"], state["start_time"],
                state["end_time"], state["downtime_end_time"], by)
    return state
