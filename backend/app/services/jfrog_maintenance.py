import asyncio
import base64
import logging
import re
from datetime import datetime
from typing import Optional

import boto3
import httpx
import yaml

logger = logging.getLogger(__name__)

EKS_VERSION = "1.34"
AMI_OWNER = "743302140042"

JFROG_DEV_TFVARS_PATH = "terraform/envs/jfrog/envs/dev/terraform.tfvars"
KARPENTER_NODECLASS_PATH = "kubernetes/base/jfrog/cluster-ops/karpenter-node-class.yaml"

JFROG_PROD_TFVARS_PATH = "terraform/envs/jfrog/envs/prod/terraform.tfvars"
KARPENTER_NODECLASS_PROD_PATH = "kubernetes/envs/jfrog/prod/cluster-ops/karpenter-node-class.yaml"

# HelmRepository names that Flux resolves from our own Artifactory rather than from
# an upstream chart host. For these, upstream publishing a version means nothing:
# Flux can only install what has been mirrored, so latest must come from the
# Artifactory index or the card offers a bump that reconciles to
# "no chart with version matching X found" (snapshot-controller 5.3.0 and 5.4.0 both
# shipped that way and sat broken for three weeks).
ARTIFACTORY_HELM_SOURCE_REFS = {"cms-devops-helm-charts"}

# ─── Chart metadata ───────────────────────────────────────────────────────────

HELM_RELEASES = {
    "jfrog-artifactory": {
        "file": "kubernetes/base/jfrog/releases/jfrog-artifactory.yaml",
        "artifacthub_repo": "jfrog",
        "artifacthub_pkg": "artifactory-ha",
        "changelog_url": "https://github.com/jfrog/charts/blob/master/stable/artifactory-ha/CHANGELOG.md",
        "label": "JFrog Artifactory HA",
    },
    "jfrog-xray": {
        "file": "kubernetes/base/jfrog/releases/jfrog-xray.yaml",
        "artifacthub_repo": "jfrog",
        "artifacthub_pkg": "xray",
        "changelog_url": "https://github.com/jfrog/charts/blob/master/stable/xray/CHANGELOG.md",
        "label": "JFrog Xray",
    },
    "aws-alb-controller": {
        "file": "kubernetes/base/jfrog/releases/aws-alb-controller.yaml",
        "artifacthub_repo": "aws",
        "artifacthub_pkg": "aws-load-balancer-controller",
        "changelog_url": "https://github.com/kubernetes-sigs/aws-load-balancer-controller/releases",
        "label": "AWS Load Balancer Controller",
    },
    "datadog-agent": {
        "file": "kubernetes/base/jfrog/releases/datadog-agent.yaml",
        "artifacthub_repo": "datadog",
        "artifacthub_pkg": "datadog",
        "changelog_url": "https://github.com/DataDog/helm-charts/releases",
        "label": "Datadog Agent",
    },
    "ingress-nginx": {
        "file": "kubernetes/base/jfrog/releases/ingress-nginx.yaml",
        "artifacthub_repo": "ingress-nginx",
        "artifacthub_pkg": "ingress-nginx",
        "changelog_url": "https://github.com/kubernetes/ingress-nginx/releases",
        "label": "Ingress NGINX",
    },
}

# Snyk broker runs in JFrog PROD only. Its manifests were moved out of the shared
# base (kubernetes/base/jfrog/...) into the prod overlay (kubernetes/envs/jfrog/
# prod/...), so these are tracked by the JFrog PROD modal alone, pointing at the
# prod paths. (Previously in HELM_RELEASES/OCI_REPOS reading the now-dead base
# paths, which left the version blank in the dev modal.)
PROD_ONLY_HELM_RELEASES = {
    "snyk-broker-cr-agent": {
        "file": "kubernetes/envs/jfrog/prod/releases/snyk-broker-cr-agent.yaml",
        # This chart is not on ArtifactHub; its latest comes from GitHub releases
        # (tags like "snyk-broker-2.12.0"). github_latest overrides the ArtifactHub
        # lookup used by other charts.
        "github_latest": {"owner": "snyk", "repo": "snyk-broker-helm", "tag_prefix": "snyk-broker-"},
        "changelog_url": "https://github.com/snyk/snyk-broker-helm/releases",
        "label": "Snyk Broker CR Agent",
    },
}

# Charts in the top-level shared base (kubernetes/base/releases) — pulled by BOTH
# the JFrog and CBJ clusters. Because they belong to neither tool, they have their
# own "Base Helm Charts" card (get_base_charts_params / apply_base_charts_changes)
# rather than riding along in the JFrog dev modal. Same HelmRelease shape as
# HELM_RELEASES, so they flow through the identical read/compare/apply path.
SHARED_BASE_RELEASES = {
    "shared-aws-cloudwatch-metrics": {
        "file": "kubernetes/base/releases/aws-cloudwatch-metrics.yaml",
        "artifacthub_repo": "aws",
        "artifacthub_pkg": "aws-cloudwatch-metrics",
        "changelog_url": "https://github.com/aws/eks-charts/tree/master/stable/aws-cloudwatch-metrics",
        "label": "AWS CloudWatch Metrics (shared)",
    },
    "shared-aws-fluent-bit": {
        "file": "kubernetes/base/releases/aws-fluent-bit.yaml",
        "artifacthub_repo": "aws",
        "artifacthub_pkg": "aws-for-fluent-bit",
        "changelog_url": "https://github.com/aws/eks-charts/tree/master/stable/aws-for-fluent-bit",
        "label": "AWS for Fluent Bit (shared)",
    },
    "shared-kube-state-metrics": {
        "file": "kubernetes/base/releases/kube-state-metrics.yaml",
        "artifacthub_repo": "prometheus-community",
        "artifacthub_pkg": "kube-state-metrics",
        "changelog_url": "https://github.com/prometheus-community/helm-charts/releases",
        "label": "kube-state-metrics (shared)",
    },
    "shared-vmware-tanzu-velero": {
        "file": "kubernetes/base/releases/vmware-tanzu-velero.yaml",
        "artifacthub_repo": "vmware-tanzu",
        "artifacthub_pkg": "velero",
        "changelog_url": "https://github.com/vmware-tanzu/helm-charts/releases",
        "label": "Velero (shared)",
    },
    "shared-snapshot-controller": {
        "file": "kubernetes/base/releases/snapshot-controller.yaml",
        "artifacthub_repo": "piraeus-charts",
        "artifacthub_pkg": "snapshot-controller",
        "changelog_url": "https://github.com/piraeusdatastore/helm-charts/releases",
        "label": "Snapshot Controller (shared)",
    },
}

OCI_REPOS = {
    "karpenter": {
        "file": "kubernetes/base/jfrog/repositories/karpenter.yaml",
        "github_repo": "kubernetes-sigs/karpenter",
        "changelog_url": "https://github.com/kubernetes-sigs/karpenter/releases",
        "label": "Karpenter",
    },
    "karpenter-crd": {
        "file": "kubernetes/base/jfrog/repositories/karpenter-crd.yaml",
        "github_repo": "kubernetes-sigs/karpenter",
        "changelog_url": "https://github.com/kubernetes-sigs/karpenter/releases",
        "label": "Karpenter CRD",
    },
}

