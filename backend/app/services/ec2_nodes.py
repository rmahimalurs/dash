"""
Live EC2 instance-flavor counts for the OE readiness "Resource Scale Up" section.

CBJ and JFrog now provision nodes dynamically via Karpenter (previously Cluster
Autoscaler), so a fixed instance count is no longer meaningful. Instead we count
the currently-running EC2 instances Karpenter has launched, grouped by instance
type, per environment. SonarQube runs on fixed EC2 app/search nodes, so it is
counted by its Name tag rather than by the Karpenter tag.

Credentials mirror ``cbj_resource_analysis._boto3_cloudwatch_client``:
  - cbj-prod-east    -> assume JENKINS_PROD_EAST_ROLE_ARN (478919403635, us-east-1)
  - cbj-gc-prod-west -> GovCloud IAM user keys           (020847197482, us-gov-west-1)
  - jfrog-prod /
    sonarqube-prod   -> assume CERT_EXPORT_PROD_ROLE_ARN (623510781344, us-east-1;
                        the existing JFrog-prod assume-role path)

Every path is best-effort: if boto3 is missing, a role can't be assumed, or the
account lacks ec2:DescribeInstances, the target returns an ``error`` and the OE
readiness builder falls back to carried-forward sizing text.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

logger = logging.getLogger(__name__)

# key -> config. cred selects the credential path; filter selects which
# instances count ("karpenter" = tag key karpenter.sh/nodepool present;
# "name:<sub>" = Name tag contains <sub>).
TARGETS: dict[str, dict] = {
    "cbj-prod-east":    {"cred": "prod-east",   "region": "us-east-1",     "filter": "karpenter",  "label": "CloudBees Prod (East)"},
    "cbj-gc-prod-west": {"cred": "gov-prod",    "region": "us-gov-west-1", "filter": "karpenter",  "label": "CloudBees Gov Prod (West)"},
    "jfrog-prod":       {"cred": "devops-prod", "region": "us-east-1",     "filter": "karpenter",  "label": "JFrog Platform"},
    "sonarqube-prod":   {"cred": "devops-prod", "region": "us-east-1",     "filter": "name:sonar", "label": "SonarQube"},
}

# Which targets feed each OE page's resources section.
PAGE_TARGETS: dict[str, list[str]] = {
    "cbj": ["cbj-prod-east", "cbj-gc-prod-west"],
    "jfrog_sonar": ["jfrog-prod", "sonarqube-prod"],
}


def _ec2_client(cred: str, region: str):
    """Build a boto3 EC2 client for a credential path, or None if unavailable."""
    try:
        import boto3
        from botocore.exceptions import BotoCoreError, ClientError
    except ImportError:
        logger.warning("boto3 not installed; EC2 node counts disabled")
        return None

    from app.config import get_settings
    settings = get_settings()

    key = secret = role_arn = ""
    if cred == "prod-east":
        key = settings.JENKINS_PROD_EAST_AWS_ACCESS_KEY_ID
        secret = settings.JENKINS_PROD_EAST_AWS_SECRET_ACCESS_KEY
        role_arn = settings.JENKINS_PROD_EAST_ROLE_ARN
    elif cred == "gov-prod":
        key = settings.GOVCLOUD_PROD_AWS_ACCESS_KEY_ID
        secret = settings.GOVCLOUD_PROD_AWS_SECRET_ACCESS_KEY
    elif cred == "devops-prod":
        # Reuse the existing JFrog-prod assume-role path (cert-export role in
        # 623510781344). Its policy must include ec2:DescribeInstances.
        role_arn = settings.CERT_EXPORT_PROD_ROLE_ARN
    else:
        return None

    if key and secret:
        try:
            return boto3.client("ec2", region_name=region,
                                aws_access_key_id=key, aws_secret_access_key=secret)
        except (BotoCoreError, ClientError) as exc:
            logger.warning("EC2 client from explicit keys (%s) failed: %s", cred, exc)

    if role_arn:
        try:
            sts = boto3.client("sts")
            creds = sts.assume_role(
                RoleArn=role_arn,
                RoleSessionName="devops-dashboard-oe-nodes",
                DurationSeconds=900,
            )["Credentials"]
            return boto3.client(
                "ec2", region_name=region,
                aws_access_key_id=creds["AccessKeyId"],
                aws_secret_access_key=creds["SecretAccessKey"],
                aws_session_token=creds["SessionToken"],
            )
        except (BotoCoreError, ClientError) as exc:
            logger.warning("Could not assume %s for EC2 (%s): %s", role_arn, cred, exc)

    try:
        return boto3.client("ec2", region_name=region)
    except (BotoCoreError, ClientError) as exc:
        logger.warning("Default EC2 client (%s) failed: %s", cred, exc)
    return None


def _filters(kind: str) -> list[dict]:
    base = [{"Name": "instance-state-name", "Values": ["running"]}]
    if kind == "karpenter":
        base.append({"Name": "tag-key", "Values": ["karpenter.sh/nodepool"]})
    elif kind.startswith("name:"):
        sub = kind.split(":", 1)[1]
        base.append({"Name": "tag:Name", "Values": [f"*{sub}*"]})
    return base


def count_target(key: str) -> dict:
    """Return {key, label, counts:{type:n}, total, error?} for one target."""
    cfg = TARGETS[key]
    out = {"key": key, "label": cfg["label"], "counts": {}, "total": 0, "error": None}
    client = _ec2_client(cfg["cred"], cfg["region"])
    if client is None:
        out["error"] = "no AWS credentials available"
        return out
    try:
        counts: dict[str, int] = {}
        paginator = client.get_paginator("describe_instances")
        for page in paginator.paginate(Filters=_filters(cfg["filter"])):
            for res in page.get("Reservations", []):
                for inst in res.get("Instances", []):
                    itype = inst.get("InstanceType", "unknown")
                    counts[itype] = counts.get(itype, 0) + 1
        out["counts"] = dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))
        out["total"] = sum(counts.values())
    except Exception as exc:  # noqa: BLE001 — boto/permission failures are expected/soft
        logger.warning("describe_instances failed for %s: %s", key, exc)
        out["error"] = str(exc)[:200]
    return out


def summarize(target_keys: list[str]) -> dict[str, dict]:
    """Count several targets concurrently. Returns {key: result}."""
    results: dict[str, dict] = {}
    if not target_keys:
        return results
    with ThreadPoolExecutor(max_workers=len(target_keys)) as pool:
        futures = {pool.submit(count_target, k): k for k in target_keys}
        for fut in futures:
            k = futures[fut]
            try:
                results[k] = fut.result()
            except Exception as exc:  # noqa: BLE001
                results[k] = {"key": k, "label": TARGETS[k]["label"],
                              "counts": {}, "total": 0, "error": str(exc)[:200]}
    return results


def counts_line(result: Optional[dict]) -> Optional[str]:
    """Human string like '12 nodes — 8× m6a.16xlarge, 4× m6a.8xlarge', or None."""
    if not result or result.get("error") or not result.get("counts"):
        return None
    parts = [f"{n}&times; {t}" for t, n in result["counts"].items()]
    return f"{result['total']} nodes &mdash; " + ", ".join(parts)
