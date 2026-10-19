"""
CBJ Resource Analysis — compares what a container asked Kubernetes for
(Reserved) against what it actually used at its busiest moment recently
(Used at Peak), sourced from CloudWatch Container Insights.

Two targets, same methodology:
- "agents": ephemeral build/agent containers (excludes the `jenkins` controller
  container itself). Usage is bursty, so Used at Peak looks back 7 days to
  catch real spikes.
- "controllers": the always-on `jenkins` controller container, one per team.

Reserved/Limit and Used at Peak both use the same 7-day window. Reserved/
Limit used to use a short 1-day window for agents on the theory that a
short window avoids showing a stale, already-fixed value — but Container
Insights only emits request/limit near pod start, not continuously, so a
1-day window silently drops any container that hasn't restarted in the last
day even though its 7-day usage data is right there (confirmed live: a
buildkit container in cbc-kmp had real utilization data but was invisible
here because its last request/limit datapoint was ~2 days old). A request
rarely changes without a restart anyway, which is the same reasoning
already used for controllers — so agents now match.

Covers prod-east and gc-prod-west separately (different AWS accounts/partitions,
never mixed into one result set).

CONFIRMED live: a single whole-cluster Metrics Insights query (the original
design) silently truncates around ~500 result rows regardless of an explicit
SQL LIMIT — with 2000+ distinct (Namespace, ContainerName) pairs on prod-east,
most of the fleet was invisible the whole time (kmp/buildkit was one real
container that never showed up, purely because of this cap, not because it
lacked data). Fixed by querying per-namespace instead of per-cluster — each
namespace's own result set is small, so nothing gets cut — fetched
concurrently so this doesn't turn into hundreds of sequential round-trips.

Originally authored by Srikanth Sharikar (PR #11); imported here and reused by
both the Monitoring page and the CBJ waste-email automation tile.
"""

import asyncio
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)

_NAMESPACE_CONCURRENCY = 15

# Per-namespace querying is correct but expensive (~namespaces x metrics
# GetMetricData calls per compute — ~1,180 on prod-east). The underlying data
# moves slowly (7-day windows; podTemplate requests only change on redeploy),
# so cache each (env, target) result briefly to collapse repeated page loads /
# the podTemplate endpoint's cross-check into one sweep. Only successful,
# non-empty results are cached, so a transient enumeration failure isn't
# frozen in for the whole TTL.
_RESULT_CACHE_TTL_SECONDS = 300
_result_cache: dict[tuple[str, str], tuple[float, list[dict]]] = {}
_result_cache_lock = threading.Lock()


def _compute_env_cached(env: str, target: str) -> list[dict]:
    key = (env, target)
    now = time.monotonic()
    with _result_cache_lock:
        hit = _result_cache.get(key)
        if hit is not None and (now - hit[0]) < _RESULT_CACHE_TTL_SECONDS:
            return hit[1]
    rows = _compute_env(env, target)
    if rows:  # don't cache empty/failed fetches (see note above)
        with _result_cache_lock:
            _result_cache[key] = (time.monotonic(), rows)
    return rows

_METRICS = (
    "container_cpu_request",
    "container_cpu_limit",
    "container_cpu_utilization",
    "container_memory_request",
    "container_memory_limit",
    "container_memory_utilization",
)

# Usage needs a longer lookback to catch bursty, infrequent builds; Reserved/
# Limit uses the same window now (see module docstring for why).
_USAGE_WINDOW_DAYS = 7

# env -> (cluster_name, region)
_ENVS = {
    "prod-east": ("jenkins-kms", "us-east-1"),
    "gc-prod-west": ("jenkins-west-gov", "us-gov-west-1"),
}

_TARGETS = ("agents", "controllers")


