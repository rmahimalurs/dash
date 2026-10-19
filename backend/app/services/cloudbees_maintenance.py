import asyncio
import logging
import re
from typing import Optional

import boto3
import httpx

logger = logging.getLogger(__name__)

EKS_VERSION = "1.34"
CB_RELEASE_NOTES_BASE = "https://docs.cloudbees.com/docs/release-notes/latest/cloudbees-ci"

# ─── File paths ───────────────────────────────────────────────────────────────

CB_CORE_BASE_PATH = "kubernetes/base/jenkins/releases/cloudbees-core.yaml"

# Karpenter OCI charts. The version lives in the OCIRepository `ref.tag`, shared
# across every jenkins env via the base overlay (so a bump lands for all clusters).
# Same upstream chart as JFrog, pinned independently (base/jenkins vs base/jfrog).
CB_OCI_REPOS = {
    "karpenter": {
        "file": "kubernetes/base/jenkins/repositories/karpenter.yaml",
        "changelog_url": "https://github.com/kubernetes-sigs/karpenter/releases",
        "label": "Karpenter",
    },
    "karpenter-crd": {
        "file": "kubernetes/base/jenkins/repositories/karpenter-crd.yaml",
        "changelog_url": "https://github.com/kubernetes-sigs/karpenter/releases",
        "label": "Karpenter CRD",
    },
}

CB_ENVS = {
    "dev-east": {
        "label": "Commercial Dev (East)",
        "tfvars_path": "terraform/envs/jenkins/envs/dev-east/terraform.tfvars",
        "nodeclass_path": "kubernetes/envs/jenkins/dev-east/cluster-ops/karpenter-node-class.yaml",
        "controller_ami_owner": "743302140042",
        "controller_ami_region": "us-east-1",
        "agent_ami_owner": "743302140042",
        "agent_ami_region": "us-east-1",
    },
    "gc-dev-west": {
        "label": "Gov Cloud Dev (West)",
        "tfvars_path": "terraform/envs/jenkins/envs/gc-dev-west/terraform.tfvars",
        "nodeclass_path": "kubernetes/envs/jenkins/gc-dev-west/cluster-ops/karpenter-node-class.yaml",
        "controller_ami_owner": "021568039808",
        "controller_ami_region": "us-gov-west-1",
        "agent_ami_owner": "021568039808",
        "agent_ami_region": "us-gov-west-1",
    },
    "prod-east": {
        "label": "Commercial Prod (East)",
        "tfvars_path": "terraform/envs/jenkins/envs/prod-east/terraform.tfvars",
        "nodeclass_path": "kubernetes/envs/jenkins/prod-east/cluster-ops/karpenter-node-class.yaml",
        "controller_ami_owner": "743302140042",
        "controller_ami_region": "us-east-1",
        "agent_ami_owner": "743302140042",
        "agent_ami_region": "us-east-1",
    },
    "gc-prod-west": {
        "label": "Gov Cloud Prod (West)",
        "tfvars_path": "terraform/envs/jenkins/envs/gc-prod-west/terraform.tfvars",
        "nodeclass_path": "kubernetes/envs/jenkins/gc-prod-west/cluster-ops/karpenter-node-class.yaml",
        "controller_ami_owner": "021568039808",
        "controller_ami_region": "us-gov-west-1",
        "agent_ami_owner": "021568039808",
        "agent_ami_region": "us-gov-west-1",
    },
}

# ─── Extractors ───────────────────────────────────────────────────────────────

def extract_chart_version(content: str) -> Optional[str]:
    """Extract the helm chart version (e.g. 3.36754.0+34f5d0bf1f18)."""
    m = re.search(r'version:\s*(3\.\d+\.\d+\+\S+)', content)
    return m.group(1) if m else None


def extract_image_tag(content: str) -> Optional[str]:
    """Extract the CloudBees image tag (e.g. 2.555.2.36753)."""
    m = re.search(r'tag:\s*(\d+\.\d+\.\d+\.\d+)', content)
    return m.group(1) if m else None


