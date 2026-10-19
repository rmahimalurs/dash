"""Shared bits for the GitHub REST calls in github_auth/github_invites/
github_copilot_seats/github_repo_create: the base URL, auth headers,
error-body parsing, and a retrying request for writes, so each PAT-scoped
write doesn't redefine them."""
from __future__ import annotations

import time

import httpx

GH_API = "https://api.github.com"

_TRANSIENT_MARKERS = ("rate limit", "secondary rate", "abuse detection", "was submitted too quickly")


def auth_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def error_detail(response: httpx.Response) -> str:
    """GitHub's JSON error body's "message", falling back to raw text."""
    try:
        return response.json().get("message") or response.text[:200]
    except Exception:  # noqa: BLE001
        return response.text[:200]


_MAX_COOLDOWN_SECONDS = 120.0  # a cap on how long one wait can be, not how many retries happen


def _is_transient(response: httpx.Response) -> bool:
    if response.status_code in (429, 500, 502, 503, 504):
        return True
    return any(m in response.text.casefold() for m in _TRANSIENT_MARKERS)


def _cooldown_seconds(response: httpx.Response, fallback: float) -> float:
    """How long GitHub itself says to wait, when it says anything -- the
    fixed exponential backoff otherwise used is a guess; honoring the
    server's own number (when present) avoids retrying into the same
    window it just asked to be left alone for.

    Secondary rate limits (abuse detection) send Retry-After, in seconds.
    The primary rate limit sends X-RateLimit-Remaining/-Reset instead, with
    no Retry-After -- Reset is a Unix epoch second, so the wait is derived
    from it only when GitHub reports the limit as actually exhausted.
    """
    retry_after = response.headers.get("Retry-After")
    if retry_after is not None:
        try:
            return min(float(retry_after), _MAX_COOLDOWN_SECONDS)
        except ValueError:
            pass

    if response.headers.get("X-RateLimit-Remaining") == "0":
        reset_at = response.headers.get("X-RateLimit-Reset")
        if reset_at is not None:
            try:
                wait = float(reset_at) - time.time()
            except ValueError:
                wait = -1
            if wait > 0:
                return min(wait, _MAX_COOLDOWN_SECONDS)

    return fallback


def request_with_retry(method: str, url: str, *, retries: int = 3, backoff: float = 2.0, **kwargs) -> httpx.Response:
    """Like httpx.request, but retries a transient failure (429, 5xx, or a
    secondary-rate-limit message in the body) with exponential backoff --
    never a real 4xx rejection, which retrying can't fix. When GitHub's own
    response says how long to wait (Retry-After, or an exhausted
    X-RateLimit-Remaining with a Reset time), that takes priority over the
    guessed backoff, so a longer cooldown than 2-4s is actually honored
    instead of retrying straight back into the same limit. Returns the last
    response either way; a connection error on the final attempt propagates.
    """
    delay = backoff
    for attempt in range(retries):
        try:
            r = httpx.request(method, url, **kwargs)
        except httpx.RequestError:
            if attempt == retries - 1:
                raise
            time.sleep(delay)
            delay *= 2
            continue
        if r.status_code < 400 or attempt == retries - 1 or not _is_transient(r):
            return r
        time.sleep(_cooldown_seconds(r, delay))
        delay *= 2
    raise AssertionError("unreachable")  # loop above always returns or raises
