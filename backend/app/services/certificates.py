import logging
import socket
import ssl
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Map of (tool_name, environment) to hostname
TOOLS: dict[tuple[str, str], str] = {
    ("CloudBees", "Dev East"): "jenkins-dev-east.cloud.cms.gov",
    ("CloudBees", "Prod East"): "jenkins-east.cloud.cms.gov",
    ("CloudBees", "Gov Dev"): "jenkins-gc-dev-west.cloud.cms.gov",
    ("CloudBees", "Gov Prod"): "jenkins-gc-west.cloud.cms.gov",
    ("Artifactory", "Dev"): "artifactory-dev.cloud.cms.gov",
    ("Artifactory", "Prod"): "artifactory.cloud.cms.gov",
    ("SonarQube", "Dev"): "sonarqube-dev.cloud.cms.gov",
    ("SonarQube", "Prod"): "sonarqube.cloud.cms.gov",
}

# strptime format used by ssl.SSLSocket.getpeercert()
_CERT_DATE_FORMAT = "%b %d %H:%M:%S %Y %Z"


def check_cert(hostname: str, port: int = 443) -> dict:
    """
    Connect to hostname:port over TLS and retrieve the certificate expiry date.

    Returns a dict with:
      - expiry_date: ISO-8601 string of the certificate's notAfter field
      - days_remaining: integer number of days until expiry
      - error: error message string if the check failed, else None
    """
    ctx = ssl.create_default_context()
    ctx.check_hostname = True
    ctx.verify_mode = ssl.CERT_REQUIRED

    try:
        with socket.create_connection((hostname, port), timeout=5) as raw_sock:
            with ctx.wrap_socket(raw_sock, server_hostname=hostname) as tls_sock:
                cert = tls_sock.getpeercert()
    except ssl.SSLCertVerificationError as exc:
        logger.warning("TLS verification failed for %s:%d: %s", hostname, port, exc)
        return {"expiry_date": None, "days_remaining": None, "error": str(exc)}
    except (socket.timeout, ConnectionRefusedError, OSError) as exc:
        logger.warning("Connection failed for %s:%d: %s", hostname, port, exc)
        return {"expiry_date": None, "days_remaining": None, "error": str(exc)}
    except Exception as exc:
        logger.error("Unexpected error checking cert for %s:%d: %s", hostname, port, exc)
        return {"expiry_date": None, "days_remaining": None, "error": str(exc)}

    not_after_str = cert.get("notAfter")
    if not not_after_str:
        return {
            "expiry_date": None,
            "days_remaining": None,
            "error": "notAfter field missing from certificate",
        }

    try:
        # ssl module returns times in UTC but the string ends with " GMT"
        expiry_dt = datetime.strptime(not_after_str, _CERT_DATE_FORMAT).replace(tzinfo=timezone.utc)
    except ValueError as exc:
        logger.error("Could not parse cert date '%s': %s", not_after_str, exc)
        return {"expiry_date": None, "days_remaining": None, "error": f"Date parse error: {exc}"}

    now = datetime.now(timezone.utc)
    days_remaining = (expiry_dt - now).days

    return {
        "expiry_date": expiry_dt.isoformat(),
        "days_remaining": days_remaining,
        "error": None,
    }