# Snyk Universal Broker OCI image — prod-only (see PROD_ONLY_HELM_RELEASES). Moved
# from kubernetes/base/jfrog/repositories/ to the prod overlay.
PROD_ONLY_OCI_REPOS = {
    "snyk-broker": {
        "file": "kubernetes/envs/jfrog/prod/repositories/snyk-broker.yaml",
        "dockerhub_repo": "snyk/snyk-universal-broker",
        "changelog_url": "https://github.com/snyk/broker/releases",
        "label": "Snyk Universal Broker",
    },
}

# Where to find release notes per chart key
# type "jfrog_changelog" → parse CHANGELOG.md from jfrog/charts
# type "github_release"  → fetch GitHub release by tag
RELEASE_SOURCES: dict[str, dict] = {
    "jfrog-artifactory": {
        "type": "jfrog_changelog",
        "gh_owner": "jfrog",
        "gh_repo": "charts",
        "changelog_path": "stable/artifactory-ha/CHANGELOG.md",
    },
    "jfrog-xray": {
        "type": "jfrog_changelog",
        "gh_owner": "jfrog",
        "gh_repo": "charts",
        "changelog_path": "stable/xray/CHANGELOG.md",
    },
    "aws-alb-controller": {
        "type": "github_release",
        "gh_owner": "kubernetes-sigs",
        "gh_repo": "aws-load-balancer-controller",
        "tag_template": "v{version}",
    },
    "datadog-agent": {
        "type": "github_release",
        "gh_owner": "DataDog",
        "gh_repo": "helm-charts",
        "tag_template": "datadog-{version}",
    },
    "ingress-nginx": {
        "type": "github_release",
        "gh_owner": "kubernetes",
        "gh_repo": "ingress-nginx",
        "tag_template": "helm-chart-{version}",
    },
    "snyk-broker-cr-agent": {
        "type": "github_release",
        "gh_owner": "snyk",
        "gh_repo": "snyk-broker-helm",
        "tag_template": "snyk-broker-{version}",
    },
    "karpenter": {
        "type": "github_release",
        "gh_owner": "kubernetes-sigs",
        "gh_repo": "karpenter",
        "tag_template": "v{version}",
        "upgrade_guide_url": "https://karpenter.sh/docs/upgrading/upgrade-guide/",
    },
    "karpenter-crd": {
        "type": "github_release",
        "gh_owner": "kubernetes-sigs",
        "gh_repo": "karpenter",
        "tag_template": "v{version}",
        "upgrade_guide_url": "https://karpenter.sh/docs/upgrading/upgrade-guide/",
    },
    "snyk-broker": {
        "type": "github_release",
        "gh_owner": "snyk",
        "gh_repo": "broker",
        "tag_template": "v{version}",
    },
    # Shared base/releases charts (JFrog-dev-owned) — GitHub release notes per chart tag.
    "shared-kube-state-metrics": {
        "type": "github_release",
        "gh_owner": "prometheus-community",
        "gh_repo": "helm-charts",
        "tag_template": "kube-state-metrics-{version}",
    },
    "shared-vmware-tanzu-velero": {
        "type": "github_release",
        "gh_owner": "vmware-tanzu",
        "gh_repo": "helm-charts",
        "tag_template": "velero-{version}",
    },
    "shared-snapshot-controller": {
        "type": "github_release",
        "gh_owner": "piraeusdatastore",
        "gh_repo": "helm-charts",
        "tag_template": "snapshot-controller-{version}",
    },
}


def maint_branch_name() -> str:
    months = ['jan','feb','mar','apr','may','jun','jul','aug','sep','oct','nov','dec']
    now = datetime.utcnow()
    return f"{months[now.month - 1]}{str(now.year)[2:]}-maint"


def _gh_headers(token: str | None = None) -> dict:
    h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


# ─── GitHub branch / file helpers ────────────────────────────────────────────

async def _branch_head_sha(client: httpx.AsyncClient, api_base: str, headers: dict, branch: str) -> str | None:
    """Return a branch's head SHA, or None if it doesn't exist. Uses the
    matching-refs endpoint because git/ref/heads/{ref} returns intermittent 503s
    for some refs on this repo; matching-refs is reliable. Filters to the exact ref."""
    resp = await client.get(f"{api_base}/git/matching-refs/heads/{branch}", headers=headers)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    want = f"refs/heads/{branch}"
    for r in resp.json():
        if r.get("ref") == want:
            return r["object"]["sha"]
    return None


async def get_branch_or_none(token: str, org: str, repo: str, branch: str) -> dict | None:
    """Read-only: return branch info if it exists, else None. Never creates the
    branch. Used by the *preview/params* endpoints so merely opening a modal does
    not cut the maintenance branch — creation is deferred to the apply/cut action."""
    api_base = f"https://api.github.com/repos/{org}/{repo}"
    headers = _gh_headers(token)
    async with httpx.AsyncClient(timeout=15) as client:
        sha = await _branch_head_sha(client, api_base, headers, branch)
        return {"branch": branch, "created": False, "sha": sha} if sha else None


async def get_or_create_branch(token: str, org: str, repo: str, branch: str) -> dict:
    api_base = f"https://api.github.com/repos/{org}/{repo}"
    headers = _gh_headers(token)
    async with httpx.AsyncClient(timeout=15) as client:
        sha = await _branch_head_sha(client, api_base, headers, branch)
        if sha:
            return {"branch": branch, "created": False, "sha": sha}

        main_sha = await _branch_head_sha(client, api_base, headers, "main")
        if not main_sha:
            raise RuntimeError("Could not resolve main branch head SHA")

        create = await client.post(
            f"{api_base}/git/refs",
            headers=headers,
            json={"ref": f"refs/heads/{branch}", "sha": main_sha},
        )
        create.raise_for_status()
        return {"branch": branch, "created": True, "sha": main_sha}


async def merge_main_into_branch(token: str, org: str, repo: str, branch: str) -> dict:
    """Bring the maintenance branch up to date with main by merging main into it
    (GitHub has no true-rebase API). Non-destructive: keeps any commits already on
    the branch. Returns {"updated": bool, "status": <http>, "sha": <new head|None>}.
    Raises on a merge conflict so the caller can surface it instead of committing
    on top of a stale branch."""
    api_base = f"https://api.github.com/repos/{org}/{repo}"
    headers = _gh_headers(token)
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{api_base}/merges",
            headers=headers,
            json={"base": branch, "head": "main",
                  "commit_message": f"chore: merge main into {branch} before maintenance"},
        )
        if resp.status_code == 201:
            return {"updated": True, "status": 201, "sha": resp.json().get("sha")}
        if resp.status_code == 204:
            # already contains everything from main — nothing to do
            return {"updated": False, "status": 204, "sha": None}
        if resp.status_code == 409:
            raise RuntimeError(
                f"Cannot rebase {branch} from main: merge conflict. Resolve it in GitHub, "
                f"then re-run without the rebase option. ({resp.text[:300]})"
            )
        resp.raise_for_status()
        return {"updated": False, "status": resp.status_code, "sha": None}


