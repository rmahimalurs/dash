"""EKS control-plane upgrade advisor.

Three reads feed the card: the upgrade targets AWS currently offers for the
region, the Kubernetes release notes for the target minor, and a pluto scan of
the GitOps manifests for API versions the target removes.

Apply bumps `eks_version` in the cluster's tfvars and realigns the gold image,
which is named for the cluster version (``al2023-eks-<ver>-gi-*``), so the
control plane and the nodes never land on different minors.
"""
from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import re
import shutil
import subprocess
import tarfile
import tempfile

import httpx

from app.services.cloudbees_maintenance import boto3_client
from app.services.jfrog_maintenance import (
    conflict_markers,
    get_branch_or_none,
    get_file,
    get_or_create_branch,
    maint_branch_name,
    merge_main_into_branch,
    patch_ami_in_nodeclass,
    patch_ami_in_tfvars,
    put_file,
    _gh_headers,
)

logger = logging.getLogger(__name__)

PLUTO_BIN = os.environ.get("PLUTO_BIN", "/usr/local/bin/pluto")

# Every cluster whose control-plane version this card manages. aws_name is the
# real EKS cluster name, which is not the key: both CloudBees east clusters are
# called jenkins-kms, in different accounts. manifest_dirs are
# the GitOps paths pluto scans for that cluster: its own overlay plus the bases
# it reconciles. nodeclass_paths is empty where a cluster inherits its AMI from a
# shared base that another env owns (JFrog prod inherits JFrog dev's base).
EKS_CLUSTERS = {
    "cbj-dev-east": {
        "aws_name": "jenkins-kms",
        "describe_role_setting": "JENKINS_DEV_EAST_ROLE_ARN",
        "label": "CloudBees Commercial Dev (East)",
        "family": "CloudBees",
        "tfvars_path": "terraform/envs/jenkins/envs/dev-east/terraform.tfvars",
        "nodeclass_paths": ["kubernetes/envs/jenkins/dev-east/cluster-ops/karpenter-node-class.yaml"],
        "manifest_dirs": ["kubernetes/envs/jenkins/dev-east", "kubernetes/base/jenkins", "kubernetes/base/releases"],
        "region": "us-east-1",
        "ami_owner": "743302140042",
        "creds": "commercial",
    },
    "cbj-gc-dev-west": {
        "aws_name": "jenkins-dev-west-gov",
        "label": "CloudBees Gov Cloud Dev (West)",
        "family": "CloudBees",
        "tfvars_path": "terraform/envs/jenkins/envs/gc-dev-west/terraform.tfvars",
        "nodeclass_paths": ["kubernetes/envs/jenkins/gc-dev-west/cluster-ops/karpenter-node-class.yaml"],
        "manifest_dirs": ["kubernetes/envs/jenkins/gc-dev-west", "kubernetes/base/jenkins", "kubernetes/base/releases"],
        "region": "us-gov-west-1",
        "ami_owner": "021568039808",
        "creds": "govcloud-dev",
    },
    "cbj-prod-east": {
        "aws_name": "jenkins-kms",
        "describe_role_setting": "JENKINS_PROD_EAST_ROLE_ARN",
        "label": "CloudBees Commercial Prod (East)",
        "family": "CloudBees",
        "tfvars_path": "terraform/envs/jenkins/envs/prod-east/terraform.tfvars",
        "nodeclass_paths": ["kubernetes/envs/jenkins/prod-east/cluster-ops/karpenter-node-class.yaml"],
        "manifest_dirs": ["kubernetes/envs/jenkins/prod-east", "kubernetes/base/jenkins", "kubernetes/base/releases"],
        "region": "us-east-1",
        "ami_owner": "743302140042",
        "creds": "commercial",
        "is_prod": True,
    },
    "cbj-gc-prod-west": {
        "aws_name": "jenkins-west-gov",
        "label": "CloudBees Gov Cloud Prod (West)",
        "family": "CloudBees",
        "tfvars_path": "terraform/envs/jenkins/envs/gc-prod-west/terraform.tfvars",
        "nodeclass_paths": ["kubernetes/envs/jenkins/gc-prod-west/cluster-ops/karpenter-node-class.yaml"],
        "manifest_dirs": ["kubernetes/envs/jenkins/gc-prod-west", "kubernetes/base/jenkins", "kubernetes/base/releases"],
        "region": "us-gov-west-1",
        "ami_owner": "021568039808",
        "creds": "govcloud-prod",
        "is_prod": True,
    },
    "jfrog-dev": {
        "aws_name": "jfrog-dev",
        "label": "JFrog Dev",
        "family": "JFrog",
        "tfvars_path": "terraform/envs/jfrog/envs/dev/terraform.tfvars",
        "nodeclass_paths": ["kubernetes/base/jfrog/cluster-ops/karpenter-node-class.yaml"],
        "manifest_dirs": ["kubernetes/envs/jfrog/dev", "kubernetes/base/jfrog", "kubernetes/base/releases"],
        "region": "us-east-1",
        "ami_owner": "743302140042",
        "creds": "commercial",
    },
    "jfrog-prod": {
        "aws_name": "jfrog-prod",
        "describe_role_setting": "CERT_EXPORT_PROD_ROLE_ARN",
        "label": "JFrog Prod",
        "family": "JFrog",
        "tfvars_path": "terraform/envs/jfrog/envs/prod/terraform.tfvars",
        # Not inherited from the base: the prod overlay lists this nodeclass under
        # kustomize patches, so it overrides the base and an upgrade that skipped
        # it left the nodes on the old minor while tfvars claimed the new one.
        "nodeclass_paths": ["kubernetes/envs/jfrog/prod/cluster-ops/karpenter-node-class.yaml"],
        "manifest_dirs": ["kubernetes/envs/jfrog/prod", "kubernetes/base/jfrog", "kubernetes/base/releases"],
        "region": "us-east-1",
        "ami_owner": "743302140042",
        "creds": "commercial",
        "is_prod": True,
    },
}


