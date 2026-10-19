import logging
from datetime import datetime, timezone

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

# VictorOps username → Jira username
# Sourced from live VictorOps schedule API (team-yJsTfLQYgVFmBlcj)
VICTOROPS_TO_JIRA: dict[str, str] = {
    "mgib":        "MGIB",   # Mahimalur, Ramesh Krishna
    "max678":      "RWRW",   # Rahimi, Masood
    "shantanu30":  "MDVF",   # Mangalvedhekar, Shantanu
    "sbs2":        "SBS2",   # Sharikar, Srikanth
    "kmehdi":      "M20M",   # Mehdi, Syed Muhammad (Kazim)
    "abdul-s3xr":  "S3XR",   # Shaik, Abdul Qavi
}

# VictorOps username → short display name for UI
VICTOROPS_DISPLAY: dict[str, str] = {
    "mgib":        "Ramesh M.",
    "max678":      "Masood R.",
    "shantanu30":  "Shantanu M.",
    "sbs2":        "Srikanth S.",
    "kmehdi":      "Kazim M.",
    "abdul-s3xr":  "Abdul S.",
}

# Reverse map for display
JIRA_TO_VICTOROPS: dict[str, str] = {v: k for k, v in VICTOROPS_TO_JIRA.items()}


def _headers() -> dict:
    settings = get_settings()
    return {
        "X-VO-Api-Id":  settings.VICTOROPS_API_ID,
        "X-VO-Api-Key": settings.VICTOROPS_API_KEY,
    }


def get_oncall_schedule(days_forward: int = 28) -> list[dict]:
    """
    Fetch the DevOps team on-call rotation schedule.
    Returns a list of roll entries: [{change, until, onCall, isRoll}, ...]
    """
    settings = get_settings()
    team_slug = settings.VICTOROPS_DEVOPS_TEAM_SLUG

    resp = httpx.get(
        f"{settings.VICTOROPS_API_URL}/team/{team_slug}/oncall/schedule",
        params={"daysForward": days_forward, "daysSkip": 0},
        headers=_headers(),
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()

    rolls = []
    for policy in data.get("schedule", []):
        rolls.extend(policy.get("rolls", []))

    # Also include any overrides (manual on-call changes)
    for override in data.get("overrides", []):
        rolls.append({
            "change": override.get("start"),
            "until":  override.get("end"),
            "onCall": override.get("overrideOnCall") or override.get("onCallUser", {}).get("username"),
            "isRoll": False,
            "isOverride": True,
        })

    return rolls


def oncall_for_date(rolls: list[dict], target: datetime) -> str | None:
    """Return the VictorOps username on-call at `target`, checking overrides first."""
    target_utc = target.astimezone(timezone.utc)

    # Check overrides first (they take priority)
    for roll in rolls:
        if not roll.get("isOverride"):
            continue
        try:
            start = datetime.fromisoformat(roll["change"]).astimezone(timezone.utc)
            end   = datetime.fromisoformat(roll["until"]).astimezone(timezone.utc)
            if start <= target_utc < end:
                return roll.get("onCall")
        except Exception:
            continue

    # Fall back to regular rotation rolls
    for roll in rolls:
        if roll.get("isOverride"):
            continue
        try:
            start = datetime.fromisoformat(roll["change"]).astimezone(timezone.utc)
            end   = datetime.fromisoformat(roll["until"]).astimezone(timezone.utc)
            if start <= target_utc < end:
                return roll.get("onCall")
        except Exception:
            continue

    return None


def get_sprint_oncall_assignments(sprint_start_iso: str, sprint_end_iso: str) -> list[dict]:
    """
    Given sprint start/end ISO strings, return per-week on-call assignments.
    Each entry: {week, start, until, victorops_user, jira_user, mapped}
    `mapped` is False when the VictorOps user has no Jira username in our map.
    """
    sprint_start = datetime.fromisoformat(sprint_start_iso.replace("Z", "+00:00"))
    sprint_end   = datetime.fromisoformat(sprint_end_iso.replace("Z", "+00:00"))

    # Fetch enough schedule to cover the sprint
    days_needed = max(int((sprint_end - datetime.now(timezone.utc)).days) + 7, 28)
    rolls = get_oncall_schedule(days_forward=days_needed)

    # Split sprint into 3 weeks
    from datetime import timedelta
    assignments = []
    week_start = sprint_start
    for week_num in range(1, 4):
        week_end = min(week_start + timedelta(weeks=1), sprint_end)
        # Sample the on-call user at the start of this week
        vo_user = oncall_for_date(rolls, week_start)

        # Find the roll boundary so we know when this person's shift ends
        shift_until = None
        for roll in rolls:
            try:
                start = datetime.fromisoformat(roll["change"]).astimezone(timezone.utc)
                end   = datetime.fromisoformat(roll["until"]).astimezone(timezone.utc)
                if start <= week_start.astimezone(timezone.utc) < end:
                    shift_until = roll["until"]
                    break
            except Exception:
                continue

        jira_user = VICTOROPS_TO_JIRA.get(vo_user or "", "")
        assignments.append({
            "week":           week_num,
            "start":          week_start.date().isoformat(),
            "until":          shift_until,
            "victorops_user": vo_user,
            "jira_user":      jira_user,
            "mapped":         bool(jira_user),
        })
        week_start = week_end

    return assignments


def get_current_oncall() -> dict:
    """
    Return who is on call right now (primary) and who is up next (secondary).
    Both include username, display_name, and their shift boundaries.
    """
    from datetime import timedelta

    rolls = get_oncall_schedule(days_forward=14)
    now = datetime.now(timezone.utc)

    primary_user = oncall_for_date(rolls, now)

    # Find the current shift's end time and whether it's an override
    primary_until: str | None = None
    primary_is_override: bool = False
    for roll in sorted(rolls, key=lambda r: r.get("isOverride", False), reverse=True):
        try:
            start = datetime.fromisoformat(roll["change"]).astimezone(timezone.utc)
            end   = datetime.fromisoformat(roll["until"]).astimezone(timezone.utc)
            if start <= now < end:
                primary_until = roll["until"]
                primary_is_override = bool(roll.get("isOverride"))
                break
        except Exception:
            continue

    # Secondary = whoever is on call one second after the current shift ends
    secondary_user: str | None = None
    secondary_from: str | None = primary_until
    secondary_until: str | None = None

    if primary_until:
        try:
            after = datetime.fromisoformat(primary_until).astimezone(timezone.utc) + timedelta(seconds=1)
            secondary_user = oncall_for_date(rolls, after)
            for roll in sorted(rolls, key=lambda r: r.get("isOverride", False), reverse=True):
                try:
                    start = datetime.fromisoformat(roll["change"]).astimezone(timezone.utc)
                    end   = datetime.fromisoformat(roll["until"]).astimezone(timezone.utc)
                    if start <= after < end:
                        secondary_until = roll["until"]
                        break
                except Exception:
                    continue
        except Exception:
            pass

    def _entry(username: str | None, shift_from: str | None, shift_until: str | None, is_override: bool = False) -> dict:
        return {
            "username":     username,
            "display_name": VICTOROPS_DISPLAY.get(username or "", username or "Unknown"),
            "from":         shift_from,
            "until":        shift_until,
            "is_override":  is_override,
        }

    return {
        "primary":   _entry(primary_user,   None,           primary_until, primary_is_override),
        "secondary": _entry(secondary_user, secondary_from, secondary_until),
    }