def extract_oci_tag(content: str) -> Optional[str]:
    """Extract the OCIRepository ref.tag (e.g. Karpenter 1.13.0)."""
    m = re.search(r'tag:\s*["\']?(\d+\.\d+\.\d+)["\']?', content)
    return m.group(1) if m else None


def patch_oci_tag(content: str, new_tag: str) -> str:
    """Bump the OCIRepository ref.tag to new_tag (first occurrence)."""
    return re.sub(r'(tag:\s*)["\']?\d+\.\d+\.\d+["\']?', f'\\g<1>{new_tag}', content, count=1)


def extract_eks_ami_from_tfvars(content: str) -> Optional[str]:
    """Extract eks_ami from terraform.tfvars."""
    m = re.search(r'eks_ami\s*=\s*"(ami-[a-z0-9]+)"', content)
    return m.group(1) if m else None


def _split_nodeclasses(content: str) -> list[str]:
    """Split karpenter-node-class.yaml into individual YAML documents."""
    # Documents are separated by '---' on its own line
    docs = re.split(r'\n---\n', content)
    return [d.strip() for d in docs if d.strip()]


def extract_controller_ami(content: str) -> Optional[str]:
    """Extract AMI from the 'controller' EC2NodeClass."""
    docs = _split_nodeclasses(content)
    for doc in docs:
        if re.search(r'name:\s*controller', doc):
            m = re.search(r'id:\s*"?(ami-[a-z0-9]+)"?', doc)
            return m.group(1) if m else None
    return None


def extract_agent_ami(content: str) -> Optional[str]:
    """Extract AMI from the 'agent' EC2NodeClass."""
    docs = _split_nodeclasses(content)
    for doc in docs:
        if re.search(r'name:\s*"?agent"?\s*$', doc, re.MULTILINE):  # exact 'agent', not 'agent-arm64'
            m = re.search(r'id:\s*"?(ami-[a-z0-9]+)"?', doc)
            return m.group(1) if m else None
    return None


# ─── Patchers ─────────────────────────────────────────────────────────────────

def patch_chart_version(content: str, new_version: str) -> str:
    return re.sub(r'(version:\s*)3\.\d+\.\d+\+\S+', f'\\g<1>{new_version}', content, count=1)


def patch_image_tag(content: str, new_tag: str) -> str:
    return re.sub(r'(tag:\s*)\d+\.\d+\.\d+\.\d+', f'\\g<1>{new_tag}', content, count=1)


def _ami_comment(ami_name: str = "", region: str = "") -> str:
    """Identifying comment for an AMI line, e.g. '  # us-east-1 : <ami-name>'.

    Delegates so CBJ and the EKS upgrade path cannot drift: they wrote the same
    comment two ways, which made it impossible to tell from a file which one had
    touched a line.
    """
    from app.services.jfrog_maintenance import ami_comment
    return ami_comment(ami_name, region)


def patch_eks_ami_in_tfvars(content: str, new_ami: str, ami_name: str = "", region: str = "") -> str:
    comment = _ami_comment(ami_name, region)
    if comment:
        return re.sub(
            r'(eks_ami\s*=\s*)"ami-[a-z0-9]+"[^\n]*',
            f'\\g<1>"{new_ami}"{comment}',
            content,
            count=1,
        )
    # No identifier — swap only the id, keeping any existing comment.
    return re.sub(r'(eks_ami\s*=\s*)"ami-[a-z0-9]+"', f'\\g<1>"{new_ami}"', content, count=1)


def patch_controller_ami(content: str, new_ami: str, ami_name: str = "", region: str = "") -> str:
    """Patch the AMI id in the 'controller' EC2NodeClass only."""
    comment = _ami_comment(ami_name, region)

    def _replace_in_controller(doc: str) -> str:
        if re.search(r'name:\s*controller', doc):
            if comment:
                return re.sub(
                    r'(id:\s*)"?ami-[a-z0-9]+"?[^\n]*',
                    f'\\g<1>"{new_ami}"{comment}',
                    doc,
                    count=1,
                )
            return re.sub(r'(id:\s*)"?ami-[a-z0-9]+"?', f'\\g<1>"{new_ami}"', doc, count=1)
        return doc

    docs = _split_nodeclasses(content)
    patched = [_replace_in_controller(d) for d in docs]
    return "\n---\n".join(patched)