def resolve_describe_creds(cluster_key: str, settings) -> dict:
    """Credentials for reading one cluster's own state.

    Separate from resolve_creds on purpose. That one is shared with the AMI and
    version-catalogue lookups, which run against the dashboard's own account on
    Pod Identity; pointing it elsewhere would move those too. Reading a cluster
    has to happen in the account that owns it, so commercial clusters outside
    jfrog-dev go through the role the dashboard already assumes there. GovCloud
    needs nothing extra: its IAM user keys already belong to the right account.
    """
    creds = dict(resolve_creds(cluster_key, settings))
    setting = EKS_CLUSTERS[cluster_key].get("describe_role_setting")
    if setting and not creds.get("aws_access_key_id"):
        creds["assume_role_arn"] = getattr(settings, setting, "") or None
    return creds


def resolve_creds(cluster_key: str, settings) -> dict:
    """Credential kwargs for a cluster's AWS calls. Commercial rides Pod Identity."""
    kind = EKS_CLUSTERS[cluster_key]["creds"]
    if kind == "govcloud-dev":
        return {
            "assume_role_arn": settings.GOVCLOUD_DEV_ROLE_ARN or None,
            "aws_access_key_id": settings.GOVCLOUD_AWS_ACCESS_KEY_ID or None,
            "aws_secret_access_key": settings.GOVCLOUD_AWS_SECRET_ACCESS_KEY or None,
        }
    if kind == "govcloud-prod":
        return {
            "assume_role_arn": None,
            "aws_access_key_id": settings.GOVCLOUD_PROD_AWS_ACCESS_KEY_ID or None,
            "aws_secret_access_key": settings.GOVCLOUD_PROD_AWS_SECRET_ACCESS_KEY or None,
        }
    return {}


# ─── Versions ─────────────────────────────────────────────────────────────────

def extract_eks_version(content: str) -> str | None:
    m = re.search(r'eks_version\s*=\s*"([0-9]+\.[0-9]+)"', content)
    return m.group(1) if m else None