async def get_file(token: str, org: str, repo: str, path: str, ref: str) -> dict:
    url = f"https://api.github.com/repos/{org}/{repo}/contents/{path}"
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(url, headers=_gh_headers(token), params={"ref": ref})
        resp.raise_for_status()
        data = resp.json()
        return {
            "content": base64.b64decode(data["content"]).decode("utf-8"),
            "sha": data["sha"],
        }


async def put_file(token: str, org: str, repo: str, path: str, content: str, sha: str, message: str, branch: str) -> None:
    url = f"https://api.github.com/repos/{org}/{repo}/contents/{path}"
    encoded = base64.b64encode(content.encode("utf-8")).decode("utf-8")
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.put(
            url, headers=_gh_headers(token),
            json={"message": message, "content": encoded, "sha": sha, "branch": branch},
        )
        resp.raise_for_status()


# ─── File content extractors / patchers ───────────────────────────────────────

def extract_eks_version_tfvars(content: str) -> Optional[str]:
    """The cluster version declared in tfvars, which the gold image name follows."""
    m = re.search(r'eks_version\s*=\s*"([0-9]+\.[0-9]+)"', content)
    return m.group(1) if m else None


def extract_ami_from_tfvars(content: str) -> Optional[str]:
    m = re.search(r'eks_ami\s*=\s*"(ami-[a-z0-9]+)"', content)
    return m.group(1) if m else None


# All JFrog EKS/Karpenter nodes run in commercial us-east-1.
JFROG_AMI_REGION = "us-east-1"


def ami_comment(ami_name: str, region: str = "") -> str:
    """Identifying comment for an AMI line, e.g. '  # us-gov-west-1 : <ami-name>'.

    The region is part of the identifier because an AMI id is only meaningful in
    one region: the same gold image has a different id in us-east-1 and in
    us-gov-west-1. Labelling a GovCloud id as us-east-1 sent someone looking for
    an image that does not exist there.
    """
    label = " : ".join(p for p in ((region or JFROG_AMI_REGION).strip(), ami_name.strip()) if p)
    return f"  # {label}" if ami_name.strip() else ""


# A trailing comment that names a gold image, which a new id makes wrong.
_STALE_AMI_COMMENT_RE = re.compile(r'\s*#[^\n]*al2023-eks-[^\n]*')


def _strip_stale_ami_comment(line_tail: str) -> str:
    """Drop a comment that identifies the image being replaced.

    Keeping it was worse than having none: the id moved to the October 1.35
    image while the comment still read 1.34, so the file disagreed with itself
    and the stale half looked authoritative.
    """
    return _STALE_AMI_COMMENT_RE.sub("", line_tail)


def patch_ami_in_tfvars(content: str, new_ami: str, ami_name: str = "", region: str = "") -> str:
    comment = ami_comment(ami_name, region)
    if comment:
        # Replace the id and its trailing comment so the identifier stays in sync.
        return re.sub(r'(eks_ami\s*=\s*)"ami-[a-z0-9]+"[^\n]*', f'\\1"{new_ami}"{comment}', content)

    # No name to write: swap the id and drop any comment that named the old
    # image, keeping an unrelated one.
    def _sub(m: re.Match) -> str:
        return f'{m.group(1)}"{new_ami}"{_strip_stale_ami_comment(m.group(2))}'

    return re.sub(r'(eks_ami\s*=\s*)"ami-[a-z0-9]+"([^\n]*)', _sub, content)


def extract_ami_from_nodeclass(content: str) -> Optional[str]:
    m = re.search(r'id:\s*"?(ami-[a-z0-9]+)"?', content)
    return m.group(1) if m else None


def patch_ami_in_nodeclass(content: str, new_ami: str, ami_name: str = "", region: str = "") -> str:
    comment = ami_comment(ami_name, region)
    if comment:
        return re.sub(r'(id:\s*)"?ami-[a-z0-9]+"?[^\n]*', f'\\1"{new_ami}"{comment}', content)

    def _sub(m: re.Match) -> str:
        return f'{m.group(1)}"{new_ami}"{_strip_stale_ami_comment(m.group(2))}'

    return re.sub(r'(id:\s*)"?ami-[a-z0-9]+"?([^\n]*)', _sub, content)


CONFLICT_MARKER_RE = re.compile(r"^(<{7}|={7}|>{7})(?: |$)", re.MULTILINE)


def conflict_markers(content: str) -> bool:
    """Whether a file still carries merge-conflict markers.

    Six files once reached main with markers committed into them, and a regex
    patcher is happy to rewrite an AMI id inside a conflict block and commit it
    back, which keeps the damage and makes it look deliberate. Every write path
    checks this first and refuses rather than editing around it.
    """
    return bool(CONFLICT_MARKER_RE.search(content or ""))


def extract_helm_version(content: str) -> Optional[str]:
    m = re.search(r'version:\s*["\']?(\d+\.\d+\.\d+)["\']?', content)
    return m.group(1) if m else None


def extract_helm_version_raw(content: str) -> Optional[str]:
    """Extract the chart version verbatim, including floating constraints like
    107.x / 4.* / ~1.2 (which extract_helm_version's strict semver regex skips)."""
    m = re.search(r'\bversion:\s*["\']?([0-9][\w.\-*~^>=<]*)["\']?', content)
    return m.group(1) if m else None


def extract_helm_source_ref(content: str) -> Optional[str]:
    m = re.search(r'sourceRef:\s*\n(?:\s+\w+:.*\n)*?\s+name:\s*["\']?([\w.-]+)', content)
    return m.group(1) if m else None


def extract_helm_chart_name(content: str) -> Optional[str]:
    m = re.search(r'^\s+chart:\s*["\']?([\w.-]+)["\']?\s*$', content, re.M)
    return m.group(1) if m else None


def patch_helm_version(content: str, new_version: str) -> str:
    return re.sub(r'(version:\s*)["\']?\d+\.\d+\.\d+["\']?', f'\\1"{new_version}"', content, count=1)


def extract_oci_tag(content: str) -> Optional[str]:
    m = re.search(r'tag:\s*["\']?([\d.]+)["\']?', content)
    return m.group(1) if m else None


def patch_oci_tag(content: str, new_tag: str) -> str:
    return re.sub(r'(tag:\s*)["\']?[\d.]+["\']?', f'\\1"{new_tag}"', content, count=1)


def is_minor_or_major_bump(current: str, latest: str) -> bool:
    try:
        def parse(v: str):
            return tuple(int(x) for x in v.lstrip("v").split(".")[:3])
        cur, lat = parse(current), parse(latest)
        return lat[0] != cur[0] or lat[1] != cur[1]
    except Exception:
        return False


def artifactory_app_version(chart_version: str) -> str:
    try:
        parts = chart_version.split(".")
        if len(parts) == 3 and len(parts[0]) == 3 and parts[0].startswith("10"):
            return f"7.{parts[1]}.{parts[2]}"
    except Exception:
        pass
    return ""


# ─── AMI release notes ────────────────────────────────────────────────────────

AMI_RELEASE_NOTES_URL = "https://cloud.cms.gov/gold-image-amazon-linux-2023-release-notes/"


