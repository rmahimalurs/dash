"""Shared ldap3 Server factory with TLS.

Every LDAP connection in the app goes through make_ldap_server so LDAPS
connections consistently validate the DC certificate against the baked AD CA
cert (AD_LDAP_CA_FILE). If the CA file is absent the connection still uses TLS
but skips validation, so a missing cert degrades gracefully instead of breaking
LDAP entirely.
"""
import os
import ssl
import logging

from ldap3 import Server, Tls

from app.config import get_settings

logger = logging.getLogger(__name__)

_warned_no_ca = False


def make_ldap_server(url: str, **kwargs) -> Server:
    use_ssl = url.lower().startswith("ldaps://")
    tls = None
    if use_ssl:
        global _warned_no_ca
        ca = get_settings().AD_LDAP_CA_FILE
        if ca and os.path.exists(ca):
            tls = Tls(ca_certs_file=ca, validate=ssl.CERT_REQUIRED)
        else:
            if not _warned_no_ca:
                logger.warning("LDAPS in use but AD CA file %r is missing; certificate NOT validated", ca)
                _warned_no_ca = True
            tls = Tls(validate=ssl.CERT_NONE)
    return Server(url, use_ssl=use_ssl, tls=tls, **kwargs)
