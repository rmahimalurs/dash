"""
Wildcard TLS certificate export automation.

Flow (see COMET runbook "Request a Certificate with ACM and Update the Tools to
Use It", page 1422104777):

  1. Export the ACM wildcard cert with a generated passphrase (boto3).
  2. Strip the passphrase from the private key (cryptography, in-process).
  3. Store cert / chain / TLS key (+ passphrase) in the 1Password DevOps vault.
  4. Build a kubernetes.io/tls Secret and SOPS-encrypt it with the target KMS key.
  5. Open a PR against main with the resulting .enc.yaml.

"One shared *.cloud.cms.gov cert per environment": dev and prod each have a
single ACM cert; the JFrog and CBJ tiles export the same per-env cert but write
their own .enc.yaml (different cluster / KMS / path).
"""
import base64
import logging
import os
import secrets
import string
import subprocess
import tempfile

import boto3
import httpx
from cryptography.hazmat.primitives import serialization

from app.config import get_settings
from app.services.jfrog_maintenance import (
    _gh_headers,
    get_or_create_branch,
    get_file,
    put_file,
)

logger = logging.getLogger(__name__)

GH_ORG = "CMS-Enterprise"
GH_REPO = "cmscloud-devops"

# ── Per-environment ACM cert source (shared across JFrog + CBJ) ────────────────
# assume_role: None = use the dashboard's own creds (pod identity); otherwise
# an ARN to assume (prod certs live in the JFrog prod account).
CERT_SOURCE = {
    "dev": {
        "arn": "arn:aws:acm:us-east-1:116248235601:certificate/3a2f6998-400f-4615-a5a5-b4a70b481943",
        "region": "us-east-1",
        "assume_role": None,
    },
    "prod": {
        # ARN discovered by domain in the prod account if left None.
        "arn": None,
        "domain": "*.cloud.cms.gov",
        "region": "us-east-1",
        "assume_role_setting": "CERT_EXPORT_PROD_ROLE_ARN",
    },
}

