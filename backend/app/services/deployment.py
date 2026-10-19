"""Whether this process is the deployment that may act on the team's behalf.

Beta runs branch builds of the same image in another namespace, and an engineer
runs the same code on a laptop. Both reach the real Slack and the real mail
relay, and neither has the EFS state the canonical pod has, so anything they
send on a timer is both unexpected and wrong. Scheduled work that leaves the
process checks here first.
"""
import logging
from pathlib import Path

from app.config import get_settings

logger = logging.getLogger(__name__)

# Every pod is told its own namespace here. Absent off-cluster, which is the
# answer we want for a laptop.
_NAMESPACE_FILE = "/var/run/secrets/kubernetes.io/serviceaccount/namespace"


def namespace() -> str:
    try:
        return Path(_NAMESPACE_FILE).read_text().strip()
    except OSError:
        return ""


def is_primary() -> bool:
    return namespace() == get_settings().PRIMARY_NAMESPACE


def skip_unless_primary(what: str) -> bool:
    """True when the caller should not run. Logs where it thinks it is."""
    if is_primary():
        return False
    logger.info(
        "Skipping %s: namespace is %r, not the primary deployment",
        what, namespace() or "none (off-cluster)",
    )
    return True