def _extract_date_from_ami_name(ami_name: str) -> str | None:
    """Extract YYYY-MM-DD from e.g. al2023-eks-1.34-gi-2026-06-10"""
    m = re.search(r'gi-(\d{4}-\d{2}-\d{2})', ami_name)
    return m.group(1) if m else None


def _parse_ami_release_notes_html(html: str, date_str: str) -> list[str] | None:
    """
    Parse CMS gold image release notes page and extract bullet points for the given date.
    Handles various date formats the page may use.
    """
    try:
        date_obj = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return None

    day_no_pad = str(date_obj.day)
    month_full = date_obj.strftime("%B")
    month_abbr = date_obj.strftime("%b")
    year = date_obj.strftime("%Y")

    date_variants = {
        date_str,
        f"{month_full} {day_no_pad}, {year}",
        f"{month_abbr} {day_no_pad}, {year}",
        date_obj.strftime("%m/%d/%Y"),
        f"{date_obj.month}/{date_obj.day}/{year}",
    }

    # Strip script/style blocks to reduce noise
    html = re.sub(r'<(script|style)[^>]*>.*?</\1>', '', html, flags=re.DOTALL | re.IGNORECASE)

    # Find all h2–h5 headings and their positions
    heading_re = re.compile(r'<(h[2-5])[^>]*>(.*?)</\1>', re.IGNORECASE | re.DOTALL)
    headings = list(heading_re.finditer(html))

    target_idx: int | None = None
    target_level: str | None = None

    for i, m in enumerate(headings):
        heading_text = re.sub(r'<[^>]+>', '', m.group(2)).strip()
        for variant in date_variants:
            if variant.lower() in heading_text.lower():
                target_idx = i
                target_level = m.group(1)
                break
        if target_idx is not None:
            break

    if target_idx is None:
        return None

    # Slice section: from end of matched heading to start of next same-or-higher heading
    start = headings[target_idx].end()
    end = len(html)
    for j in range(target_idx + 1, len(headings)):
        if headings[j].group(1) <= target_level:  # "h2" <= "h3" lexicographically = higher
            end = headings[j].start()
            break

    section_html = html[start:end]

    # Prefer list items; fall back to paragraphs
    items: list[str] = []
    for m in re.finditer(r'<li[^>]*>(.*?)</li>', section_html, re.IGNORECASE | re.DOTALL):
        text = re.sub(r'<[^>]+>', '', m.group(1)).strip()
        text = re.sub(r'\s+', ' ', text)
        if text:
            items.append(text)

    if not items:
        for m in re.finditer(r'<p[^>]*>(.*?)</p>', section_html, re.IGNORECASE | re.DOTALL):
            text = re.sub(r'<[^>]+>', '', m.group(1)).strip()
            text = re.sub(r'\s+', ' ', text)
            if text and len(text) > 5:
                items.append(text)

    return items or None


async def fetch_ami_release_notes(ami_name: str) -> dict:
    """Fetch and parse CMS gold image release notes for the given AMI name."""
    date_str = _extract_date_from_ami_name(ami_name)
    if not date_str:
        return {"available": False, "error": "Could not extract date from AMI name", "source_url": AMI_RELEASE_NOTES_URL}

    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(AMI_RELEASE_NOTES_URL, headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
            })
            resp.raise_for_status()

        notes = _parse_ami_release_notes_html(resp.text, date_str)
        if notes:
            return {"available": True, "date": date_str, "notes": notes, "source_url": AMI_RELEASE_NOTES_URL}
        return {"available": False, "error": f"No release notes found for {date_str}", "source_url": AMI_RELEASE_NOTES_URL}

    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 403:
            # cloud.cms.gov requires Zscaler; EKS pods can't reach it — degrade silently
            logger.warning("AMI release notes: 403 from %s (requires Zscaler)", AMI_RELEASE_NOTES_URL)
            return {"available": False, "source_url": AMI_RELEASE_NOTES_URL}
        logger.warning("AMI release notes fetch failed: %s", exc)
        return {"available": False, "error": str(exc), "source_url": AMI_RELEASE_NOTES_URL}
    except Exception as exc:
        logger.warning("AMI release notes fetch failed: %s", exc)
        return {"available": False, "error": str(exc), "source_url": AMI_RELEASE_NOTES_URL}


# ─── Version fetchers ─────────────────────────────────────────────────────────

async def fetch_live_eks_version(cluster: str) -> str | None:
    """The version the control plane is actually running, or None if unreadable.

    Delegates rather than calling describe_cluster here: reading a cluster has to
    happen in the account that owns it, and eks_upgrade already knows which role
    to assume for each. A direct Pod Identity call only ever reaches jfrog-dev,
    which is how prod silently came back as unreadable. Imported inside the
    function because eks_upgrade imports this module.
    """
    from app.config import get_settings
    from app.services.eks_upgrade import running_version

    try:
        return await running_version(cluster, get_settings(), None)
    except Exception as exc:  # noqa: BLE001 — the modal still works without it
        logger.warning("Could not read the live version of %s: %s", cluster, exc)
        return None


async def ami_eks_minor(ami_id: str | None) -> str | None:
    """The Kubernetes minor a gold image is built for, from its name.

    ec2:DescribeImages is already granted in-cluster, unlike eks:DescribeCluster,
    so this is how the node side's version is established without new IAM.
    """
    if not ami_id:
        return None
    from app.config import get_settings

    def _describe() -> str | None:
        ec2 = boto3.client("ec2", region_name=get_settings().AWS_REGION)
        images = ec2.describe_images(ImageIds=[ami_id]).get("Images") or []
        if not images:
            return None
        m = re.search(r"al2023-eks-([0-9]+\.[0-9]+)-gi-", images[0].get("Name") or "")
        return m.group(1) if m else None

    try:
        return await asyncio.to_thread(_describe)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not read the version of %s: %s", ami_id, exc)
        return None


def _minor(v: str | None) -> tuple:
    try:
        return tuple(int(x) for x in (v or "").split(".")[:2])
    except Exception:  # noqa: BLE001
        return (0, 0)


async def fetch_latest_ami(eks_version: str | None = None) -> dict:
    """
    Describe the latest gold-image AMI via boto3.
    In-cluster: credentials come automatically from the EKS Pod Identity agent.
    Locally: uses whatever AWS credentials are in the environment (direnv / aws-setup).
    """
    from app.config import get_settings

    def _describe() -> dict:
        ec2 = boto3.client("ec2", region_name=get_settings().AWS_REGION)
        resp = ec2.describe_images(
            Owners=[AMI_OWNER],
            Filters=[
                {"Name": "name", "Values": [f"al2023-eks-{eks_version or EKS_VERSION}-gi-*"]},
                {"Name": "state", "Values": ["available"]},
            ],
        )
        images = sorted(resp["Images"], key=lambda x: x["CreationDate"])
        if not images:
            raise RuntimeError("No AMIs found")
        latest = images[-1]
        return {
            "ami_id": latest["ImageId"],
            "ami_name": latest["Name"],
            "created_at": latest["CreationDate"],
        }

    try:
        return await asyncio.to_thread(_describe)
    except Exception as e:
        raise RuntimeError(f"AMI fetch failed: {e}") from e