def patch_eks_version(content: str, new_version: str) -> str:
    return re.sub(r'(eks_version\s*=\s*")[0-9]+\.[0-9]+(")', f'\\g<1>{new_version}\\g<2>', content, count=1)


def version_tuple(v: str) -> tuple:
    try:
        return tuple(int(x) for x in v.split(".")[:2])
    except Exception:
        return (0, 0)


async def running_version(cluster_key: str, settings, declared: str | None = None) -> str | None:
    """What a cluster is running, falling back to the declared version.

    Gold images are named for a Kubernetes minor, so whichever version this
    returns decides which image the maintenance modals offer. It has to be the
    running one: picking by the declared version offers the nodes an image for a
    control plane that does not exist yet.
    """
    if cluster_key not in EKS_CLUSTERS:
        return declared
    got = await fetch_live_version(
        cluster_key, EKS_CLUSTERS[cluster_key]["region"],
        resolve_describe_creds(cluster_key, settings))
    return got["live_version"] or declared


async def fetch_available_versions(region: str, creds: dict) -> dict:
    """Upgrade targets AWS offers in a region, newest first.

    includeAll picks up extended-support minors too, so the card can show that a
    target is already past end of standard support rather than hiding it.
    """
    def _describe() -> list[dict]:
        eks = boto3_client("eks", region, **creds)
        rows: list[dict] = []
        token = None
        while True:
            kwargs = {"includeAll": True, "maxResults": 100}
            if token:
                kwargs["nextToken"] = token
            resp = eks.describe_cluster_versions(**kwargs)
            for cv in resp.get("clusterVersions", []):
                rows.append({
                    "version": cv.get("clusterVersion"),
                    "status": cv.get("status"),
                    "default": bool(cv.get("defaultVersion")),
                    "release_date": _iso(cv.get("releaseDate")),
                    "end_of_standard_support": _iso(cv.get("endOfStandardSupportDate")),
                    "end_of_extended_support": _iso(cv.get("endOfExtendedSupportDate")),
                    "patch_version": cv.get("kubernetesPatchVersion"),
                })
            token = resp.get("nextToken")
            if not token:
                break
        return rows

    try:
        rows = await asyncio.to_thread(_describe)
    except Exception as exc:
        logger.warning("EKS describe_cluster_versions failed in %s: %s", region, exc)
        return {"versions": [], "error": str(exc)[:200]}

    # Collapse to one row per minor (the API can return several patch rows).
    seen: dict[str, dict] = {}
    for r in rows:
        v = r["version"]
        if v and v not in seen:
            seen[v] = r
    ordered = sorted(seen.values(), key=lambda r: version_tuple(r["version"]), reverse=True)
    return {"versions": ordered, "error": None}


async def fetch_live_version(cluster_key: str, region: str, creds: dict) -> dict:
    """The version the control plane is actually running.

    tfvars says what Terraform intends, which is not the same thing: a staged
    bump sits in the branch until somebody applies it. Reporting the declared
    value as the current one made JFrog prod read 1.35 while the cluster was on
    1.34, and it hides exactly the case the card exists to catch.
    """
    name = EKS_CLUSTERS[cluster_key].get("aws_name") or cluster_key

    def _describe() -> str | None:
        eks = boto3_client("eks", region, **creds)
        return (eks.describe_cluster(name=name).get("cluster") or {}).get("version")

    try:
        return {"live_version": await asyncio.to_thread(_describe), "error": None}
    except Exception as exc:  # noqa: BLE001 — one unreadable cluster must not fail the card
        logger.warning("EKS describe_cluster failed for %s: %s", name, exc)
        return {"live_version": None, "error": str(exc)[:200]}


def _iso(value) -> str | None:
    return value.date().isoformat() if hasattr(value, "date") else (str(value) if value else None)


