import json
import logging

import httpx

logger = logging.getLogger(__name__)


async def generate_jenkins_token(
    cjoc_url: str,
    username: str,
    password: str,
    token_name: str,
) -> dict | None:
    """Create a named personal token; never raises so dashboard login can continue."""
    try:
        async with httpx.AsyncClient(timeout=10, verify=False) as client:
            crumb_resp = await client.get(
                f"{cjoc_url}/crumbIssuer/api/json", auth=(username, password),
            )
            if crumb_resp.status_code != 200:
                logger.warning("Jenkins crumb failed (user=%s): HTTP %s", username, crumb_resp.status_code)
                return None
            crumb_data = crumb_resp.json()
            gen_resp = await client.post(
                f"{cjoc_url}/user/{username}/descriptorByName"
                "/jenkins.security.ApiTokenProperty/generateNewToken",
                auth=(username, password),
                headers={crumb_data["crumbRequestField"]: crumb_data["crumb"]},
                data={"newTokenName": token_name},
            )
            if gen_resp.status_code != 200:
                logger.warning("Jenkins token generation failed (user=%s): HTTP %s", username, gen_resp.status_code)
                return None
            data = gen_resp.json().get("data", {})
            logger.info("Jenkins token created for %s (%s)", username, token_name)
            return {
                "token_value": data.get("tokenValue"),
                "token_uuid": data.get("tokenUuid"),
                "token_name": data.get("tokenName", token_name),
            }
    except Exception as exc:
        logger.warning("Jenkins token generation error (user=%s): %s: %s", username, type(exc).__name__, exc)
        return None


async def _jenkins_token_is_valid(cjoc_url: str, username: str, token: str) -> bool | None:
    """Return True/False for a verified Jenkins response, None when unreachable."""
    try:
        async with httpx.AsyncClient(timeout=10, verify=False) as client:
            resp = await client.get(f"{cjoc_url}/whoAmI/api/json", auth=(username, token))
        if resp.status_code == 401:
            return False
        if resp.status_code != 200:
            return None
        return resp.json().get("authenticated") is True
    except Exception as exc:
        logger.warning("Jenkins token validation error for %s: %s", username, type(exc).__name__)
        return None


async def get_or_create_jenkins_token(
    cjoc_url: str,
    username: str,
    password: str,
    environment: str,
) -> tuple[dict | None, bool]:
    """Reuse the user's encrypted per-environment token, creating it only once.

    Tokens are encrypted with the same password-derived session key used for the
    user's existing secret vault. The bool says whether the returned token is
    durably stored; logout retains durable tokens and revokes session-only tokens.
    """
    from app.routers.profile import load_profile, save_profile
    from app.services import user_secrets

    key = user_secrets.get_session_key(username)
    profile = load_profile(username)
    encrypted = profile.get("jenkins_api_tokens", {}).get(environment)
    if key and encrypted:
        try:
            saved = json.loads(user_secrets.decrypt(key, encrypted))
            token = saved.get("token_value")
            if token:
                valid = await _jenkins_token_is_valid(cjoc_url, username, token)
                if valid is True:
                    return saved, True
                if valid is None:
                    # Network trouble is not evidence that a token was revoked.
                    # Keep the cached token and let normal workflows handle it.
                    return saved, True
        except Exception as exc:
            logger.warning("Could not unlock stored Jenkins token for %s: %s", username, type(exc).__name__)

    info = await generate_jenkins_token(
        cjoc_url=cjoc_url,
        username=username,
        password=password,
        token_name=f"dashboard-{environment}",
    )
    if not info or not info.get("token_value"):
        return None, False
    if not key:
        return info, False

    tokens = profile.setdefault("jenkins_api_tokens", {})
    tokens[environment] = user_secrets.encrypt(key, json.dumps(info))
    try:
        save_profile(username, profile)
        return info, True
    except Exception as exc:
        logger.warning("Could not persist Jenkins token for %s: %s", username, type(exc).__name__)
        return info, False


async def revoke_jenkins_token(cjoc_url: str, username: str, jenkins_token: str, token_uuid: str) -> bool:
    """Best-effort revoke a session-only legacy Jenkins API token."""
    try:
        async with httpx.AsyncClient(timeout=10, verify=False) as client:
            crumb_resp = await client.get(
                f"{cjoc_url}/crumbIssuer/api/json", auth=(username, jenkins_token),
            )
            if crumb_resp.status_code != 200:
                return False
            crumb_data = crumb_resp.json()
            revoke_resp = await client.post(
                f"{cjoc_url}/user/{username}/descriptorByName"
                "/jenkins.security.ApiTokenProperty/revoke",
                auth=(username, jenkins_token),
                headers={crumb_data["crumbRequestField"]: crumb_data["crumb"]},
                data={"tokenUuid": token_uuid},
            )
            success = revoke_resp.status_code in (200, 204)
            if success:
                logger.info("Jenkins token revoked for %s (uuid %s)", username, token_uuid[:8])
            else:
                logger.warning("Jenkins token revoke failed for %s: HTTP %s", username, revoke_resp.status_code)
            return success
    except Exception as exc:
        logger.warning("Jenkins token revocation error for %s: %s", username, type(exc).__name__)
        return False