# ── Per (tool, env) deploy target ──────────────────────────────────────────────
# cert_env : which CERT_SOURCE cert to export (dev/prod). There is NO separate west
#            cert — GovCloud clusters reuse the same commercial *.cloud.cms.gov cert.
# kms      : the target cluster's SOPS KMS key used to encrypt the .enc.yaml.
# encrypt  : how to get creds for the SOPS encrypt (the export uses CERT_SOURCE creds):
#            {"mode":"role","role_setting":<cfg attr|None>}  -> assume that role, or
#              None = the dashboard's own creds (same-account keys).
#            {"mode":"govcloud","creds_prefix":"GOVCLOUD"|"GOVCLOUD_PROD"} -> static
#              in-account GovCloud IAM user creds (aws-us-gov, us-gov-west-1).
# secrets  : one or more k8s TLS secrets to (re)write from the SAME cert. CBJ has two
#            per env (ingress-nginx + cjoc); JFrog has one.
_JENKINS = "kubernetes/envs/jenkins"
DEPLOY_TARGET = {
    ("jfrog", "dev"): {
        "cert_env": "dev",
        "kms": "arn:aws:kms:us-east-1:116248235601:key/2596ceb4-1fd7-4a78-ae56-e9aa074dd978",
        "encrypt": {"mode": "role", "role_setting": None},
        "secrets": [
            # nginx ingress default cert
            {"name": "dev-east", "namespace": "ingress-nginx",
             "enc_path": "kubernetes/envs/jfrog/dev/secret/dev-east-tls.enc.yaml"},
            # Artifactory ingress cert (artifactory.cloud.cms.gov)
            {"name": "artifactory-tls", "namespace": "artifactory",
             "enc_path": "kubernetes/envs/jfrog/dev/secret/artifactory-tls.enc.yaml"},
        ],
    },
    ("jfrog", "prod"): {
        "cert_env": "prod",
        "kms": "arn:aws:kms:us-east-1:623510781344:key/29a07480-5b2c-4cbd-a33f-838157e89a3c",
        "encrypt": {"mode": "role", "role_setting": "CERT_EXPORT_PROD_ROLE_ARN"},
        "secrets": [
            # nginx ingress default cert
            {"name": "prod-east", "namespace": "ingress-nginx",
             "enc_path": "kubernetes/envs/jfrog/prod/secret/prod-east-tls.enc.yaml"},
            # Artifactory ingress cert (artifactory.cloud.cms.gov)
            {"name": "artifactory-tls", "namespace": "artifactory",
             "enc_path": "kubernetes/envs/jfrog/prod/secret/artifactory-tls.enc.yaml"},
        ],
    },
    # ── CloudBees CI: 4 clusters, each with an ingress + a cjoc TLS secret ─────
    ("cbj", "dev-east"): {
        "cert_env": "dev",
        "kms": "arn:aws:kms:us-east-1:280350076387:key/b247b61b-fc1d-48d1-8738-d9aa1d73367e",
        "encrypt": {"mode": "role", "role_setting": "JENKINS_DEV_EAST_ROLE_ARN"},
        "secrets": [
            {"name": "dev-east", "namespace": "ingress-nginx",
             "enc_path": f"{_JENKINS}/dev-east/secret/dev-east-ingress-tls.enc.yaml"},
            {"name": "jenkins-dev-east-tls", "namespace": "cjoc",
             "enc_path": f"{_JENKINS}/dev-east/secret/dev-east-cjoc-tls.enc.yaml"},
        ],
    },
    ("cbj", "prod-east"): {
        "cert_env": "prod",
        "kms": "arn:aws:kms:us-east-1:478919403635:key/7c481d70-bfa9-4551-b042-174dcb178950",
        "encrypt": {"mode": "role", "role_setting": "JENKINS_PROD_EAST_ROLE_ARN"},
        "secrets": [
            {"name": "prod-east", "namespace": "ingress-nginx",
             "enc_path": f"{_JENKINS}/prod-east/secret/prod-east-ingress-tls.enc.yaml"},
            {"name": "jenkins-prod-east-tls", "namespace": "cjoc",
             "enc_path": f"{_JENKINS}/prod-east/secret/prod-east-cjoc-tls.enc.yaml"},
        ],
    },
    ("cbj", "gc-dev-west"): {
        "cert_env": "dev",
        "kms": "arn:aws-us-gov:kms:us-gov-west-1:021175979101:key/36562fe7-45ca-4e28-983e-f38fa161c591",
        "encrypt": {"mode": "govcloud", "creds_prefix": "GOVCLOUD"},
        "secrets": [
            {"name": "gc-dev-west", "namespace": "ingress-nginx",
             "enc_path": f"{_JENKINS}/gc-dev-west/secret/gc-dev-west-ingress-tls.enc.yaml"},
            {"name": "gc-dev-west", "namespace": "cjoc",
             "enc_path": f"{_JENKINS}/gc-dev-west/secret/gc-dev-west-cjoc-tls.enc.yaml"},
        ],
    },
    ("cbj", "gc-prod-west"): {
        "cert_env": "prod",
        "kms": "arn:aws-us-gov:kms:us-gov-west-1:020847197482:key/b4bfca02-ab5b-438b-a858-1d4caaf5e863",
        "encrypt": {"mode": "govcloud", "creds_prefix": "GOVCLOUD_PROD"},
        "secrets": [
            {"name": "gc-prod-west", "namespace": "ingress-nginx",
             "enc_path": f"{_JENKINS}/gc-prod-west/secret/gc-prod-west-ingress-tls.enc.yaml"},
            {"name": "gc-prod-west", "namespace": "cjoc",
             "enc_path": f"{_JENKINS}/gc-prod-west/secret/gc-prod-west-cjoc-tls.enc.yaml"},
        ],
    },
}

OP_ITEM_PREFIX = {"dev": "Dev Wildcard", "prod": "Prod Wildcard"}
_OP_INTEGRATION = ("devops-dashboard", "1.0.0")


# ── AWS helpers ────────────────────────────────────────────────────────────────
def _assume_creds(role_arn: str, session_name: str) -> dict:
    """Assume a cross-account role, return credentials kwargs."""
    sts = boto3.client("sts")
    resp = sts.assume_role(RoleArn=role_arn, RoleSessionName=session_name)
    c = resp["Credentials"]
    return {
        "aws_access_key_id": c["AccessKeyId"],
        "aws_secret_access_key": c["SecretAccessKey"],
        "aws_session_token": c["SessionToken"],
    }