async def fetch_artifacthub_version(repo: str, package: str) -> str:
    url = f"https://artifacthub.io/api/v1/packages/helm/{repo}/{package}"
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(url, headers={"Accept": "application/json"})
        resp.raise_for_status()
        return resp.json()["version"]


async def fetch_karpenter_latest() -> str:
    # Karpenter's Helm chart (oci://public.ecr.aws/karpenter/karpenter) is released from
    # kubernetes-sigs/karpenter. Do NOT use GitHub's /releases/latest — it is ordered by
    # publish date, so a backport patch to an old minor (e.g. v1.2.8 shipped after v1.14.0)
    # gets reported as "latest". Pick the true semver maximum across stable releases instead.
    url = "https://api.github.com/repos/kubernetes-sigs/karpenter/releases"
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(url, headers=_gh_headers(), params={"per_page": 100})
        resp.raise_for_status()
        versions = [
            r["tag_name"].lstrip("v")
            for r in resp.json()
            if not r.get("prerelease") and not r.get("draft") and r.get("tag_name")
        ]
    if not versions:
        raise RuntimeError("No stable Karpenter releases found")
    return max(versions, key=_ver_tuple)


async def fetch_github_chart_latest(owner: str, repo: str, tag_prefix: str = "") -> str:
    """Latest stable chart version from a repo's GitHub releases. Strips `tag_prefix`
    (e.g. 'snyk-broker-') off the tag and returns the true semver maximum — not
    GitHub's publish-date /releases/latest, which mis-reports a backport patch as
    newest (same reasoning as fetch_karpenter_latest)."""
    url = f"https://api.github.com/repos/{owner}/{repo}/releases"
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(url, headers=_gh_headers(), params={"per_page": 100})
        resp.raise_for_status()
        versions = []
        for r in resp.json():
            if r.get("prerelease") or r.get("draft"):
                continue
            tag = r.get("tag_name") or ""
            if tag_prefix and not tag.startswith(tag_prefix):
                continue
            v = tag[len(tag_prefix):] if tag_prefix else tag.lstrip("v")
            if re.match(r"^\d+\.\d+\.\d+", v):
                versions.append(v)
    if not versions:
        raise RuntimeError(f"No stable releases for {owner}/{repo}")
    return max(versions, key=_ver_tuple)


async def fetch_artifactory_chart_latest(source_ref: str, chart: str) -> str:
    """Latest version of `chart` that our Artifactory actually serves, read from the
    repo's Helm index. This is the only version Flux can resolve, so it is what the
    card must compare against for charts in ARTIFACTORY_HELM_SOURCE_REFS. The index
    is world-readable, so no credentials are needed."""
    from app.config import get_settings

    base = get_settings().ARTIFACTORY_PROD_URL.rstrip("/")
    url = f"{base}/artifactory/{source_ref}/index.yaml"
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(url, headers={"Accept": "application/x-yaml"})
        resp.raise_for_status()
        index = yaml.safe_load(resp.text) or {}
    entries = (index.get("entries") or {}).get(chart) or []
    versions = [
        str(e["version"]).strip() for e in entries
        if e.get("version") and re.match(r"^\d+\.\d+\.\d+$", str(e["version"]).strip())
    ]
    if not versions:
        raise RuntimeError(f"No '{chart}' chart versions published in {source_ref}")
    return max(versions, key=_ver_tuple)


async def fetch_dockerhub_latest(repo: str) -> str:
    url = f"https://hub.docker.com/v2/repositories/{repo}/tags"
    semver_re = re.compile(r'^\d+\.\d+\.\d+$')
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(url, params={"ordering": "last_updated", "page_size": 25})
        resp.raise_for_status()
        for tag in resp.json().get("results", []):
            name = tag.get("name", "")
            if semver_re.match(name):
                return name
    raise RuntimeError(f"No semver tag found for {repo}")


# ─── Release notes fetching and parsing ──────────────────────────────────────

def _ver_tuple(v: str) -> tuple:
    try:
        return tuple(int(x) for x in v.lstrip("v").split(".")[:3])
    except Exception:
        return (0, 0, 0)


def _parse_jfrog_changelog(content: str, current: str, target: str) -> list[dict]:
    """
    Extract CHANGELOG.md entries strictly between current (exclusive) and target (inclusive).
    Returns list of {version, date, notes, has_important} sorted newest-first.
    """
    section_re = re.compile(r'^## \[(\d+\.\d+\.\d+)\](?:\s*-\s*(.*))?$', re.MULTILINE)
    cur_t = _ver_tuple(current)
    tgt_t = _ver_tuple(target)

    matches = list(section_re.finditer(content))
    results = []

    for i, m in enumerate(matches):
        version = m.group(1)
        date = (m.group(2) or "").strip()
        ver_t = _ver_tuple(version)

        if not (cur_t < ver_t <= tgt_t):
            continue

        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        body = content[start:end].strip()

        notes = []
        for line in body.splitlines():
            line = line.strip()
            if line.startswith(("* ", "- ", "+ ")):
                notes.append(line[2:].strip())

        has_important = any(
            kw in n.lower()
            for n in notes
            for kw in ("important", "breaking", "removed", "deprecated", "migration", "rename")
        )

        results.append({
            "version": version,
            "date": date,
            "notes": notes,
            "has_important": has_important,
        })

    results.sort(key=lambda s: _ver_tuple(s["version"]), reverse=True)
    return results


_SKIP_SECTIONS = frozenset({
    "documentation", "docs", "continuous integration", "ci", "chores",
    "chore", "tests", "test", "commits", "dependencies", "deps",
})
_IMPACT_KEYWORDS = frozenset({"breaking", "incompatible", "removed", "migration", "deprecated", "rename"})
_FEATURE_SECTIONS = frozenset({"features", "new features", "enhancements", "changes", "changed", "what's changed", "bug fixes", "fixes"})


def _parse_github_release_body(body: str) -> dict:
    """
    Parse a GitHub release markdown body.
    Returns {sections: [{heading, items, is_breaking}], has_breaking: bool}.
    Strips noisy PR-link suffixes from bullet text.
    """
    if not body:
        return {"sections": [], "has_breaking": False}

    pr_link_re = re.compile(r'\s+\[#\d+\]\([^)]*\)|\s+\(#\d+\)|\s+\([^)]*@[^)]*\)$')

    sections: list[dict] = []
    has_breaking = False
    current_heading: str | None = None
    current_items: list[str] = []

    def _flush():
        nonlocal has_breaking
        if not current_heading or not current_items:
            return
        h_lower = current_heading.lower()
        is_breaking = any(kw in h_lower for kw in _IMPACT_KEYWORDS)
        is_feature = any(kw in h_lower for kw in _FEATURE_SECTIONS)
        is_skip = any(kw in h_lower for kw in _SKIP_SECTIONS)
        if (is_breaking or is_feature) and not is_skip:
            sections.append({
                "heading": current_heading,
                "items": current_items[:8],
                "is_breaking": is_breaking,
            })
            if is_breaking:
                has_breaking = True

    for line in body.splitlines():
        s = line.strip()
        if s.startswith("## "):
            _flush()
            current_heading = s[3:].strip()
            current_items = []
        elif s.startswith(("- ", "* ", "+ ")):
            item = pr_link_re.sub("", s[2:].strip()).strip()
            if item:
                current_items.append(item)

    _flush()
    return {"sections": sections, "has_breaking": has_breaking}