def _boto3_cloudwatch_client(env: str, region: str):
    """
    Return a boto3 CloudWatch client for the given CBJ environment. Tries, in
    order: (1) explicit access keys for that environment, (2) assume the
    environment's cross-account role via the dashboard's Pod Identity, (3) the
    default credential chain. Returns None if boto3 is unavailable or all auth
    paths fail. Mirrors copy_controller._boto3_iam_client.

    In the deployed cluster gc-prod-west uses explicit keys (an IAM user in the
    GovCloud account) while prod-east has no keys and assumes
    JENKINS_PROD_EAST_ROLE_ARN (DEVOPS-DASHBOARD-READONLY) — so the assume-role
    tier is required for prod-east CloudWatch to work at all; without it we fall
    through to the jfrog-dev Pod Identity, which cannot read prod-east metrics.
    """
    try:
        import boto3
        from botocore.exceptions import BotoCoreError, ClientError
    except ImportError:
        logger.warning("boto3 not installed; cbj-resource-analysis lookups disabled")
        return None

    from app.config import get_settings
    settings = get_settings()

    if env == "prod-east":
        key = settings.JENKINS_PROD_EAST_AWS_ACCESS_KEY_ID
        secret = settings.JENKINS_PROD_EAST_AWS_SECRET_ACCESS_KEY
        role_arn = settings.JENKINS_PROD_EAST_ROLE_ARN
    elif env == "gc-prod-west":
        key = settings.GOVCLOUD_PROD_AWS_ACCESS_KEY_ID
        secret = settings.GOVCLOUD_PROD_AWS_SECRET_ACCESS_KEY
        role_arn = ""  # GovCloud auth is the IAM user's own keys; no role to assume.
    else:
        return None

    if key and secret:
        try:
            return boto3.client(
                "cloudwatch",
                region_name=region,
                aws_access_key_id=key,
                aws_secret_access_key=secret,
            )
        except (BotoCoreError, ClientError) as exc:
            logger.warning("Could not build CloudWatch client for %s from explicit keys: %s", env, exc)

    if role_arn:
        try:
            sts = boto3.client("sts")
            assumed = sts.assume_role(
                RoleArn=role_arn,
                RoleSessionName="devops-dashboard-cbj-analysis",
                DurationSeconds=900,
            )
            creds = assumed["Credentials"]
            return boto3.client(
                "cloudwatch",
                region_name=region,
                aws_access_key_id=creds["AccessKeyId"],
                aws_secret_access_key=creds["SecretAccessKey"],
                aws_session_token=creds["SessionToken"],
            )
        except (BotoCoreError, ClientError) as exc:
            logger.warning("Could not assume %s for %s CloudWatch: %s", role_arn, env, exc)

    try:
        return boto3.client("cloudwatch", region_name=region)
    except (BotoCoreError, ClientError) as exc:
        logger.warning("Default CloudWatch client for %s failed: %s", env, exc)
    return None


def _container_filter(target: str) -> str:
    return "ContainerName = 'jenkins'" if target == "controllers" else "ContainerName != 'jenkins'"


def _list_namespaces(client, cluster_name: str, target: str, start, end) -> list[str]:
    """Every namespace with at least one matching container in the window —
    bounded by controller count (~200), nowhere near the ~500-row cap.

    CONFIRMED live: dropping PodName/FullPodName from the SCHEMA() dimension
    list (even though this query doesn't GROUP BY or filter on them) silently
    returns zero rows — must declare the same full schema signature used
    elsewhere, not just the dimensions actually referenced."""
    expr = (
        f'SELECT MAX(container_cpu_request) FROM SCHEMA("ContainerInsights", '
        f"ClusterName,Namespace,ContainerName,PodName,FullPodName) "
        f"WHERE ClusterName='{cluster_name}' AND {_container_filter(target)} "
        f"GROUP BY Namespace"
    )
    try:
        resp = client.get_metric_data(
            MetricDataQueries=[{"Id": "q0", "Expression": expr, "Period": 86400}],
            StartTime=start,
            EndTime=end,
        )
    except Exception as exc:
        logger.warning("cbj_resource_analysis: namespace enumeration failed: %s", exc)
        return []
    return sorted({r["Label"] for r in resp.get("MetricDataResults", []) if r.get("Label") and r.get("Values")})


def _fetch_namespace_metric(client, cluster_name: str, namespace: str, metric: str, target: str, start, end) -> dict[str, float]:
    """One (namespace, metric) query. CONFIRMED live: this account's
    GetMetricData quota caps at 1 query per call (not the usual 500), so
    metrics can't be batched into one call the way _list_namespaces might
    suggest — every (namespace, metric) pair is its own round-trip, run
    concurrently by the caller."""
    safe_ns = namespace.replace("'", "''")
    expr = (
        f'SELECT MAX({metric}) FROM SCHEMA("ContainerInsights", '
        f"ClusterName,Namespace,ContainerName,PodName,FullPodName) "
        f"WHERE ClusterName='{cluster_name}' AND Namespace='{safe_ns}' AND {_container_filter(target)} "
        f"GROUP BY Namespace, ContainerName"
    )
    out: dict[str, float] = {}
    try:
        resp = client.get_metric_data(
            MetricDataQueries=[{"Id": "q0", "Expression": expr, "Period": 86400}],
            StartTime=start,
            EndTime=end,
        )
    except Exception as exc:
        logger.warning("cbj_resource_analysis: query for %s/%s failed: %s", namespace, metric, exc)
        return out
    for r in resp.get("MetricDataResults", []):
        label = r.get("Label", "")
        vals = r.get("Values", [])
        if label and vals:
            out[label] = max(vals)
    return out