def target_ready(tool: str, env: str) -> tuple[bool, str]:
    """Whether a (tool, env) target can actually run: KMS key + the encrypt creds
    it needs are configured. Returns (ready, reason-if-not)."""
    settings = get_settings()
    t = DEPLOY_TARGET.get((tool, env))
    if not t or not t.get("kms"):
        return False, "no KMS key"
    enc = t["encrypt"]
    if enc.get("mode") == "govcloud":
        prefix = enc["creds_prefix"]
        if not (getattr(settings, f"{prefix}_AWS_ACCESS_KEY_ID", "")
                and getattr(settings, f"{prefix}_AWS_SECRET_ACCESS_KEY", "")):
            return False, f"{prefix} GovCloud creds not configured"
        return True, ""
    role_setting = enc.get("role_setting")
    if role_setting and not getattr(settings, role_setting, ""):
        return False, f"{role_setting} not configured"
    return True, ""


def _encrypt_aws_env(encrypt_cfg: dict) -> dict:
    """Build the env-var overrides sops runs with, based on the target's encrypt mode.

    - role:     assume `role_setting` (cross-account KMS) or {} for dashboard creds.
    - govcloud: static in-account GovCloud IAM user creds (aws-us-gov). Session token
                and pod-identity vars are cleared so the SDK uses only these keys, and
                the region is pinned to us-gov-west-1.
    """
    settings = get_settings()
    mode = encrypt_cfg.get("mode", "role")
    if mode == "govcloud":
        prefix = encrypt_cfg["creds_prefix"]  # GOVCLOUD | GOVCLOUD_PROD
        ak = getattr(settings, f"{prefix}_AWS_ACCESS_KEY_ID", "")
        sk = getattr(settings, f"{prefix}_AWS_SECRET_ACCESS_KEY", "")
        if not (ak and sk):
            raise RuntimeError(
                f"{prefix}_AWS_ACCESS_KEY_ID/SECRET not configured — cannot SOPS-encrypt "
                "the GovCloud TLS secret."
            )
        return {
            "AWS_ACCESS_KEY_ID": ak,
            "AWS_SECRET_ACCESS_KEY": sk,
            # clear any pod-identity / assumed-role creds so only the static keys apply
            "AWS_SESSION_TOKEN": "",
            "AWS_CONTAINER_CREDENTIALS_FULL_URI": "",
            "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI": "",
            "AWS_WEB_IDENTITY_TOKEN_FILE": "",
            "AWS_ROLE_ARN": "",
            "AWS_DEFAULT_REGION": "us-gov-west-1",
            "AWS_REGION": "us-gov-west-1",
        }
    # role mode
    role_setting = encrypt_cfg.get("role_setting")
    role_arn = getattr(settings, role_setting, "") if role_setting else None
    if role_setting and not role_arn:
        raise RuntimeError(
            f"{role_setting} is not configured — cannot assume the role needed to "
            "SOPS-encrypt this secret."
        )
    if role_arn:
        creds = _assume_creds(role_arn, "dashboard-cert-sops")
        return {
            "AWS_ACCESS_KEY_ID": creds["aws_access_key_id"],
            "AWS_SECRET_ACCESS_KEY": creds["aws_secret_access_key"],
            "AWS_SESSION_TOKEN": creds["aws_session_token"],
        }
    return {}  # dashboard's own creds (same-account KMS key)


def _gen_passphrase(n: int = 40) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(n))