async def fetch_release_notes(key: str, current_version: str, target_version: str) -> dict:
    """
    Fetch and parse release notes for upgrading a chart from current to target version.
    Returns a dict that the frontend can render.
    """
    source = RELEASE_SOURCES.get(key)
    if not source:
        return {"available": False}

    try:
        if source["type"] == "jfrog_changelog":
            url = (
                f"https://api.github.com/repos/{source['gh_owner']}/{source['gh_repo']}"
                f"/contents/{source['changelog_path']}"
            )
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(url, headers=_gh_headers())
                resp.raise_for_status()
                raw = base64.b64decode(resp.json()["content"]).decode("utf-8")
            entries = _parse_jfrog_changelog(raw, current_version, target_version)
            has_important = any(e["has_important"] for e in entries)
            return {
                "available": True,
                "type": "changelog",
                "entries": entries,
                "has_breaking": has_important,
                "upgrade_guide_url": source.get("upgrade_guide_url"),
                "source_url": (
                    f"https://github.com/{source['gh_owner']}/{source['gh_repo']}"
                    f"/blob/master/{source['changelog_path']}"
                ),
            }

        elif source["type"] == "github_release":
            tag = source["tag_template"].format(version=target_version)
            release_url = (
                f"https://github.com/{source['gh_owner']}/{source['gh_repo']}/releases/tag/{tag}"
            )
            url = (
                f"https://api.github.com/repos/{source['gh_owner']}/{source['gh_repo']}"
                f"/releases/tags/{tag}"
            )
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(url, headers=_gh_headers())
                if resp.status_code == 404:
                    return {
                        "available": False,
                        "error": f"No GitHub release found for tag {tag}",
                        "source_url": release_url,
                        "upgrade_guide_url": source.get("upgrade_guide_url"),
                    }
                resp.raise_for_status()
                body = resp.json().get("body") or ""

            parsed = _parse_github_release_body(body)
            return {
                "available": True,
                "type": "github_release",
                "sections": parsed["sections"],
                "has_breaking": parsed["has_breaking"],
                "upgrade_guide_url": source.get("upgrade_guide_url"),
                "source_url": release_url,
            }

    except Exception as exc:
        logger.warning("Release notes fetch failed for %s: %s", key, exc)
        return {"available": False, "error": str(exc)}

    return {"available": False}


# ─── Shared JFrog env helpers ─────────────────────────────────────────────────

def _is_floating_version(v: str | None) -> bool:
    """True if a chart version is a floating constraint (e.g. 107.x, ~1.2, ^3, 4.*,
    >=1.0). Dev overlays float their charts so Flux tracks the latest, so these
    have no manual bump to apply."""
    if not v:
        return False
    v = v.strip().strip('"').strip("'")
    return bool(re.search(r"(?:^|\.)[xX*]$|[~^]|>=|<=|\*|\.x\b", v))


async def fetch_helm_latest(meta: dict, file_data: dict | None = None) -> str | None:
    """Latest chart version for a HELM_RELEASES-shaped entry. A chart whose manifest
    points at an Artifactory-backed HelmRepository is resolved from that repo's index,
    because that is the only version Flux can install. Entries that pin github_latest
    read GitHub releases (charts ArtifactHub does not index or indexes stale);
    everything else reads ArtifactHub. Returns None on failure so one dead upstream
    cannot fail the whole preview."""
    content = (file_data or {}).get("content")
    source_ref = extract_helm_source_ref(content) if content else None
    gl = meta.get("github_latest")
    try:
        if source_ref in ARTIFACTORY_HELM_SOURCE_REFS:
            chart = extract_helm_chart_name(content) or meta.get("artifacthub_pkg")
            return await fetch_artifactory_chart_latest(source_ref, chart)
        if gl:
            return await fetch_github_chart_latest(gl["owner"], gl["repo"], gl.get("tag_prefix", ""))
        return await fetch_artifacthub_version(meta["artifacthub_repo"], meta["artifacthub_pkg"])
    except Exception as e:
        logger.warning("Chart latest lookup failed for %s: %s", meta.get("label"), e)
        return None


