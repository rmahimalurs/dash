"""
Send mail through the CMS internal SMTP relay.

The relay (``smtp.cloud.internal.cms.gov``) accepts *unauthenticated* relay only
from allowlisted internal source IPs, and requires STARTTLS before ``MAIL FROM``
(else it answers 530 "Must issue a STARTTLS command first"). So the flow is:
connect on port 25 → EHLO → STARTTLS → EHLO → send, with no AUTH. Authenticated
submission on 587 is deliberately avoided (it 535'd for every credential and
risks AD-locking the dso-smtp-* service accounts Artifactory depends on).

TLS is opportunistic: the relay presents an internal cert that the pod's CA
bundle does not trust, and the source IP is already allowlisted, so by default we
STARTTLS without certificate verification (SMTP_TLS_VERIFY toggles it).
"""
import logging
import re
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

from app.config import get_settings

logger = logging.getLogger(__name__)


def _as_list(value) -> list[str]:
    """Normalise None / str / iterable of addresses into a de-duped list."""
    if not value:
        return []
    if isinstance(value, str):
        value = [value]
    seen, out = set(), []
    for v in value:
        v = (v or "").strip()
        if v and v.lower() not in seen:
            seen.add(v.lower())
            out.append(v)
    return out


def _html_to_text(html: str) -> str:
    """Crude HTML→text fallback for the multipart/alternative plain part."""
    text = re.sub(r"(?is)<(script|style).*?</\1>", "", html)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|tr|h[1-6]|li)>", "\n", text)
    text = re.sub(r"(?i)</td>", "  ", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return text.strip()


def _tls_context():
    ctx = ssl.create_default_context()
    if not get_settings().SMTP_TLS_VERIFY:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


def render_shell(title: str, inner: str) -> str:
    """Wrap body HTML in the standard dashboard email chrome."""
    return (
        '<div style="font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;'
        'color:#1f2937;max-width:640px;margin:0 auto;padding:8px">'
        f'<div style="background:#0b4f8a;color:#fff;padding:14px 18px;border-radius:8px 8px 0 0">'
        f'<div style="font-size:12px;letter-spacing:.5px;color:#9dc7e8">CMS DMSC · CLOUD DEVOPS</div>'
        f'<div style="font-size:19px;font-weight:700">{title}</div></div>'
        f'<div style="border:1px solid #e5e7eb;border-top:none;border-radius:0 0 8px 8px;padding:16px 18px">{inner}</div>'
        '<div style="color:#8590a2;font-size:11px;margin-top:8px">Sent by the DevOps Dashboard · '
        'devops-dashboard.cloud.cms.gov</div></div>'
    )


def send_html_email(
    to,
    subject: str,
    html_body: str,
    *,
    cc=None,
    text_body: str | None = None,
    from_addr: str | None = None,
    from_name: str | None = None,
) -> dict:
    """
    Send a multipart (text + HTML) message through the CMS relay.

    Returns ``{"sent": True, "to": [...], "cc": [...]}`` on success, or
    ``{"sent": False, "error": "..."}`` on any failure — never raises, so the
    caller can surface a clean message to the UI.
    """
    settings = get_settings()
    if not settings.SMTP_ENABLED:
        return {"sent": False, "error": "Outbound email is disabled (SMTP_ENABLED is off)."}

    to_list = _as_list(to)
    cc_list = _as_list(cc)
    if not to_list:
        return {"sent": False, "error": "No recipients."}

    sender = from_addr or settings.SMTP_FROM
    msg = EmailMessage()
    msg["From"] = formataddr((from_name or settings.SMTP_FROM_NAME, sender))
    msg["To"] = ", ".join(to_list)
    if cc_list:
        msg["Cc"] = ", ".join(cc_list)
    msg["Subject"] = subject
    try:
        msg["Message-ID"] = make_msgid(domain=sender.rsplit("@", 1)[-1])
    except Exception:  # pragma: no cover - make_msgid is defensive only
        pass
    msg.set_content(text_body or _html_to_text(html_body))
    msg.add_alternative(html_body, subtype="html")

    recipients = to_list + cc_list
    try:
        with smtplib.SMTP(settings.SMTP_RELAY_HOST, settings.SMTP_RELAY_PORT,
                          timeout=settings.SMTP_TIMEOUT) as smtp:
            smtp.ehlo()
            smtp.starttls(context=_tls_context())
            smtp.ehlo()
            smtp.send_message(msg, from_addr=sender, to_addrs=recipients)
    except (smtplib.SMTPException, OSError) as exc:
        logger.warning("SMTP send to %s failed: %s", to_list, exc)
        return {"sent": False, "error": f"SMTP send failed: {exc}"}

    logger.info("Sent '%s' to %s (cc %s)", subject, to_list, cc_list)
    return {"sent": True, "to": to_list, "cc": cc_list}