async def fetch_gold_image_for_version(region: str, owner: str, version: str, creds: dict) -> dict:
    """Newest gold image built for a cluster version (al2023-eks-<ver>-gi-*)."""
    def _describe() -> dict:
        ec2 = boto3_client("ec2", region, **creds)
        resp = ec2.describe_images(
            Owners=[owner],
            Filters=[
                {"Name": "name", "Values": [f"al2023-eks-{version}-gi-*"]},
                {"Name": "state", "Values": ["available"]},
            ],
        )
        images = sorted(resp["Images"], key=lambda x: x["CreationDate"])
        if not images:
            raise RuntimeError(f"No gold image published for EKS {version} in {region} yet")
        latest = images[-1]
        return {"ami_id": latest["ImageId"], "ami_name": latest["Name"], "error": None}

    try:
        return await asyncio.to_thread(_describe)
    except Exception as exc:
        logger.warning("Gold image lookup failed for %s in %s: %s", version, region, exc)
        return {"ami_id": None, "ami_name": None, "error": str(exc)[:200]}


# ─── Kubernetes release notes ─────────────────────────────────────────────────

_CHANGELOG_URL = "https://raw.githubusercontent.com/kubernetes/kubernetes/master/CHANGELOG/CHANGELOG-{minor}.md"
_MD_LINK = re.compile(r'\[([^\]]+)\]\((?:[^)]+)\)')
_SIG_SUFFIX = re.compile(r'\s*\[SIG[^\]]*\]\s*$')
_NOTE_CAP = 20
_NOTE_MAX_CHARS = 700


def _clean_note(text: str) -> str:
    text = _MD_LINK.sub(r'\1', text)
    text = _SIG_SUFFIX.sub('', text)
    text = re.sub(r'`([^`]*)`', r'\1', text)
    return re.sub(r'\s+', ' ', text).strip()


def _bullets(block: str, cap: int = _NOTE_CAP) -> list[str]:
    """Split a changelog section into one string per top-level bullet.

    Upstream separates a bullet's lead-in from its body with a blank line
    ("- ACTION REQUIRED:" then the detail), so a blank line continues the current
    bullet instead of ending it; only the next bullet ends it.
    """
    out: list[str] = []
    current: list[str] = []
    for line in block.splitlines():
        if re.match(r'^\s*[-*]\s+', line):
            if current:
                out.append(" ".join(current))
            current = [re.sub(r'^\s*[-*]\s+', '', line).strip()]
        elif line.strip() and current:
            current.append(line.strip())
    if current:
        out.append(" ".join(current))
    cleaned = [_clean_note(b)[:_NOTE_MAX_CHARS] for b in out]
    return [c for c in cleaned if c and c != "ACTION REQUIRED:"][:cap]


def _section(body: str, heading_pattern: str) -> str:
    """Text under a heading, up to the next heading of the same or higher level."""
    m = re.search(heading_pattern, body, re.MULTILINE)
    if not m:
        return ""
    level = len(re.match(r'#+', m.group(0).lstrip()).group(0))
    rest = body[m.end():]
    nxt = re.search(r'^#{1,%d} ' % level, rest, re.MULTILINE)
    return rest[: nxt.start()] if nxt else rest


async def fetch_k8s_release_notes(minor: str) -> dict:
    """Urgent upgrade notes, deprecations, and API changes for a Kubernetes minor.

    Reads the .0 section of the upstream CHANGELOG, which is where the breaking
    items for a minor are recorded; later patch sections only carry fixes.
    """
    url = _CHANGELOG_URL.format(minor=minor)
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            r = await client.get(url)
        if r.status_code == 404:
            return {"available": False, "error": f"No upstream changelog for {minor} yet", "source_url": url}
        r.raise_for_status()
        text = r.text
    except Exception as exc:
        logger.warning("Kubernetes changelog fetch failed for %s: %s", minor, exc)
        return {"available": False, "error": str(exc)[:200], "source_url": url}

    body = _section(text, rf'^# v{re.escape(minor)}\.0$')
    if not body:
        return {"available": False, "error": f"Could not locate the v{minor}.0 section", "source_url": url}

    urgent = _bullets(_section(body, r'^## Urgent Upgrade Notes\s*$'))
    deprecations = _bullets(_section(body, r'^### Deprecation\s*$'))
    api_changes = _bullets(_section(body, r'^### API Change\s*$'))
    return {
        "available": bool(urgent or deprecations or api_changes),
        "version": minor,
        "urgent": urgent,
        "deprecations": deprecations,
        "api_changes": api_changes,
        "source_url": f"https://github.com/kubernetes/kubernetes/blob/master/CHANGELOG/CHANGELOG-{minor}.md",
        "error": None,
    }