async def get_jfrog_env_params(
    token: str,
    org: str,
    repo: str,
    tfvars_path: str,
    nodeclass_path: str | None,
    eks_cluster: str | None = None,
    helm_overlay_dir: str | None = None,
    extra_helm_releases: dict | None = None,
    extra_oci_repos: dict | None = None,
) -> dict:
    """
    Read the maintenance branch (WITHOUT creating it), then fetch current versions
    from the branch — or from main if the branch has not been cut yet — and latest
    versions from upstream registries.  Returns a complete diff the engineer can
    review before applying.  Works for both dev and prod by accepting env-specific
    file paths.  Passing nodeclass_path=None skips the Karpenter nodeclass entirely,
    for a cluster that genuinely has none of its own.
    """
    branch = maint_branch_name()

    # Base HELM_RELEASES plus any env-scoped extras (e.g. JFrog dev owns the shared
    # base/releases charts; JFrog prod owns the snyk-broker chart). Merged locally
    # so other envs never see them.
    helm_releases = {**HELM_RELEASES, **(extra_helm_releases or {})}
    oci_repos = {**OCI_REPOS, **(extra_oci_repos or {})}

    # ── 1. Look up the maintenance branch (read-only; do NOT create on preview) ─
    branch_info = await get_branch_or_none(token, org, repo, branch)
    branch_exists = branch_info is not None
    # Preview against the branch if it exists, otherwise against main so the diff
    # still renders before the branch is cut.
    ref = branch if branch_exists else "main"
    branch_url = f"https://github.com/{org}/{repo}/tree/{branch}"

    # ── 2. Read current file contents from the ref ─────────────────────────────
    async def safe_get(path: str | None):
        if not path:
            return None
        try:
            return await get_file(token, org, repo, path, ref)
        except Exception as e:
            logger.warning("Could not read %s from ref %s: %s", path, ref, e)
            return None

    tfvars_file, nodeclass_file = await asyncio.gather(
        safe_get(tfvars_path),
        safe_get(nodeclass_path),
    )

    helm_files = {}
    # When an env floats its chart versions in an overlay (dev), read the CURRENT
    # version from that overlay so we don't compare the base (prod) pin.
    helm_current_overrides: dict[str, str] = {}
    for key, meta in helm_releases.items():
        helm_files[key] = await safe_get(meta["file"])
        if helm_overlay_dir:
            basename = meta["file"].rsplit("/", 1)[-1]
            overlay = await safe_get(f"{helm_overlay_dir}/{basename}")
            if overlay:
                ov = extract_helm_version_raw(overlay["content"])
                if ov:
                    helm_current_overrides[key] = ov

    oci_files = {}
    for key, meta in oci_repos.items():
        oci_files[key] = await safe_get(meta["file"])

    # ── 3. Fetch latest versions from upstream ────────────────────────────────
    karpenter_latest = None
    karpenter_error = None
    try:
        karpenter_latest = await fetch_karpenter_latest()
    except Exception as e:
        karpenter_error = str(e)

    declared_eks = extract_eks_version_tfvars(tfvars_file["content"]) if tfvars_file else None
    # The gold image offered has to match what the cluster is running, not what
    # tfvars declares. Selecting by the declared version is how a 1.35 image came
    # to be offered to a 1.34 control plane.
    live_eks = await fetch_live_eks_version(eks_cluster) if eks_cluster else None
    ami_for = live_eks or declared_eks

    ami_info = None
    ami_error = None
    try:
        ami_info = await fetch_latest_ami(ami_for)
    except Exception as e:
        ami_error = str(e)

    # The gold image is chosen by the version tfvars declares, so when tfvars has
    # been bumped ahead of the apply the offered AMI is for a newer Kubernetes
    # than the cluster runs. Installing it would put the kubelet ahead of the API
    # server, which is not a supported direction. JFrog prod sat exactly here:
    # tfvars said 1.35, the control plane was on 1.34.
    # Two separate questions. Is this a minor jump for the nodes, and if so can we
    # confirm the control plane is already there?

    helm_latest = {}
    latest_results = await asyncio.gather(
        *[fetch_helm_latest(meta, helm_files.get(key)) for key, meta in helm_releases.items()]
    )
    for key, latest in zip(helm_releases.keys(), latest_results):
        helm_latest[key] = latest

    snyk_broker_latest = None
    try:
        snyk_broker_latest = await fetch_dockerhub_latest("snyk/snyk-universal-broker")
    except Exception as e:
        logger.warning("Docker Hub snyk-universal-broker failed: %s", e)

    # ── 4. Build response ─────────────────────────────────────────────────────
    current_ami_tfvars = extract_ami_from_tfvars(tfvars_file["content"]) if tfvars_file else None
    current_ami_nodeclass = extract_ami_from_nodeclass(nodeclass_file["content"]) if nodeclass_file else None

    # Which minor the nodes are on today, and whether the image on offer is for a
    # newer one than the cluster runs. With the running version known the latter
    # cannot happen, since ami_for is that version; the check remains for when
    # the read fails and the declared version is used instead.
    node_eks = await ami_eks_minor(current_ami_nodeclass or current_ami_tfvars)
    ami_ahead = bool(live_eks and ami_for and _minor(ami_for) > _minor(live_eks))
    new_ami = ami_info["ami_id"] if ami_info else None

    # Fetch AMI release notes (best-effort)
    ami_release_notes: dict = {"available": False}
    if ami_info and ami_info.get("ami_name"):
        try:
            ami_release_notes = await fetch_ami_release_notes(ami_info["ami_name"])
        except Exception as e:
            logger.warning("AMI release notes fetch failed: %s", e)

    ami_section = {
        "current_ami": current_ami_tfvars,
        "current_ami_nodeclass": current_ami_nodeclass,
        "latest_ami": new_ami,
        "latest_ami_name": ami_info["ami_name"] if ami_info else None,
        "has_update": bool(new_ami and current_ami_tfvars and new_ami != current_ami_tfvars),
        "has_update_nodeclass": bool(
            new_ami and current_ami_nodeclass and new_ami != current_ami_nodeclass),
        "declared_eks_version": declared_eks,
        "live_eks_version": live_eks,
        "node_eks_version": node_eks,
        "ami_selected_for_eks": ami_for,
        "ami_ahead_of_cluster": ami_ahead,
        "error": ami_error,
        "eks_version": declared_eks or EKS_VERSION,
        "release_notes": ami_release_notes,
    }

    # Build preliminary rows (need current/latest to fetch release notes)
    helm_rows_prelim: list[dict] = []
    for key, meta in helm_releases.items():
        file_data = helm_files.get(key)
        current = helm_current_overrides.get(key) or (
            extract_helm_version(file_data["content"]) if file_data else None
        )
        latest = helm_latest.get(key)
        floating = _is_floating_version(current)
        # Floating (e.g. dev's 107.x) auto-tracks latest via Flux — no manual bump.
        has_update = bool(current and latest and current != latest and not floating)
        row: dict = {
            "key": key,
            "label": meta["label"],
            "file": meta["file"],
            "current_version": current,
            "latest_version": latest,
            "has_update": has_update,
            "floating": floating,
            "is_breaking": is_minor_or_major_bump(current, latest) if (current and latest and not floating) else False,
            "changelog_url": meta["changelog_url"],
        }
        if key == "jfrog-artifactory":
            row["app_version"] = artifactory_app_version(latest) if latest else ""
        helm_rows_prelim.append(row)

    oci_rows_prelim: list[dict] = []
    for key, meta in oci_repos.items():
        file_data = oci_files.get(key)
        current = extract_oci_tag(file_data["content"]) if file_data else None
        if key in ("karpenter", "karpenter-crd"):
            latest = karpenter_latest
            error = karpenter_error
        else:
            latest = snyk_broker_latest
            error = None if snyk_broker_latest else "Docker Hub fetch failed"
        has_update = bool(current and latest and current != latest)
        oci_rows_prelim.append({
            "key": key,
            "label": meta["label"],
            "file": meta["file"],
            "current_version": current,
            "latest_version": latest,
            "has_update": has_update,
            "is_breaking": is_minor_or_major_bump(current, latest) if (current and latest) else False,
            "changelog_url": meta["changelog_url"],
            "error": error,
        })

    async def _no_notes():
        return {"available": False}

    # Fetch release notes in parallel for all rows that have updates
    all_rows = helm_rows_prelim + oci_rows_prelim
    rn_tasks = [
        fetch_release_notes(r["key"], r["current_version"], r["latest_version"])
        if (r["has_update"] and r["current_version"] and r["latest_version"])
        else _no_notes()
        for r in all_rows
    ]
    rn_results = await asyncio.gather(*rn_tasks, return_exceptions=True)

    for row, rn in zip(all_rows, rn_results):
        if isinstance(rn, Exception):
            row["release_notes"] = {"available": False, "error": str(rn)}
        else:
            row["release_notes"] = rn

    return {
        "branch": branch,
        # Preview never creates the branch; report whether it already exists so
        # the UI can show "not cut yet" instead of a "just created" badge.
        "branch_created": False,
        "branch_exists": branch_exists,
        "branch_url": branch_url,
        "ami": ami_section,
        "helm_charts": helm_rows_prelim,
        "oci_repos": oci_rows_prelim,
    }


