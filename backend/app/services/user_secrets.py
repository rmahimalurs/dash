"""Per-user secret vault, encrypted with a key derived from the engineer's own
AD password (max isolation — undecryptable at rest without the user).

How it works:
- At login we derive a 32-byte vault key = scrypt(AD password, per-user salt) and
  hold it ONLY in this process's memory for the session (never persisted, never
  in the JWT). The salt is per-user, non-secret, stored in the profile.
- Secrets (GitHub PATs) are AES-GCM encrypted with that key and stored on EFS.
- On logout / TTL / process restart the in-memory key is gone, so the ciphertext
  on disk cannot be decrypted by anyone (admins, KMS, another engineer) without
  the user logging in again with their password.

CONSTRAINT: the in-memory key cache requires the backend to run as a SINGLE
replica (it does). If ever scaled >1, this needs a shared session store instead.
Callers must fall back gracefully (service account) when the vault is locked.
"""
from __future__ import annotations

import base64
import logging
import os
import time

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

logger = logging.getLogger(__name__)

# username -> (key: bytes, expiry_epoch: float). Process-local, single replica.
_session_keys: dict[str, tuple[bytes, float]] = {}
_SESSION_TTL_SECONDS = 8 * 3600  # match the auth cookie lifetime


def _derive_key(password: str, salt: bytes) -> bytes:
    kdf = Scrypt(salt=salt, length=32, n=2 ** 14, r=8, p=1)
    return kdf.derive(password.encode("utf-8"))


def _get_or_create_salt(username: str) -> bytes:
    from app.routers.profile import load_profile, save_profile  # local import avoids cycle
    prof = load_profile(username)
    s = prof.get("vault_salt")
    if s:
        return base64.b64decode(s)
    salt = os.urandom(16)
    prof["vault_salt"] = base64.b64encode(salt).decode("ascii")
    save_profile(username, prof)
    return salt


def unlock_session(username: str, password: str) -> None:
    """Derive + cache the user's vault key from their password. Best-effort."""
    try:
        salt = _get_or_create_salt(username)
        _session_keys[username] = (_derive_key(password, salt), time.time() + _SESSION_TTL_SECONDS)
    except Exception as exc:  # noqa: BLE001 — never block login on this
        logger.warning("vault unlock failed for %s: %s", username, exc)


def lock_session(username: str) -> None:
    _session_keys.pop(username, None)


def get_session_key(username: str) -> bytes | None:
    v = _session_keys.get(username)
    if not v:
        return None
    key, exp = v
    if time.time() > exp:
        _session_keys.pop(username, None)
        return None
    return key


def session_unlocked(username: str) -> bool:
    return get_session_key(username) is not None


def encrypt(key: bytes, plaintext: str) -> str:
    """AES-GCM encrypt; returns base64(nonce || ciphertext)."""
    nonce = os.urandom(12)
    ct = AESGCM(key).encrypt(nonce, plaintext.encode("utf-8"), None)
    return base64.b64encode(nonce + ct).decode("ascii")


def decrypt(key: bytes, blob_b64: str) -> str:
    """AES-GCM decrypt. Raises (InvalidTag) if the key is wrong (e.g. password changed)."""
    raw = base64.b64decode(blob_b64)
    return AESGCM(key).decrypt(raw[:12], raw[12:], None).decode("utf-8")