# ─── Pluto scan ───────────────────────────────────────────────────────────────

async def fetch_repo_tarball(token: str, org: str, repo: str, ref: str) -> bytes:
    url = f"https://api.github.com/repos/{org}/{repo}/tarball/{ref}"
    async with httpx.AsyncClient(timeout=180, follow_redirects=True) as client:
        r = await client.get(url, headers=_gh_headers(token))
        r.raise_for_status()
        return r.content


def _extract_dirs(raw: bytes, dirs: list[str], dest: str) -> int:
    """Extract only the manifest dirs we scan. Returns the file count."""
    count = 0
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tf:
        for member in tf:
            if not member.isfile():
                continue
            # GitHub tarballs nest everything under a single <org>-<repo>-<sha> dir.
            rel = member.name.split("/", 1)[1] if "/" in member.name else member.name
            if not rel.endswith((".yaml", ".yml")):
                continue
            if not any(rel == d or rel.startswith(d + "/") for d in dirs):
                continue
            target = os.path.join(dest, rel)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            src = tf.extractfile(member)
            if src is None:
                continue
            with open(target, "wb") as out:
                out.write(src.read())
            count += 1
    return count


def _run_pluto(scan_dir: str, target_version: str) -> dict:
    """pluto detect-files over an extracted tree.

    pluto exits non-zero whenever it finds something (that is its contract), so
    the parse of stdout decides success, not the exit status.
    """
    proc = subprocess.run(
        [PLUTO_BIN, "detect-files", "-d", ".", "--target-versions",
         f"k8s=v{target_version}", "-o", "json"],
        cwd=scan_dir,
        capture_output=True,
        text=True,
        timeout=300,
    )
    if not proc.stdout.strip():
        raise RuntimeError(proc.stderr.strip()[:300] or "pluto produced no output")
    return json.loads(proc.stdout)


async def run_pluto_scan(token: str, org: str, repo: str, ref: str,
                         target_version: str, dirs: list[str]) -> dict:
    """Scan a cluster's GitOps manifests for APIs the target version removes."""
    if not os.path.exists(PLUTO_BIN):
        return {"available": False, "error": f"pluto binary not found at {PLUTO_BIN}"}

    try:
        raw = await fetch_repo_tarball(token, org, repo, ref)
    except Exception as exc:
        logger.warning("Tarball fetch failed for %s@%s: %s", repo, ref, exc)
        return {"available": False, "error": f"Could not download {repo}@{ref}: {str(exc)[:160]}"}

    tmp = tempfile.mkdtemp(prefix="pluto-")
    # Resolve before the scan: the temp root can itself be a symlink (/var vs
    # /private/var), and it is gone by the time the findings are mapped.
    scan_root = os.path.realpath(tmp)
    try:
        scanned = await asyncio.to_thread(_extract_dirs, raw, dirs, tmp)
        if not scanned:
            return {"available": False, "error": "No manifests matched the scanned paths"}
        data = await asyncio.to_thread(_run_pluto, tmp, target_version)
    except Exception as exc:
        logger.warning("pluto scan failed: %s", exc)
        return {"available": False, "error": str(exc)[:300]}
    finally:
        await asyncio.to_thread(_rmtree, tmp)

    items = []
    for it in (data.get("items") or []):
        api = it.get("api") or {}
        path = it.get("filePath") or ""
        resolved = os.path.realpath(path) if path else ""
        rel = os.path.relpath(resolved, scan_root) if resolved.startswith(scan_root) else path.lstrip("./")
        items.append({
            "name": it.get("name"),
            "file": rel,
            "api_version": api.get("version"),
            "kind": api.get("kind"),
            "deprecated_in": api.get("deprecated-in"),
            "removed_in": api.get("removed-in"),
            "replacement_api": api.get("replacement-api") or None,
            "component": api.get("component"),
            "deprecated": bool(it.get("deprecated")),
            "removed": bool(it.get("removed")),
        })
    items.sort(key=lambda i: (not i["removed"], i["file"] or "", i["kind"] or ""))
    return {
        "available": True,
        "target_version": target_version,
        "files_scanned": scanned,
        "scanned_paths": dirs,
        "removed_count": sum(1 for i in items if i["removed"]),
        "deprecated_count": sum(1 for i in items if i["deprecated"] and not i["removed"]),
        "items": items,
        "error": None,
    }


