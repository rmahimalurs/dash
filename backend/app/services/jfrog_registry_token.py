"""Rotate the JFrog vendor entitlement credential.

JFrog issues this credential against our subscription and it is regenerated monthly
on the JFrog user page. Supplying the new one here rewrites every SOPS-encrypted
secret that carries it and commits the result to the current maintenance branch,
so it goes live with that month's maintenance.

Three secrets ride on the one credential:
  - flux-system/jfrog-repo-secret, read by the HelmRepository pointing at
    charts.jfrog.io (Opaque username/password, no host stored in it)
  - artifactory/jfrog-registry-auth and xray/jfrog-registry-auth, read by the
    product pods pulling images from releases-authenticated-docker.jfrog.io
    (dockerconfigjson, which does embed the host)

This is deliberately not a CMS Artifactory credential. artifactory.cloud.cms.gov is
a separate service with its own accounts, and the CMS chart repository
cms-devops-helm-charts is anonymous and carries no secretRef at all.
"""

import base64
import json
import logging
import os
from datetime import date, datetime, timedelta, timezone

import httpx
import yaml

from app.config import get_settings
from app.services.cert_export import _encrypt_aws_env, sops_decrypt, sops_encrypt
from app.services.jfrog_maintenance import (
    get_file,
    get_or_create_branch,
    maint_branch_name,
    merge_main_into_branch,
    put_file,
)

logger = logging.getLogger(__name__)

# JFrog mints a replacement entitlement token from a refresh token, so the
# monthly rotation does not need anyone to regenerate one by hand on the JFrog
# user page. Refreshing is authenticated with the token being replaced, which is
# the password already stored in the pull secrets, so no new input is needed.
#
# JFrog returns a NEW refresh token alongside the new access token and retires
# the one that was used, so the stored copy is stale the moment it is spent. It
# lives in 1Password rather than in a SOPS secret for exactly that reason: a
# secret in git would need a commit and a cluster apply after every rotation
# just to keep this tile working, and the 1Password entry would drift from it.
OP_VAULT_NAME = "JFrog"
OP_ITEM_TITLE = "JFrog Entitlement Refresh Token"
OP_FIELD = "credential"

# Embedded in the dockerconfigjson, so it has to match the registry the product
# images are actually pulled from.
REGISTRY_HOST = "releases-authenticated-docker.jfrog.io"

# Served by the Opaque secret. Recorded for the tile to display; the URL itself
# lives in the HelmRepository manifest, not in the secret.
CHART_HOST = "charts.jfrog.io"

# Both environments restrict encryption to the data keys, so a rewrite keeps the
# metadata readable in the diff. Prod used to encrypt the whole document; it was
# normalized on oct26-maint, and writing it back the old way would silently undo that.
ROTATE_TARGET: dict[str, dict] = {
    "dev": {
        "label": "JFrog Dev",
        "kms": "arn:aws:kms:us-east-1:116248235601:key/2596ceb4-1fd7-4a78-ae56-e9aa074dd978",
        "encrypt": {"mode": "role", "role_setting": None},
        "enc_path": "kubernetes/envs/jfrog/dev/secret/jfrog-registry-auth.enc.yaml",
        "encrypted_regex": "^(data|stringData)$",
        "secrets": [
            {"name": "jfrog-repo-secret", "namespace": "flux-system", "kind": "opaque"},
            {"name": "jfrog-registry-auth", "namespace": "artifactory", "kind": "dockerconfigjson"},
            {"name": "jfrog-registry-auth", "namespace": "xray", "kind": "dockerconfigjson"},
        ],
    },
    "prod": {
        "label": "JFrog Prod",
        "kms": "arn:aws:kms:us-east-1:623510781344:key/29a07480-5b2c-4cbd-a33f-838157e89a3c",
        "encrypt": {"mode": "role", "role_setting": "CERT_EXPORT_PROD_ROLE_ARN"},
        "enc_path": "kubernetes/envs/jfrog/prod/secret/jfrog-registry-auth.enc.yaml",
        "encrypted_regex": "^(data|stringData)$",
        "secrets": [
            {"name": "jfrog-repo-secret", "namespace": "flux-system", "kind": "opaque"},
            {"name": "jfrog-registry-auth", "namespace": "artifactory", "kind": "dockerconfigjson"},
            {"name": "jfrog-registry-auth", "namespace": "xray", "kind": "dockerconfigjson"},
        ],
    },
}


def targets() -> list[dict]:
    """Environments the tile can offer, and whether each is actually rotatable."""
    out = []
    for env, cfg in ROTATE_TARGET.items():
        ready, reason = target_ready(env)
        out.append({
            "env": env,
            "label": cfg["label"],
            "enc_path": cfg["enc_path"],
            "secret_count": len(cfg["secrets"]),
            "ready": ready,
            "reason": reason,
        })
    return out


