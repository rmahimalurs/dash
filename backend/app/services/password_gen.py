"""Strong random password generation for AD service-account rotation."""
import secrets
import string

# AD-safe symbol set: satisfies complexity but avoids characters that commonly
# break shell/URL/LDAP handling ("'`\\/<>{}[]() and whitespace).
_SYMBOLS = "!@#$%^*-_=+?."
_POOLS = (string.ascii_lowercase, string.ascii_uppercase, string.digits, _SYMBOLS)
_ALPHABET = "".join(_POOLS)


def generate_password(length: int = 20) -> str:
    """Generate a random password containing all four character classes.

    Default length 20 comfortably clears CMS AD complexity + length policy.
    """
    length = max(length, 14)
    while True:
        pw = "".join(secrets.choice(_ALPHABET) for _ in range(length))
        if all(any(c in pool for c in pw) for pool in _POOLS):
            return pw