def _rmtree(path: str) -> None:
    shutil.rmtree(path, ignore_errors=True)


# ─── Card data ────────────────────────────────────────────────────────────────

async def get_eks_upgrade_params(token: str, org: str, repo: str, settings) -> dict:
    """Current declared version per cluster plus the targets AWS offers."""
    branch = maint_branch_name()
    branch_info = await get_branch_or_none(token, org, repo, branch)
    branch_exists = branch_info is not None
    ref = branch if branch_exists else "main"

    async def safe_get(path: str):
        try:
            return await get_file(token, org, repo, path, ref)
        except Exception as e:
            logger.warning("Could not read %s from ref %s: %s", path, ref, e)
            return None

    keys = list(EKS_CLUSTERS.keys())
    tfvars_files = await asyncio.gather(*[safe_get(EKS_CLUSTERS[k]["tfvars_path"]) for k in keys])

    # One version lookup per distinct (region, credential set).
    regions: dict[str, dict] = {}
    for k in keys:
        cfg = EKS_CLUSTERS[k]
        regions.setdefault(f"{cfg['region']}|{cfg['creds']}", {"region": cfg["region"], "key": k})
    region_results = await asyncio.gather(
        *[fetch_available_versions(v["region"], resolve_creds(v["key"], settings)) for v in regions.values()]
    )
    available_by_region = dict(zip(regions.keys(), region_results))

    # What each control plane is actually running, read per cluster.
    live_results = await asyncio.gather(*[
        fetch_live_version(k, EKS_CLUSTERS[k]["region"], resolve_describe_creds(k, settings))
        for k in keys
    ])
    live_by_key = dict(zip(keys, live_results))

    clusters = []
    for key, tfvars in zip(keys, tfvars_files):
        cfg = EKS_CLUSTERS[key]
        current = extract_eks_version(tfvars["content"]) if tfvars else None
        avail = available_by_region[f"{cfg['region']}|{cfg['creds']}"]
        live = live_by_key[key]["live_version"]
        # Measured from the running version where it is known: a staged tfvars
        # bump would otherwise make the remaining upgrades disappear.
        baseline = live or current
        upgrades = [
            v for v in avail["versions"]
            if baseline and version_tuple(v["version"]) > version_tuple(baseline)
        ]
        clusters.append({
            "key": key,
            "label": cfg["label"],
            "family": cfg["family"],
            "region": cfg["region"],
            "is_prod": bool(cfg.get("is_prod")),
            "tfvars_path": cfg["tfvars_path"],
            "nodeclass_paths": cfg["nodeclass_paths"],
            "current_version": current,
            "live_version": live_by_key[key]["live_version"],
            "live_error": live_by_key[key]["error"],
            # Terraform can be bumped well before anyone applies it, and that gap
            # is the thing worth seeing: prod declared 1.35 while running 1.34.
            "version_drift": bool(
                current and live_by_key[key]["live_version"]
                and current != live_by_key[key]["live_version"]),
            "available_versions": avail["versions"],
            "upgrade_targets": upgrades,
            "next_version": upgrades[-1]["version"] if upgrades else None,
            "latest_version": avail["versions"][0]["version"] if avail["versions"] else None,
            "error": avail["error"],
        })

    return {
        "branch": branch,
        "branch_exists": branch_exists,
        "branch_url": f"https://github.com/{org}/{repo}/tree/{branch}",
        "clusters": clusters,
    }