def patch_agent_ami(content: str, new_ami: str, ami_name: str = "", region: str = "") -> str:
    """Patch the AMI id in the 'agent' EC2NodeClass only."""
    comment = _ami_comment(ami_name, region)

    def _replace_in_agent(doc: str) -> str:
        if re.search(r'name:\s*"?agent"?\s*$', doc, re.MULTILINE):  # exact 'agent', not 'agent-arm64'
            if comment:
                return re.sub(
                    r'(id:\s*)"?ami-[a-z0-9]+"?[^\n]*',
                    f'\\g<1>"{new_ami}"{comment}',
                    doc,
                    count=1,
                )
            return re.sub(r'(id:\s*)"?ami-[a-z0-9]+"?', f'\\g<1>"{new_ami}"', doc, count=1)
        return doc

    docs = _split_nodeclasses(content)
    patched = [_replace_in_agent(d) for d in docs]
    return "\n---\n".join(patched)


# ─── Version / AMI fetchers ───────────────────────────────────────────────────

async def fetch_latest_cb_version() -> dict:
    """Fetch latest CloudBees Core chart version from ArtifactHub."""
    url = "https://artifacthub.io/api/v1/packages/helm/cloudbees/cloudbees-core"
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(url, headers={"Accept": "application/json"})
        resp.raise_for_status()
        data = resp.json()
        return {
            "version": data["version"],          # e.g. 3.36984.0+814fd3fcf17b
            "app_version": data["app_version"],  # e.g. 2.555.3.36983
        }


def boto3_client(
    service: str,
    region: str,
    assume_role_arn: str | None = None,
    aws_access_key_id: str | None = None,
    aws_secret_access_key: str | None = None,
):
    """Return a boto3 client for an env.

    Priority: explicit IAM credentials > role assumption > default (Pod Identity).
    """
    if aws_access_key_id and aws_secret_access_key:
        return boto3.client(
            service,
            region_name=region,
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key,
        )
    if assume_role_arn:
        sts_region = region if "gov" in region else None
        sts = boto3.client("sts", **({"region_name": sts_region} if sts_region else {}))
        creds = sts.assume_role(
            RoleArn=assume_role_arn,
            RoleSessionName="devops-dashboard-govcloud",
        )["Credentials"]
        return boto3.client(
            service,
            region_name=region,
            aws_access_key_id=creds["AccessKeyId"],
            aws_secret_access_key=creds["SecretAccessKey"],
            aws_session_token=creds["SessionToken"],
        )
    return boto3.client(service, region_name=region)


def _boto3_ec2(
    region: str,
    assume_role_arn: str | None = None,
    aws_access_key_id: str | None = None,
    aws_secret_access_key: str | None = None,
):
    return boto3_client("ec2", region, assume_role_arn, aws_access_key_id, aws_secret_access_key)


async def fetch_latest_controller_ami(
    env_key: str,
    assume_role_arn: str | None = None,
    aws_access_key_id: str | None = None,
    aws_secret_access_key: str | None = None,
    eks_version: str | None = None,
) -> dict:
    """
    Fetch the latest gold-image controller AMI for a Jenkins env.
    Commercial (us-east-1): uses Pod Identity credentials.
    GovCloud (us-gov-west-1): uses explicit IAM credentials or role assumption.

    The gold image name carries the cluster version, so callers pass the version
    declared in that env's tfvars; EKS_VERSION is only the fallback. Without this
    an env upgraded past EKS_VERSION would be offered the previous minor's image.
    """
    cfg = CB_ENVS[env_key]
    owner = cfg["controller_ami_owner"]
    region = cfg["controller_ami_region"]
    version = eks_version or EKS_VERSION

    def _describe() -> dict:
        ec2 = _boto3_ec2(region, assume_role_arn, aws_access_key_id, aws_secret_access_key)
        resp = ec2.describe_images(
            Owners=[owner],
            Filters=[
                {"Name": "name", "Values": [f"al2023-eks-{version}-gi-*"]},
                {"Name": "state", "Values": ["available"]},
            ],
        )
        images = sorted(resp["Images"], key=lambda x: x["CreationDate"])
        if not images:
            raise RuntimeError(f"No controller AMIs for EKS {version} found in {region}")
        latest = images[-1]
        return {"ami_id": latest["ImageId"], "ami_name": latest["Name"]}

    try:
        return await asyncio.to_thread(_describe)
    except Exception as exc:
        logger.warning("Controller AMI fetch failed for %s (%s): %s", env_key, region, exc)
        return {"ami_id": None, "ami_name": None, "error": str(exc)}


