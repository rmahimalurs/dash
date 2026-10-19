import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.config import get_settings

logger = logging.getLogger(__name__)


def _audit_dir() -> Path:
    return Path(get_settings().AUDIT_DIR)


def log_event(
    event_type: str,
    username: str,
    details: dict | None = None,
    ip: str | None = None,
) -> None:
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": event_type,
        "username": username,
        "ip": ip,
        "details": details or {},
    }

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    audit_dir = _audit_dir()
    audit_dir.mkdir(parents=True, exist_ok=True)
    log_file = audit_dir / f"{today}.jsonl"

    try:
        with log_file.open("a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as exc:
        logger.error("Failed to write audit log entry: %s", exc)


def cleanup_old_logs(retention_days: int) -> int:
    """Delete audit log files older than retention_days. Returns the number of files removed."""
    audit_dir = _audit_dir()
    if not audit_dir.exists():
        return 0

    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    cutoff_str = cutoff.strftime("%Y-%m-%d")
    deleted = 0

    for log_file in audit_dir.glob("*.jsonl"):
        if log_file.stem < cutoff_str:
            try:
                log_file.unlink()
                deleted += 1
            except Exception as exc:
                logger.error("Failed to delete audit log %s: %s", log_file.name, exc)

    return deleted


def get_events(
    date_from: str | None = None,
    date_to: str | None = None,
    username: str | None = None,
    event_type: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> dict:
    audit_dir = _audit_dir()
    if not audit_dir.exists():
        return {"events": [], "total": 0, "page": page, "page_size": page_size}

    events: list[dict] = []
    for log_file in sorted(audit_dir.glob("*.jsonl"), reverse=True):
        file_date = log_file.stem
        if date_from and file_date < date_from:
            continue
        if date_to and file_date > date_to:
            continue

        try:
            for line in log_file.read_text().splitlines():
                if not line.strip():
                    continue
                entry = json.loads(line)
                if username and entry.get("username") != username:
                    continue
                if event_type and not entry.get("event", "").startswith(event_type):
                    continue
                events.append(entry)
        except Exception as exc:
            logger.warning("Failed to read audit log %s: %s", log_file, exc)

    events.sort(key=lambda e: e.get("timestamp", ""), reverse=True)
    total = len(events)
    start = (page - 1) * page_size
    return {
        "events": events[start : start + page_size],
        "total": total,
        "page": page,
        "page_size": page_size,
    }