def _status(pct_used: float | None) -> str:
    """Waste severity, mirrors the ok/warning/critical convention used elsewhere in this app."""
    if pct_used is None:
        return "unknown"
    if pct_used < 0.10:
        return "critical"   # using under 10% of what was reserved
    if pct_used < 0.30:
        return "warning"
    return "ok"


def _compute_env(env: str, target: str) -> list[dict]:
    from datetime import datetime, timedelta, timezone

    cluster_name, region = _ENVS[env]
    client = _boto3_cloudwatch_client(env, region)
    if client is None:
        return []

    # CloudWatch Metrics Insights GROUP BY queries with a 1-day period silently
    # return zero rows (no error, no Messages) unless the overall time range is
    # aligned to day boundaries. Truncate to midnight UTC before subtracting.
    now = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    usage_start = now - timedelta(days=_USAGE_WINDOW_DAYS)

    # Request/limit are only reported when a pod starts, not continuously —
    # both targets now use the full 7-day window so a container that hasn't
    # restarted in the last day still surfaces (see module docstring).
    #
    # Query per-namespace, concurrently, instead of one whole-cluster query —
    # a single query silently truncates around ~500 rows regardless of an
    # explicit LIMIT, which was hiding most of the fleet (see module docstring).
    namespaces = _list_namespaces(client, cluster_name, target, usage_start, now)
    data: dict[str, dict[str, float]] = {m: {} for m in _METRICS}
    if namespaces:
        with ThreadPoolExecutor(max_workers=_NAMESPACE_CONCURRENCY) as pool:
            futures = {
                pool.submit(_fetch_namespace_metric, client, cluster_name, ns, m, target, usage_start, now): m
                for ns in namespaces for m in _METRICS
            }
            for fut in as_completed(futures):
                metric = futures[fut]
                data[metric].update(fut.result())

    labels = set(data["container_cpu_request"]) | set(data["container_memory_request"])
    rows = []
    for label in labels:
        parts = label.split(" ", 1)
        if len(parts) != 2:
            continue
        namespace, container = parts

        cpu_req_m = data["container_cpu_request"].get(label)
        cpu_lim_m = data["container_cpu_limit"].get(label)
        cpu_util_pct = data["container_cpu_utilization"].get(label)
        mem_req_b = data["container_memory_request"].get(label)
        mem_lim_b = data["container_memory_limit"].get(label)
        mem_util_pct = data["container_memory_utilization"].get(label)

        cpu_req = cpu_req_m / 1000 if cpu_req_m is not None else None
        cpu_used = (cpu_util_pct * cpu_lim_m / 100 / 1000) if (cpu_util_pct is not None and cpu_lim_m is not None) else None
        cpu_wasted = (cpu_req - cpu_used) if (cpu_req is not None and cpu_used is not None) else None
        cpu_pct_used = (cpu_used / cpu_req) if (cpu_used is not None and cpu_req not in (None, 0)) else None

        mem_req = mem_req_b / 1e9 if mem_req_b is not None else None
        mem_used = (mem_util_pct * mem_lim_b / 100 / 1e9) if (mem_util_pct is not None and mem_lim_b is not None) else None
        mem_wasted = (mem_req - mem_used) if (mem_req is not None and mem_used is not None) else None
        mem_pct_used = (mem_used / mem_req) if (mem_used is not None and mem_req not in (None, 0)) else None

        rows.append({
            "env": env,
            "namespace": namespace,
            "container": container,
            "cpu_reserved_cores": cpu_req,
            "cpu_used_at_peak_cores": cpu_used,
            "cpu_wasted_cores": cpu_wasted,
            "cpu_pct_used": cpu_pct_used,
            "mem_reserved_gb": mem_req,
            "mem_used_at_peak_gb": mem_used,
            "mem_wasted_gb": mem_wasted,
            "mem_pct_used": mem_pct_used,
            "status": _status(cpu_pct_used),
        })

    rows.sort(key=lambda r: (r["cpu_wasted_cores"] if r["cpu_wasted_cores"] is not None else -1), reverse=True)
    return rows


def compute_env_sync(env: str, target: str = "agents") -> list[dict]:
    """Blocking variant, for callers already off the event loop (e.g. the
    waste-email service, which runs inside asyncio.to_thread)."""
    if env not in _ENVS:
        raise ValueError(f"Unknown env '{env}', expected one of {list(_ENVS)}")
    if target not in _TARGETS:
        raise ValueError(f"Unknown target '{target}', expected one of {_TARGETS}")
    return _compute_env_cached(env, target)


async def get_cbj_resource_analysis(env: str, target: str = "agents") -> list[dict]:
    if env not in _ENVS:
        raise ValueError(f"Unknown env '{env}', expected one of {list(_ENVS)}")
    if target not in _TARGETS:
        raise ValueError(f"Unknown target '{target}', expected one of {_TARGETS}")
    return await asyncio.to_thread(_compute_env_cached, env, target)