async def apply_jfrog_env_changes(
    token: str,
    org: str,
    repo: str,
    branch: str,
    new_ami: str,
    helm_versions: dict,
    oci_versions: dict,
    tfvars_path: str,
    nodeclass_path: str | None,
    env_label: str,
    rebase_from_main: bool = False,
    new_ami_name: str = "",
    extra_helm_releases: dict | None = None,
    extra_oci_repos: dict | None = None,
    eks_cluster: str | None = None,
) -> dict:
    """
    Commit AMI and chart version updates to the maintenance branch.
    Re-reads each file from the branch immediately before writing to get a fresh SHA.
    Works for both dev and prod via env-specific file paths and env_label.
    Passing nodeclass_path=None skips the Karpenter nodeclass commit (e.g. JFrog
    prod, whose nodeclass AMI is inherited from the shared base updated from dev).
    main is merged into the branch on every apply, so a commit never lands on a
    stale base; rebase_from_main is accepted for compatibility and ignored.
    """
    committed: list[str] = []
    errors: list[str] = []

    # Ensure the maintenance branch exists. Preview endpoints are now read-only,
    # so the branch is cut here on the explicit Apply action (idempotent — a
    # pre-existing branch is reused, never re-created).
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

    # AMI updates
    if new_ami and eks_cluster:
        # Refuse to move the nodes ahead of the control plane. The AMI is picked
        # by the version tfvars declares, so a staged bump offers a newer
        # Kubernetes than the cluster runs, and a kubelet ahead of the API server
        # is unsupported. Upgrade the control plane first.
        declared = extract_eks_version_tfvars(
            (await get_file(token, org, repo, tfvars_path, branch))["content"])
        node_now = await ami_eks_minor(new_ami)
        if declared and node_now and _minor(node_now) > _minor(declared):
            declared = node_now  # the AMI itself is the authority on what is installed
        live = await fetch_live_eks_version(eks_cluster)
        if node_now and live and _minor(node_now) > _minor(live):
            raise RuntimeError(
                f"{env_label}: that gold image is built for EKS {node_now} but "
                f"{eks_cluster} is running {live}. Installing it would put the kubelet "
                f"ahead of the API server. Upgrade the control plane first.")
        if node_now and not live:
            current_node = await ami_eks_minor(
                extract_ami_from_nodeclass(
                    (await get_file(token, org, repo, nodeclass_path, branch))["content"])
                if nodeclass_path else None)
            if current_node and _minor(node_now) > _minor(current_node):
                raise RuntimeError(
                    f"{env_label}: that gold image is built for EKS {node_now} and the "
                    f"nodes are on {current_node}, but the running control-plane version "
                    f"could not be read to confirm the jump is safe "
                    f"(eks:DescribeCluster is not granted). Refusing rather than "
                    f"guessing; upgrade the control plane first, or grant the read.")

    if new_ami:
        await commit_file(
            tfvars_path,
            lambda c: patch_ami_in_tfvars(c, new_ami, new_ami_name),
            f"chore({env_label}): update node AMI to {new_ami}",
        )
        # Skip the env-specific Karpenter nodeclass when nodeclass_path is None
        # (JFrog prod inherits its nodeclass AMI from the shared base, updated
        # via the dev flow).
        if nodeclass_path:
            await commit_file(
                nodeclass_path,
                lambda c: patch_ami_in_nodeclass(c, new_ami, new_ami_name),
                f"chore({env_label}): update Karpenter nodeclass AMI to {new_ami}",
            )

    # Helm chart version updates
    helm_releases = {**HELM_RELEASES, **(extra_helm_releases or {})}
    for key, new_version in helm_versions.items():
        meta = helm_releases.get(key)
        if not meta:
            continue
        label = meta["label"]
        await commit_file(
            meta["file"],
            lambda c, v=new_version: patch_helm_version(c, v),
            f"chore({env_label}): update {label} chart to {new_version}",
        )

    # OCI repo tag updates
    oci_repos = {**OCI_REPOS, **(extra_oci_repos or {})}
    for key, new_tag in oci_versions.items():
        meta = oci_repos.get(key)
        if not meta:
            continue
        label = meta["label"]
        await commit_file(
            meta["file"],
            lambda c, v=new_tag: patch_oci_tag(c, v),
            f"chore({env_label}): update {label} to {new_tag}",
        )

    if errors:
        raise RuntimeError(f"Some commits failed: {'; '.join(errors)}. Succeeded: {committed}")

    return {"committed_files": committed, "branch": branch}


# ─── Shared base Helm charts (kubernetes/base/releases) ───────────────────────

async def get_base_charts_params(token: str, org: str, repo: str) -> dict:
    """Preview the shared base/releases charts on the maintenance branch.

    These charts are pulled by both the JFrog and CBJ clusters, so they get their
    own card instead of riding in a tool-specific modal. Read-only: previews
    against the branch when it exists, otherwise against main, and never cuts it.
    """
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

    keys = list(SHARED_BASE_RELEASES.keys())
    metas = [SHARED_BASE_RELEASES[k] for k in keys]
    # Files first, then latest: an Artifactory-backed chart needs its manifest's
    # sourceRef to know which index to read.
    files = await asyncio.gather(*[safe_get(m["file"]) for m in metas])
    latests = await asyncio.gather(*[fetch_helm_latest(m, f) for m, f in zip(metas, files)])

    rows: list[dict] = []
    for key, meta, file_data, latest in zip(keys, metas, files, latests):
        current = extract_helm_version(file_data["content"]) if file_data else None
        floating = _is_floating_version(current)
        has_update = bool(current and latest and current != latest and not floating)
        rows.append({
            "key": key,
            "label": meta["label"],
            "file": meta["file"],
            "current_version": current,
            "latest_version": latest,
            "has_update": has_update,
            "floating": floating,
            "is_breaking": is_minor_or_major_bump(current, latest) if (current and latest and not floating) else False,
            "changelog_url": meta["changelog_url"],
        })

    async def _no_notes():
        return {"available": False}

    rn_results = await asyncio.gather(*[
        fetch_release_notes(r["key"], r["current_version"], r["latest_version"])
        if (r["has_update"] and r["current_version"] and r["latest_version"])
        else _no_notes()
        for r in rows
    ], return_exceptions=True)
    for row, rn in zip(rows, rn_results):
        row["release_notes"] = {"available": False, "error": str(rn)} if isinstance(rn, Exception) else rn

    return {
        "branch": branch,
        "branch_created": False,
        "branch_exists": branch_exists,
        "branch_url": f"https://github.com/{org}/{repo}/tree/{branch}",
        "helm_charts": rows,
    }


async def apply_base_charts_changes(
    token: str,
    org: str,
    repo: str,
    branch: str,
    helm_versions: dict,
    rebase_from_main: bool = False,
) -> dict:
    """Commit shared base/releases chart bumps to the maintenance branch."""
    committed: list[str] = []
    errors: list[str] = []

    await get_or_create_branch(token, org, repo, branch)
    if rebase_from_main:
        merged = await merge_main_into_branch(token, org, repo, branch)
        if merged["updated"]:
            committed.append(f"(merged main into {branch})")

    for key, new_version in helm_versions.items():
        meta = SHARED_BASE_RELEASES.get(key)
        if not meta:
            continue
        path = meta["file"]
        try:
            f = await get_file(token, org, repo, path, branch)
            new_content = patch_helm_version(f["content"], new_version)
            if new_content == f["content"]:
                continue
            await put_file(token, org, repo, path, new_content, f["sha"],
                           f"chore(base): update {meta['label']} chart to {new_version}", branch)
            committed.append(path)
        except Exception as e:
            logger.error("Failed to commit %s: %s", path, e)
            errors.append(f"{path}: {e}")

    return {"committed_files": committed, "errors": errors}