def target_ready(env: str) -> tuple[bool, str]:
    cfg = ROTATE_TARGET.get(env)
    if not cfg:
        return False, f"Unknown environment '{env}'"
    role_setting = cfg["encrypt"].get("role_setting")
    if role_setting and not getattr(get_settings(), role_setting, ""):
        return False, f"{role_setting} is not configured, so the role needed to SOPS-encrypt {env} cannot be assumed."
    return True, ""


async def verify_credentials(username: str, password: str) -> dict:
    """Check the credential against JFrog before anything is written.

    Committing an unverified token would leave Flux and the product pods unable to
    pull until someone noticed, so a failure here aborts the rotation.

    The registry's /v2/ endpoint is the one that discriminates: 401 anonymously,
    401 on a bad token, 200 on a good one. The chart host serves its index
    anonymously, so it cannot tell a working credential from no credential and is
    not used as the check.
    """
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(f"https://{REGISTRY_HOST}/v2/", auth=(username, password))
        if resp.status_code in (401, 403):
            raise PermissionError(
                f"{REGISTRY_HOST} rejected the credential for '{username}' "
                f"({resp.status_code}). Regenerate the entitlement token on the JFrog "
                "user page and retry. Note this is a JFrog subscription credential, "
                "not a CMS Artifactory one."
            )
        resp.raise_for_status()
    return {"username": username, "registry": REGISTRY_HOST,
            "chart_host": CHART_HOST, "verified": True}


def _opaque_doc(name: str, namespace: str, username: str, password: str) -> dict:
    return {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {"name": name, "namespace": namespace},
        "type": "Opaque",
        "stringData": {"username": username, "password": password},
    }


def _dockerconfig_doc(name: str, namespace: str, username: str, password: str) -> dict:
    auth = {"auths": {REGISTRY_HOST: {"username": username, "password": password}}}
    return {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {"name": name, "namespace": namespace},
        "type": "kubernetes.io/dockerconfigjson",
        "stringData": {".dockerconfigjson": json.dumps(auth)},
    }


def build_manifest(env: str, username: str, password: str) -> str:
    cfg = ROTATE_TARGET[env]
    docs = [
        _opaque_doc(s["name"], s["namespace"], username, password)
        if s["kind"] == "opaque"
        else _dockerconfig_doc(s["name"], s["namespace"], username, password)
        for s in cfg["secrets"]
    ]
    return yaml.safe_dump_all(docs, sort_keys=False, default_flow_style=False)


def _opaque_credential(manifest: str) -> tuple[str, str]:
    """The username and password out of the decrypted pull-secret manifest.

    Read from the Opaque document rather than the dockerconfigjson, because that
    one carries the pair as plain keys instead of a base64 auth blob.
    """
    for doc in yaml.safe_load_all(manifest):
        if not doc:
            continue
        data = doc.get("stringData") or {}
        if "username" in data and "password" in data:
            return data["username"], data["password"]
    raise RuntimeError(
        "Could not find a username/password pair in the current pull secret, so "
        "there is nothing to authenticate the refresh with."
    )


def _token_subject(access_token: str, fallback: str) -> str:
    """The subject a JFrog access token authenticates as.

    The registry wants the token's own subject as the username, and a refreshed
    token can carry a different one from the token it replaced, so it is read
    from the token rather than carried over. Falls back to the previous username
    when the token is not a readable JWT.
    """
    try:
        payload = access_token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload)).get("sub") or fallback
    except Exception:  # noqa: BLE001 — an opaque token is fine, keep the old subject
        return fallback


async def _request_refresh(current_access_token: str, refresh_token: str) -> dict:
    """Exchange a refresh token for a new entitlement access token."""
    settings = get_settings()
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            settings.JFROG_TOKENS_URL,
            headers={
                "Authorization": f"Bearer {current_access_token}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={"grant_type": "refresh_token", "refresh_token": refresh_token},
        )
    if resp.status_code in (400, 401, 403):
        raise PermissionError(
            f"JFrog refused the refresh ({resp.status_code}). The stored refresh token "
            "is spent or revoked, or the token it authenticated with is no longer valid. "
            f"Regenerate the entitlement token on the JFrog user page, then update the "
            f"'{OP_ITEM_TITLE}' entry in the {OP_VAULT_NAME} 1Password vault."
        )
    resp.raise_for_status()
    body = resp.json()
    token = body.get("access_token")
    if not token:
        raise RuntimeError("JFrog returned no access_token in the refresh response.")
    return {
        "access_token": token,
        "refresh_token": body.get("refresh_token") or "",
        "expires_in": body.get("expires_in"),
    }