async def get_upgrade_preview(token: str, org: str, repo: str, settings,
                              cluster_key: str, target_version: str) -> dict:
    """Release notes, the pluto report, and the gold image for one target."""
    cfg = EKS_CLUSTERS[cluster_key]
    branch = maint_branch_name()
    branch_info = await get_branch_or_none(token, org, repo, branch)
    ref = branch if branch_info else "main"

    notes, pluto, ami = await asyncio.gather(
        fetch_k8s_release_notes(target_version),
        run_pluto_scan(token, org, repo, ref, target_version, cfg["manifest_dirs"]),
        fetch_gold_image_for_version(cfg["region"], cfg["ami_owner"], target_version,
                                     resolve_creds(cluster_key, settings)),
    )
    return {
        "cluster": cluster_key,
        "label": cfg["label"],
        "target_version": target_version,
        "ref_scanned": ref,
        "release_notes": notes,
        "pluto": pluto,
        "gold_image": ami,
    }


async def apply_eks_upgrade(token: str, org: str, repo: str, branch: str,
                            cluster_key: str, target_version: str,
                            new_ami: str = "", new_ami_name: str = "",
                            rebase_from_main: bool = False) -> dict:
    """Bump eks_version in tfvars and realign the gold image to the new minor."""
    cfg = EKS_CLUSTERS[cluster_key]
    committed: list[str] = []
    errors: list[str] = []

    await get_or_create_branch(token, org, repo, branch)

    # Always bring the branch up to date with main before writing. Committing on
    # a stale branch is what produced two different AMI steps on the same lines,
    # which git then merged into a conflict that reached main with its markers
    # still in the file. A conflict here is surfaced instead.
    merged = await merge_main_into_branch(token, org, repo, branch)
    if merged["updated"]:
        committed.append(f"(merged main into {branch})")

    async def commit_file(path: str, transform, message: str) -> None:
        try:
            f = await get_file(token, org, repo, path, branch)
            if conflict_markers(f["content"]):
                errors.append(
                    f"{path}: has merge-conflict markers committed into it. Resolve them "
                    f"on {branch} first; editing around them would rewrite an id inside a "
                    f"conflict block and hide it.")
                return
            new_content = transform(f["content"])
            if new_content == f["content"]:
                return
            await put_file(token, org, repo, path, new_content, f["sha"], message, branch)
            committed.append(path)
        except Exception as e:
            logger.error("Failed to commit %s: %s", path, e)
            errors.append(f"{path}: {e}")

    await commit_file(
        cfg["tfvars_path"],
        lambda c: patch_eks_version(c, target_version),
        f"chore({cluster_key}): upgrade EKS control plane to {target_version}",
    )

    # The gold image name carries the cluster version, so the nodes have to move
    # with the control plane or Karpenter keeps launching the old minor.
    if new_ami:
        await commit_file(
            cfg["tfvars_path"],
            lambda c: patch_ami_in_tfvars(c, new_ami, new_ami_name, cfg["region"]),
            f"chore({cluster_key}): realign node AMI to {new_ami} for EKS {target_version}",
        )
        # patch_ami_in_nodeclass rewrites every id: in the file, which is what we
        # want: controller and agent share the gold image, and the arm64 pools
        # select by alias so they are left alone.
        for nodeclass in cfg["nodeclass_paths"]:
            await commit_file(
                nodeclass,
                lambda c: patch_ami_in_nodeclass(c, new_ami, new_ami_name, cfg["region"]),
                f"chore({cluster_key}): realign Karpenter nodeclass AMI to {new_ami}",
            )

    return {"committed_files": committed, "errors": errors}