def _cert_fingerprint(pem: str) -> str:
    """SHA-256 fingerprint of a PEM cert — the identity used to detect a new
    (renewed/rotated) cert. Changes whenever ACM reissues the cert."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes

    return x509.load_pem_x509_certificate(pem.strip().encode()).fingerprint(hashes.SHA256()).hex()


def _resolve_cert_arn(env: str, creds: dict, region: str) -> str:
    src = CERT_SOURCE[env]
    if src.get("arn"):
        return src["arn"]
    # discover by domain
    acm = boto3.client("acm", region_name=region, **creds)
    for page in acm.get_paginator("list_certificates").paginate(
        CertificateStatuses=["ISSUED"]
    ):
        for c in page["CertificateSummaryList"]:
            if c.get("DomainName") == src.get("domain"):
                return c["CertificateArn"]
    raise RuntimeError(f"No ISSUED ACM cert matching {src.get('domain')} in {env} account")


def export_cert(env: str) -> dict:
    """Export the per-env wildcard cert. Returns cert, chain, tls_key (no
    passphrase), and the passphrase used."""
    settings = get_settings()
    src = CERT_SOURCE[env]
    region = src["region"]

    role_setting = src.get("assume_role_setting")
    role_arn = getattr(settings, role_setting, "") if role_setting else src.get("assume_role")
    creds = _assume_creds(role_arn, "dashboard-cert-export") if role_arn else {}

    arn = _resolve_cert_arn(env, creds, region)
    passphrase = _gen_passphrase()

    acm = boto3.client("acm", region_name=region, **creds)
    resp = acm.export_certificate(
        CertificateArn=arn, Passphrase=passphrase.encode()
    )
    enc_key_pem = resp["PrivateKey"].encode()

    # strip the passphrase from the private key
    key_obj = serialization.load_pem_private_key(enc_key_pem, password=passphrase.encode())
    tls_key = key_obj.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()

    return {
        "arn": arn,
        "cert": resp["Certificate"],
        "chain": resp.get("CertificateChain", ""),
        "tls_key": tls_key,
        "passphrase": passphrase,
    }


# ── 1Password ──────────────────────────────────────────────────────────────────
async def store_in_1password(env: str, exported: dict) -> list[str]:
    """Upsert the cert, chain, and TLS key (with passphrase) into the DevOps
    vault. Returns the item titles written."""
    from onepassword.client import Client
    from onepassword import (
        ItemCreateParams,
        ItemCategory,
        ItemField,
        ItemFieldType,
    )

    settings = get_settings()
    token = settings.OP_SERVICE_ACCOUNT_TOKEN
    vault_name = settings.OP_VAULT
    if not token or not vault_name:
        raise RuntimeError("OP_SERVICE_ACCOUNT_TOKEN / OP_VAULT not configured")

    client = await Client.authenticate(
        auth=token, integration_name=_OP_INTEGRATION[0], integration_version=_OP_INTEGRATION[1]
    )
    vault_id = None
    for v in await client.vaults.list():
        if v.title == vault_name:
            vault_id = v.id
            break
    if vault_id is None:
        raise RuntimeError(
            f"1Password vault '{vault_name}' not visible to the service account. "
            "Grant the service account write access to the vault in 1Password."
        )

    prefix = OP_ITEM_PREFIX[env]
    # title -> (notes body, extra concealed fields)
    plan = {
        f"{prefix} Cert": (exported["cert"], []),
        f"{prefix} Chain": (exported["chain"], []),
        f"{prefix} TLS key": (
            exported["tls_key"],
            [ItemField(id="passphrase", title="passphrase", field_type=ItemFieldType.CONCEALED, value=exported["passphrase"])],
        ),
    }

    # index existing items by title in the vault
    existing = {}
    for it in await client.items.list(vault_id):
        existing[it.title] = it.id

    # Idempotency: only write when the cert actually changed (renewed/rotated).
    # Compare the exported cert's fingerprint to the one already stored.
    cert_title = f"{prefix} Cert"
    if cert_title in existing:
        stored = await client.items.get(vault_id, existing[cert_title])
        try:
            if stored.notes and _cert_fingerprint(stored.notes) == _cert_fingerprint(exported["cert"]):
                return {"changed": False, "items": []}
        except Exception:
            pass  # unparseable stored cert → treat as changed and overwrite

    written = []
    for title, (notes, fields) in plan.items():
        if title in existing:
            item = await client.items.get(vault_id, existing[title])
            item.notes = notes
            if fields:
                item.fields = fields
            await client.items.put(item)
        else:
            await client.items.create(
                ItemCreateParams(
                    title=title,
                    category=ItemCategory.SECURENOTE,
                    vault_id=vault_id,
                    fields=fields,
                    notes=notes,
                )
            )
        written.append(title)
    return {"changed": True, "items": written}


# ── SOPS-encrypted TLS secret ───────────────────────────────────────────────────
def _tls_secret_yaml(name: str, namespace: str, cert_chain: str, tls_key: str) -> str:
    crt_b64 = base64.b64encode(cert_chain.encode()).decode()
    key_b64 = base64.b64encode(tls_key.encode()).decode()
    return (
        "apiVersion: v1\n"
        "kind: Secret\n"
        "type: kubernetes.io/tls\n"
        "metadata:\n"
        f"  name: {name}\n"
        f"  namespace: {namespace}\n"
        "data:\n"
        f"  tls.crt: {crt_b64}\n"
        f"  tls.key: {key_b64}\n"
    )


def sops_encrypt(secret_yaml: str, kms_arn: str, aws_env: dict) -> str:
    """SOPS-encrypt a manifest with the given KMS key; returns the .enc.yaml text."""
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
        f.write(secret_yaml)
        path = f.name
    try:
        env = {**os.environ, **aws_env}
        proc = subprocess.run(
            ["sops", "--encrypt", "--kms", kms_arn,
             "--encrypted-regex", "^(data|stringData)$", path],
            capture_output=True, text=True, env=env, timeout=60,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"sops encrypt failed: {proc.stderr.strip()[:300]}")
        return proc.stdout
    finally:
        os.unlink(path)


def sops_decrypt(enc_yaml: str, aws_env: dict) -> str:
    """SOPS-decrypt an .enc.yaml (KMS key read from its embedded sops metadata);
    returns the plaintext manifest. Needs kms:Decrypt on that key."""
    with tempfile.NamedTemporaryFile("w", suffix=".enc.yaml", delete=False) as f:
        f.write(enc_yaml)
        path = f.name
    try:
        env = {**os.environ, **aws_env}
        proc = subprocess.run(
            ["sops", "--decrypt", path],
            capture_output=True, text=True, env=env, timeout=60,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"sops decrypt failed: {proc.stderr.strip()[:300]}")
        return proc.stdout
    finally:
        os.unlink(path)


def _secret_leaf_fp(decrypted_yaml: str) -> str | None:
    """SHA-256 fingerprint of the leaf cert inside a decrypted TLS-secret manifest,
    or None if it can't be extracted."""
    import re

    m = re.search(r"tls\.crt:\s*([A-Za-z0-9+/=]+)", decrypted_yaml)
    if not m:
        return None
    try:
        pem = base64.b64decode(m.group(1)).decode()
        return _cert_fingerprint(pem)  # loads the FIRST (leaf) cert in the chain
    except Exception:
        return None