async def _stored_refresh_token() -> str:
    """The refresh token, read from 1Password at the moment it is used."""
    from app.services.onepassword_service import read_field
    return await read_field(OP_VAULT_NAME, OP_ITEM_TITLE, OP_FIELD)


async def _store_new_refresh_token(new_refresh: str) -> dict:
    """Replace the refresh token in 1Password with the one JFrog just issued.

    Not optional: JFrog retires the token that was spent, so without this the
    next rotation has nothing valid to present.
    """
    from app.services.onepassword_service import write_field
    return await write_field(OP_VAULT_NAME, OP_ITEM_TITLE, OP_FIELD, new_refresh)


# Reminder thresholds. The token lives about a month, so a warning much earlier
# than two weeks out would sit in the bell for most of its life and stop being
# read as a reminder at all.
EXPIRY_WARNING_DAYS = 14
EXPIRY_CRITICAL_DAYS = 5


def _expiry_state_path() -> str:
    return get_settings().JFROG_TOKEN_STATE_FILE


def _read_expiry_state() -> dict:
    try:
        with open(_expiry_state_path()) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def record_expiry(expires_at: datetime, source: str = "refresh") -> dict:
    """Remember when the entitlement token in force stops working."""
    state = {"expires_at": expires_at.date().isoformat(), "source": source,
             "recorded_at": datetime.now(timezone.utc).isoformat()}
    path = _expiry_state_path()
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        tmp = f"{path}.tmp.{os.getpid()}"
        with open(tmp, "w") as f:
            json.dump(state, f, indent=2)
        os.replace(tmp, path)
    except OSError as exc:
        logger.warning("Could not record the JFrog token expiry: %s", exc)
    return state


def expiry_status() -> dict:
    """How long the entitlement token has left, for the reminder in the bell.

    Falls back to the configured date until a refresh has reported a real one,
    so the reminder works for the token issued by hand as well.
    """
    settings = get_settings()
    state = _read_expiry_state()
    raw = state.get("expires_at") or settings.JFROG_TOKEN_EXPIRES_AT
    source = state.get("source") or "configured"
    can_refresh = bool(settings.OP_SERVICE_ACCOUNT_TOKEN)
    if not raw:
        return {"expires_at": None, "days_remaining": None, "status": "unknown",
                "source": source, "can_refresh": can_refresh}

    try:
        expires = date.fromisoformat(raw)
    except ValueError:
        return {"expires_at": raw, "days_remaining": None, "status": "unknown",
                "source": source, "can_refresh": can_refresh}

    days = (expires - date.today()).days
    if days < 0:
        status = "expired"
    elif days <= EXPIRY_CRITICAL_DAYS:
        status = "critical"
    elif days <= EXPIRY_WARNING_DAYS:
        status = "warning"
    else:
        status = "ok"
    return {
        "expires_at": expires.isoformat(),
        "days_remaining": days,
        "status": status,
        "source": source,
        "can_refresh": can_refresh,
    }


def apply_commands(env: str) -> list[dict]:
    """The commands an engineer runs to put a committed rotation into a cluster.

    This tile commits and does not apply, so without these the credential sits
    in git looking done while the clusters still hold the old one.
    """
    cfg = ROTATE_TARGET[env]
    creds = "~/.aws-dev-jfrog" if env == "dev" else "~/.aws-prod-jfrog"
    return [
        {
            "step": "Load the credentials for that account",
            "command": f"set -a; . {creds}; set +a",
        },
        {
            "step": "Decrypt and apply the pull secrets",
            "command": f"sops -d {cfg['enc_path']} | kubectl apply -f -",
        },
        {
            "step": "Restart the pods that hold the old credential",
            "command": (
                "kubectl rollout restart statefulset/artifactory -n artifactory && "
                "kubectl rollout restart statefulset/xray -n xray"
            ),
        },
        {
            "step": "Confirm Flux picked up the chart credential",
            "command": "kubectl get secret jfrog-repo-secret -n flux-system -o jsonpath='{.metadata.resourceVersion}'",
        },
    ]


