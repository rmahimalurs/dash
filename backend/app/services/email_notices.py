"""
Escalating email notice counter.

Some ADO outreach emails (PVC cleanup, CBJ resource-waste) are sent repeatedly
to the same target until the team acts. To make the escalation obvious, each
successive email to the same target carries a subject prefix:

    1st send  -> (no prefix)
    2nd send  -> "[Second Notice] ..."
    3rd send and later -> "[Final Notice] ..."

The per-(flow, key) count is persisted to a small JSON file on the EFS data
volume so it survives pod restarts. Counts are monotonic (they never reset on
their own) — once a target has had three notices it stays at "[Final Notice]".

Usage (increment ONLY on a successful send):

    ordinal, prefix = email_notices.peek_next("pvc", controller)
    subject = f"{prefix}Action needed: ..."
    result = send(...)
    if result.get("sent"):
        email_notices.bump("pvc", controller)
"""

import json
import logging
import os
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

_STORE = Path(__file__).resolve().parents[2] / "data" / "email_notice_counts.json"
_lock = threading.Lock()


def _load() -> dict:
    if not _STORE.exists():
        return {}
    try:
        return json.loads(_STORE.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("email_notices: could not read %s: %s", _STORE, exc)
        return {}


def _save(data: dict) -> None:
    # Atomic write so a concurrent read can't see a half-written file.
    _STORE.parent.mkdir(parents=True, exist_ok=True)
    tmp = _STORE.with_suffix(_STORE.suffix + f".tmp.{os.getpid()}")
    tmp.write_text(json.dumps(data))
    os.replace(tmp, _STORE)


def _prefix(ordinal: int) -> str:
    if ordinal <= 1:
        return ""
    if ordinal == 2:
        return "[Second Notice] "
    return "[Final Notice] "


def _entry_of(v) -> dict:
    """Normalize a stored value to {'count': int, 'history': list}, migrating the
    old bare-int format (pre-history)."""
    if isinstance(v, dict):
        return {"count": int(v.get("count", 0)), "history": list(v.get("history", []))}
    return {"count": int(v or 0), "history": []}


def peek_next(flow: str, key: str) -> tuple[int, str]:
    """1-based ordinal + subject prefix the NEXT email to this target would use.
    Read-only — does not increment (call record() after a successful send)."""
    with _lock:
        current = _entry_of(_load().get(flow, {}).get(key))["count"]
    ordinal = current + 1
    return ordinal, _prefix(ordinal)


def record(flow: str, key: str, to: list[str] | None = None, by: str = "") -> int:
    """Record a sent notice for (flow, key): increment the count and append a
    history entry (sent_at, ordinal, recipients, who sent). Call ONLY after the
    email actually went out. Returns the new count (= the ordinal just sent)."""
    from datetime import datetime, timezone
    with _lock:
        data = _load()
        flow_data = data.setdefault(flow, {})
        entry = _entry_of(flow_data.get(key))
        entry["count"] += 1
        entry["history"].append({
            "sent_at": datetime.now(timezone.utc).isoformat(),
            "ordinal": entry["count"],
            "to": list(to or []),
            "by": by or "",
        })
        entry["history"] = entry["history"][-50:]  # cap growth
        flow_data[key] = entry
        _save(data)
        return entry["count"]


def history(flow: str, key: str) -> list[dict]:
    """Send history for (flow, key), oldest first: [{sent_at, ordinal, to, by}]."""
    with _lock:
        return _entry_of(_load().get(flow, {}).get(key))["history"]