async def fetch_latest_agent_ami(
    env_key: str,
    assume_role_arn: str | None = None,
    aws_access_key_id: str | None = None,
    aws_secret_access_key: str | None = None,
    eks_version: str | None = None,
) -> dict:
    """Fetch the latest gold-image agent AMI for a Jenkins env.

    x86 agent node pools run the same CMS gold image as the controllers; the
    EKS-optimized AL2023 image is no longer used for them. The arm64 pools
    (GovCloud only) still resolve al2023@latest in their nodeclass and are not
    managed here.
    """
    cfg = CB_ENVS[env_key]
    owner = cfg["agent_ami_owner"]
    region = cfg["agent_ami_region"]
    version = eks_version or EKS_VERSION

    def _describe() -> dict:
        ec2 = _boto3_ec2(region, assume_role_arn, aws_access_key_id, aws_secret_access_key)
        resp = ec2.describe_images(
            Owners=[owner],
            Filters=[
                {"Name": "name", "Values": [f"al2023-eks-{version}-gi-*"]},
                {"Name": "state", "Values": ["available"]},
            ],
        )
        images = sorted(resp["Images"], key=lambda x: x["CreationDate"])
        if not images:
            raise RuntimeError(f"No agent AMIs for EKS {version} found in {region}")
        latest = images[-1]
        return {"ami_id": latest["ImageId"], "ami_name": latest["Name"]}

    try:
        return await asyncio.to_thread(_describe)
    except Exception as exc:
        logger.warning("Agent AMI fetch failed for %s (%s): %s", env_key, region, exc)
        return {"ami_id": None, "ami_name": None, "error": str(exc)}


# ─── CloudBees release notes ──────────────────────────────────────────────────

_CB_SECTION_LABELS = {
    "upgrade notes": ("Upgrade Notes", True),
    "new features": ("New Features", False),
    "feature enhancements": ("Feature Enhancements", False),
    "resolved issues": ("Resolved Issues", False),
    "resolved": ("Resolved Issues", False),
}

_CB_SKIP_SECTIONS = frozenset({"quick links", "security advisories", "plugins list"})


def _cb_version_tuple(v: str) -> tuple:
    try:
        return tuple(int(x) for x in v.split(".")[:4])
    except Exception:
        return (0, 0, 0, 0)