# ── GitHub PR ───────────────────────────────────────────────────────────────────
async def _open_pr(token: str, branch: str, title: str, body: str) -> str:
    url = f"https://api.github.com/repos/{GH_ORG}/{GH_REPO}/pulls"
    async with httpx.AsyncClient(timeout=30) as client:
        # reuse an existing open PR from this branch if present
        existing = await client.get(url, headers=_gh_headers(token),
                                    params={"head": f"{GH_ORG}:{branch}", "base": "main", "state": "open"})
        if existing.status_code == 200 and existing.json():
            return existing.json()[0]["html_url"]
        resp = await client.post(url, headers=_gh_headers(token),
                                 json={"title": title, "body": body, "head": branch, "base": "main"})
        if not resp.is_success:
            raise RuntimeError(f"PR open failed: {resp.status_code} {resp.text[:300]}")
        return resp.json()["html_url"]


# ── Orchestration ───────────────────────────────────────────────────────────────
async def run_export(tool: str, env: str, username: str | None = None) -> dict:
    """Full flow for a (tool, env) tile. Returns a summary.

    The PR is opened with the requesting engineer's GitHub PAT when they have one
    stored + unlocked (so it is attributed to them), otherwise the service account.
    """
    import asyncio

    from app.services import github_auth

    settings = get_settings()
    target = DEPLOY_TARGET.get((tool, env))
    if not target:
        raise RuntimeError(f"Unknown target {tool}/{env}")
    if not target["kms"]:
        raise RuntimeError(
            f"{tool}/{env} is not fully configured yet (missing KMS key for the enc file)."
        )
    gh_token = github_auth.resolve_github_auth(username)["token"]
    if not gh_token:
        raise RuntimeError("GITHUB_TOKEN is not configured")

    cert_env = target["cert_env"]  # which commercial cert to export (dev/prod)

    # 1-2) export + strip the commercial *.cloud.cms.gov cert (blocking → thread)
    exported = await asyncio.to_thread(export_cert, cert_env)

    # 3) 1Password — idempotent store. This is a SIDE-EFFECT only; it must NOT
    #    gate the PR. (A prior run can leave the cert in 1Password while the git
    #    secret / cluster was never updated — the old bug returned "unchanged"
    #    here and never opened the PR.)
    op = await store_in_1password(cert_env, exported)
    op_items = op["items"]
    enc_paths = [s["enc_path"] for s in target["secrets"]]

    # 4) Drive the PR off the DEPLOYED state: for each target secret, compare the
    #    cert committed on `main` against the freshly-exported one. A secret is
    #    "stale" when its enc file is missing on main or decrypts to a different
    #    leaf cert. Only stale secrets get committed; if none are stale we're done.
    aws_env = await asyncio.to_thread(_encrypt_aws_env, target["encrypt"])
    exported_fp = _cert_fingerprint(exported["cert"])
    token = gh_token

    stale: list[dict] = []
    for s in target["secrets"]:
        try:
            existing = await get_file(token, GH_ORG, GH_REPO, s["enc_path"], "main")
        except Exception:
            stale.append(s)  # missing on main → needs the PR
            continue
        try:
            dec = await asyncio.to_thread(sops_decrypt, existing["content"], aws_env)
            if _secret_leaf_fp(dec) == exported_fp:
                continue  # already deployed with this exact cert
        except Exception:
            pass  # can't decrypt/parse → treat as stale and overwrite
        stale.append(s)

    if not stale:
        return {
            "status": "unchanged",
            "cert_arn": exported["arn"],
            "op_items": op_items,
            "enc_paths": enc_paths,
            "pr_url": None,
            "message": "Certificate already deployed to every target secret on main — nothing to do.",
        }

    # 5) SOPS-encrypt + commit only the stale secrets to a branch, then open/reuse
    #    one PR. Skip a file already staged on the branch with the right cert.
    cert_chain = exported["cert"] + ("\n" + exported["chain"] if exported["chain"] else "")
    branch = f"cert-export/{tool}-{env}-wildcard"
    await get_or_create_branch(token, GH_ORG, GH_REPO, branch)
    committed: list[str] = []
    for s in stale:
        path = s["enc_path"]
        sha = None
        try:
            cur = await get_file(token, GH_ORG, GH_REPO, path, branch)
            sha = cur["sha"]
            try:
                dec = await asyncio.to_thread(sops_decrypt, cur["content"], aws_env)
                if _secret_leaf_fp(dec) == exported_fp:
                    committed.append(path)  # branch already has it
                    continue
            except Exception:
                pass
        except Exception:
            sha = None
        secret_yaml = _tls_secret_yaml(s["name"], s["namespace"], cert_chain, exported["tls_key"])
        enc_yaml = await asyncio.to_thread(sops_encrypt, secret_yaml, target["kms"], aws_env)
        await put_file(token, GH_ORG, GH_REPO, path, enc_yaml, sha,
                       f"chore({tool}/{env}): rotate wildcard TLS cert", branch)
        committed.append(path)

    secret_list = ", ".join(f"{s['namespace']}/{s['name']}" for s in stale)
    pr_url = await _open_pr(
        token, branch,
        f"{tool}/{env}: rotate wildcard TLS cert",
        f"Automated wildcard cert export for **{tool} {env}** (cert env: {cert_env}).\n\n"
        f"- Exported ACM cert `{exported['arn']}`\n"
        f"- Stored in 1Password (vault `{settings.OP_VAULT}`): {', '.join(op_items) or '(already current)'}\n"
        f"- Updated secrets ({secret_list}), SOPS/KMS encrypted:\n"
        + "".join(f"  - `{p}`\n" for p in committed)
        + "\nReview and merge, then apply the secrets to the cluster.",
    )

    return {
        "status": "updated",
        "cert_arn": exported["arn"],
        "op_items": op_items,
        "enc_paths": committed,
        "pr_url": pr_url,
        "message": "Certificate exported; PR opened to update the target secret(s).",
    }