async def rotate_from_refresh_token(env: str, gh_token: str) -> dict:
    """Mint a new entitlement token and rotate the pull secrets with it.

    The engineer supplies nothing: the token being replaced is read from the
    secret currently in git and used to authenticate its own replacement.
    """
    ready, reason = target_ready(env)
    if not ready:
        raise RuntimeError(reason)
    settings = get_settings()
    if not settings.OP_SERVICE_ACCOUNT_TOKEN:
        raise RuntimeError(
            "OP_SERVICE_ACCOUNT_TOKEN is not configured, so the refresh token cannot "
            "be read from 1Password. Supply the credential by hand instead."
        )
    stored_refresh = await _stored_refresh_token()

    cfg = ROTATE_TARGET[env]
    org = settings.GITHUB_ORG
    repo = settings.GITHUB_DEFAULT_REPO or "cmscloud-devops"
    branch = maint_branch_name()

    # Read the token in force from the same branch the rotation commits to, so
    # the refresh authenticates with whatever is actually current there.
    await get_or_create_branch(gh_token, org, repo, branch)
    current = await get_file(gh_token, org, repo, cfg["enc_path"], branch)
    aws_env = _encrypt_aws_env(cfg["encrypt"])
    old_username, old_password = _opaque_credential(sops_decrypt(current["content"], aws_env))

    refreshed = await _request_refresh(old_password, stored_refresh)
    new_password = refreshed["access_token"]
    new_username = _token_subject(new_password, old_username)

    result = await rotate(env, new_username, new_password, gh_token)

    # Store the replacement, or the next rotation has nothing valid to present.
    rotated_refresh = refreshed["refresh_token"]
    refresh_stored, refresh_note = False, ""
    if rotated_refresh and rotated_refresh != stored_refresh:
        try:
            await _store_new_refresh_token(rotated_refresh)
            refresh_stored = True
            refresh_note = (
                f"JFrog issued a replacement refresh token and it was written back to "
                f"1Password ({OP_VAULT_NAME} vault, '{OP_ITEM_TITLE}'). Nothing to apply."
            )
        except Exception as exc:  # noqa: BLE001 — the rotation itself already succeeded
            refresh_note = (
                "JFrog issued a replacement refresh token but it could not be stored "
                f"({exc}). The next rotation will fail until it is stored by hand."
            )
            logger.error("Could not store the replacement JFrog refresh token: %s", exc)

    expires_in = refreshed["expires_in"]
    if expires_in:
        record_expiry(datetime.now(timezone.utc) + timedelta(seconds=int(expires_in)))

    return {
        **result,
        "source": "refresh_token",
        "requested_automatically": True,
        "expires_in": refreshed["expires_in"],
        "refresh_token_rotated": bool(rotated_refresh),
        "refresh_token_stored": refresh_stored,
        "refresh_note": refresh_note,
        "apply_commands": apply_commands(env),
    }


async def rotate(env: str, username: str, password: str, gh_token: str) -> dict:
    """Verify, re-encrypt and commit the pull secrets for one environment."""
    ready, reason = target_ready(env)
    if not ready:
        raise RuntimeError(reason)
    cfg = ROTATE_TARGET[env]

    verified = await verify_credentials(username, password)

    settings = get_settings()
    org = settings.GITHUB_ORG
    repo = settings.GITHUB_DEFAULT_REPO or "cmscloud-devops"
    branch = maint_branch_name()
    await get_or_create_branch(gh_token, org, repo, branch)

    # The maintenance branch is long-lived and shared, so by the time a credential
    # is rotated it is usually behind main. Bring it up to date first, the way the
    # other tiles offer to. Unlike those, this is not optional: there is no reason
    # to want a credential committed onto a stale base.
    #
    # A conflict here is someone else's unrelated change, and refusing to rotate
    # the credential because of it would be the worse failure. The secret file is
    # self-contained, so the commit is still correct on a slightly stale branch;
    # the caller is told the sync did not happen.
    branch_synced, sync_note = True, ""
    try:
        merged = await merge_main_into_branch(gh_token, org, repo, branch)
        sync_note = f"merged main into {branch}" if merged.get("updated") else "already current with main"
    except Exception as exc:  # noqa: BLE001
        branch_synced = False
        sync_note = f"could not merge main into {branch}: {exc}"
        logger.warning("Branch sync before credential rotation failed: %s", exc)

    plaintext = build_manifest(env, username, password)
    enc = sops_encrypt(plaintext, cfg["kms"], _encrypt_aws_env(cfg["encrypt"]))

    existing = await get_file(gh_token, org, repo, cfg["enc_path"], branch)
    await put_file(
        gh_token, org, repo, cfg["enc_path"], enc, existing["sha"],
        f"chore({env}): rotate Artifactory pull credentials for {username}", branch,
    )

    logger.info("Rotated Artifactory pull secrets for %s on %s", env, branch)
    return {
        "env": env,
        "branch": branch,
        "branch_synced": branch_synced,
        "sync_note": sync_note,
        "path": cfg["enc_path"],
        "secrets": [f"{s['namespace']}/{s['name']}" for s in cfg["secrets"]],
        "verified": verified,
    }