def _parse_cb_release_notes_page(html: str) -> dict:
    """
    Parse a single CloudBees modern-cloud-platforms release notes page.
    Items are in <dt class="hdlist1"> tags within <dl> definition lists.
    Returns {date, sections: [{heading, items, is_breaking}], has_breaking}.
    """
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE)

    # Extract release date
    date_match = re.search(r"Rolling release:\s*(\d{4}-\d{2}-\d{2})", html)
    date = date_match.group(1) if date_match else ""

    h2_re = re.compile(r"<h2[^>]*>(.*?)</h2>", re.IGNORECASE | re.DOTALL)
    h2_headings = list(h2_re.finditer(html))

    sections: list[dict] = []
    has_breaking = False

    for i, m in enumerate(h2_headings):
        heading_text = re.sub(r"<[^>]+>", "", m.group(1)).strip()
        heading_lower = heading_text.lower()

        matched = next(
            ((label, breaking) for key, (label, breaking) in _CB_SECTION_LABELS.items() if key in heading_lower),
            None,
        )
        if not matched or any(skip in heading_lower for skip in _CB_SKIP_SECTIONS):
            continue

        label, is_breaking = matched

        # Slice section HTML until next h2
        start = m.end()
        end = h2_headings[i + 1].start() if i + 1 < len(h2_headings) else len(html)
        section_html = html[start:end]

        # Items are in <dt class="hdlist1"> tags
        dt_re = re.compile(r"<dt[^>]*>(.*?)</dt>", re.IGNORECASE | re.DOTALL)
        items = []
        for dt in dt_re.finditer(section_html):
            text = re.sub(r"<[^>]+>", "", dt.group(1)).strip()
            text = re.sub(r"\s+", " ", text)
            if text and text.lower() not in ("none", "n/a", ""):
                items.append(text)

        if not items:
            # Check for plain "None." paragraph indicating no items
            plain = re.sub(r"<[^>]+>", " ", section_html)
            plain = re.sub(r"\s+", " ", plain).strip()
            if plain.lower().startswith("none"):
                continue

        if items:
            sections.append({"heading": label, "items": items[:12], "is_breaking": is_breaking})
            if is_breaking:
                has_breaking = True

    return {"date": date, "sections": sections, "has_breaking": has_breaking}


async def fetch_cb_release_notes(current_tag: str, latest_tag: str) -> dict:
    """
    Fetch CloudBees CI Modern Cloud Platforms release notes for all versions
    in the upgrade range (current_tag, latest_tag] — exclusive current, inclusive latest.
    """
    cur_t = _cb_version_tuple(current_tag)
    lat_t = _cb_version_tuple(latest_tag)
    source_url = f"{CB_RELEASE_NOTES_BASE}/modern-cloud-platforms/{latest_tag}"

    try:
        # 1. Get the version list from the index page
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            index_resp = await client.get(f"{CB_RELEASE_NOTES_BASE}/")
            index_resp.raise_for_status()

        # Extract all app_versions from modern-cloud-platforms links
        version_re = re.compile(
            r"/docs/release-notes/latest/cloudbees-ci/modern-cloud-platforms/(\d+\.\d+\.\d+\.\d+)"
        )
        versions_in_range = [
            v for v in dict.fromkeys(version_re.findall(index_resp.text))  # deduplicate, preserve order
            if cur_t < _cb_version_tuple(v) <= lat_t
        ]

        if not versions_in_range:
            return {"available": False, "error": "No versions found in upgrade range", "source_url": source_url}

        # 2. Fetch each version's release notes page concurrently
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            responses = await asyncio.gather(
                *[client.get(f"{CB_RELEASE_NOTES_BASE}/modern-cloud-platforms/{v}") for v in versions_in_range],
                return_exceptions=True,
            )

        # 3. Parse each page into entries
        entries = []
        for version, resp in zip(versions_in_range, responses):
            if isinstance(resp, Exception):
                logger.warning("CB release notes fetch failed for %s: %s", version, resp)
                continue
            parsed = _parse_cb_release_notes_page(resp.text)
            # Flatten sections into notes list for changelog-style display
            notes = []
            for sec in parsed["sections"]:
                prefix = "⚠ " if sec["is_breaking"] else ""
                for item in sec["items"]:
                    notes.append(f"{prefix}[{sec['heading']}] {item}")
            entries.append({
                "version": version,
                "date": parsed["date"],
                "notes": notes,
                "has_important": parsed["has_breaking"],
                "sections": parsed["sections"],   # also include structured for richer display
            })

        if not entries:
            return {"available": False, "error": "Could not parse any release notes", "source_url": source_url}

        return {
            "available": True,
            "type": "cb_release",
            "entries": entries,
            "has_breaking": any(e["has_important"] for e in entries),
            "source_url": source_url,
        }

    except Exception as exc:
        logger.warning("CB release notes fetch failed: %s", exc)
        return {"available": False, "error": str(exc), "source_url": source_url}
