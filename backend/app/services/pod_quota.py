"""
CBJ pod-quota (fiftypods) audit + remediation.

Each CloudBees controller namespace (cbc-<controller>) has a `fiftypods`
ResourceQuota capping agent pods at 50. When it's full, pipelines fail with
"exceeded quota: fiftypods ... used: pods=50, limited: pods=50" and can't start
new agents.

This service lets an engineer:
  - AUDIT the fiftypods quota (used vs hard) across every controller in an env,
    flagging the ones at/near the limit.
  - see the RUNNING BUILDS on a maxed-out controller (longest-running first) —
    the candidates to kill to free agent pods — and ABORT selected ones.
  - INCREASE the quota (bounded: 1 < new <= HARD_CAP and > current used).

Quota read/patch runs on the **CJOC** via fabric8 (the cjoc SA has the
cjoc-resourcequota-editor ClusterRole). Build listing/abort runs on the
**controller's** own Script Console. Env/auth/URL helpers reuse controller_users.
"""
from __future__ import annotations

import json
import logging

import httpx

from app.services.controller_users import (
    ENVS, _cjoc_url, _controller_url, _detect_groovy_trace, _env_auth, list_controllers,
)
from app.services.jenkins import run_groovy_script

logger = logging.getLogger(__name__)

QUOTA_NAME = "fiftypods"
HARD_CAP = 100          # max pod limit an increase may set
NEAR_LIMIT_FRAC = 0.9   # >=90% used = "near limit"


def _last_json_line(raw: str):
    return json.loads(raw.strip().splitlines()[-1])


# ─── Groovy ───────────────────────────────────────────────────────────────────

# On the CJOC (fabric8): every cbc-* fiftypods quota's used/hard in one pass.
_GROOVY_AUDIT = r"""
import io.fabric8.kubernetes.client.KubernetesClientBuilder
import groovy.json.JsonOutput
def client = new KubernetesClientBuilder().build()
def out = []
try {
  client.resourceQuotas().inAnyNamespace().list().getItems().each { q ->
    def ns = q.metadata.namespace
    if (q.metadata.name == "fiftypods" && ns.startsWith("cbc-")) {
      out << [controller: ns.replaceFirst(/^cbc-/, ""), namespace: ns,
              hard: q.spec?.hard?.get("pods")?.toString(),
              used: q.status?.used?.get("pods")?.toString()]
    }
  }
} finally { client.close() }
println JsonOutput.toJson(out)
"""

# On the CJOC (fabric8): set fiftypods hard.pods for one namespace.
_GROOVY_SET = r"""
import io.fabric8.kubernetes.client.KubernetesClientBuilder
import io.fabric8.kubernetes.api.model.Quantity
import groovy.json.JsonOutput
def ns = "__NS__"
def client = new KubernetesClientBuilder().build()
try {
  def q = client.resourceQuotas().inNamespace(ns).withName("fiftypods").get()
  if (q == null) { println JsonOutput.toJson([error: "no fiftypods quota in " + ns]); return }
  q.spec.hard.put("pods", new Quantity("__LIMIT__"))
  def u = client.resourceQuotas().inNamespace(ns).resource(q).update()
  println JsonOutput.toJson([hard: u.spec?.hard?.get("pods")?.toString(),
                             used: u.status?.used?.get("pods")?.toString()])
} catch (Throwable t) {
  println JsonOutput.toJson([error: t.class.name + ": " + (t.message ?: t.toString())])
} finally { client.close() }
"""

# On the CONTROLLER: running builds, longest-running first (killable candidates).
_GROOVY_RUNNING = r"""
import groovy.json.JsonOutput
import hudson.model.Job
import jenkins.model.Jenkins
def out = []
def now = System.currentTimeMillis()
Jenkins.instance.getAllItems(Job).each { job ->
  job.builds.findAll { it.isBuilding() }.each { b ->
    out << [job: job.fullName, number: b.number, url: b.getUrl(),
            durationMs: (now - b.getStartTimeInMillis())]
  }
}
out = out.sort { -it.durationMs }
println JsonOutput.toJson([count: out.size(), builds: out.take(100)])
"""

# Reliable abort for a running build. Most CBJ builds are Pipeline (WorkflowRun)
# whose executor is a OneOffExecutor — Executor.doStop() on it returns without
# error but does NOT stop a wedged pipeline (e.g. one stuck waiting for an agent
# pod because the quota is full). WorkflowRun.doKill() (hard kill) reliably
# terminates those; fall back to executor.interrupt(ABORTED) / doStop for
# non-pipeline builds. Verified live: doKill -> result=ABORTED, doStop did not.
_GROOVY_ABORT_FN = r"""
import hudson.model.Result
def abortRun = { b ->
  try {
    if (b.metaClass.respondsTo(b, "doKill")) { b.doKill(); return true }
    def exec = b.getExecutor() ?: b.getOneOffExecutor()
    if (exec != null) { exec.interrupt(Result.ABORTED); return true }
    if (b.metaClass.respondsTo(b, "doStop")) { b.doStop(); return true }
    return false
  } catch (Throwable t) { return false }
}
"""

# On the CONTROLLER: abort running builds in bulk. __MIN_MS__ = only abort builds
# running longer than this many ms (0 = all).
_GROOVY_ABORT_ALL = _GROOVY_ABORT_FN + r"""
import jenkins.model.Jenkins
import hudson.model.Job
def minMs = __MIN_MS__ as long
def now = System.currentTimeMillis()
def aborted = 0
def failed = 0
Jenkins.instance.getAllItems(Job).each { job ->
  job.builds.findAll { it.isBuilding() }.each { b ->
    if ((now - b.getStartTimeInMillis()) < minMs) return
    if (abortRun(b)) { aborted++ } else { failed++ }
  }
}
println "ABORTED=" + aborted + " FAILED=" + failed
"""

# On the CONTROLLER: abort one running build.
_GROOVY_ABORT = _GROOVY_ABORT_FN + r"""
import jenkins.model.Jenkins
import hudson.model.Job
def job = Jenkins.instance.getItemByFullName("__JOB__", Job)
if (job == null) { println "NO_JOB"; return }
def b = job.getBuildByNumber(__NUM__ as int)
if (b == null) { println "NO_BUILD"; return }
if (!b.isBuilding()) { println "NOT_BUILDING"; return }
println abortRun(b) ? "ABORTED" : "FAILED"
"""


# ─── Public API ───────────────────────────────────────────────────────────────

def audit(env: str) -> dict:
    """fiftypods used/hard for every controller in the env, worst-first."""
    if env not in ENVS:
        return {"env": env, "error": f"Unknown environment '{env}'", "controllers": []}
    auth = _env_auth(env)
    if not auth:
        return {"env": env, "error": f"No Jenkins credentials configured for {env}", "controllers": []}
    try:
        raw = run_groovy_script(_cjoc_url(env), _GROOVY_AUDIT, auth, timeout=45)
    except httpx.HTTPError as exc:
        return {"env": env, "error": f"CJOC Script Console call failed: {exc}", "controllers": []}
    trace = _detect_groovy_trace(raw)
    if trace:
        return {"env": env, "error": f"CJOC Groovy error: {trace}", "controllers": []}
    try:
        rows = _last_json_line(raw)
    except (json.JSONDecodeError, IndexError) as exc:
        return {"env": env, "error": f"Could not parse quota audit: {exc}", "controllers": []}

    controllers = []
    for r in rows:
        try:
            hard = int(r.get("hard") or 0)
            used = int(r.get("used") or 0)
        except (TypeError, ValueError):
            hard, used = 0, 0
        at_limit = hard > 0 and used >= hard
        near = hard > 0 and used >= hard * NEAR_LIMIT_FRAC
        controllers.append({
            "controller": r.get("controller"), "namespace": r.get("namespace"),
            "hard": hard, "used": used,
            "at_limit": at_limit, "near_limit": near,
            "pct": round(used / hard * 100, 0) if hard else 0,
        })
    controllers.sort(key=lambda c: (c["hard"] - c["used"] if c["hard"] else 999, -c["used"]))
    return {
        "env": env, "error": None, "hard_cap": HARD_CAP,
        "at_limit_count": sum(1 for c in controllers if c["at_limit"]),
        "controllers": controllers,
    }


def running_builds(env: str, controller: str) -> dict:
    """Running builds on a controller, longest-running first (kill candidates)."""
    if env not in ENVS:
        return {"error": f"Unknown environment '{env}'", "builds": []}
    auth = _env_auth(env)
    if not auth:
        return {"error": f"No Jenkins credentials configured for {env}", "builds": []}
    try:
        raw = run_groovy_script(_controller_url(env, controller), _GROOVY_RUNNING, auth, timeout=60)
    except httpx.HTTPError as exc:
        return {"error": f"Controller Script Console call failed: {exc}", "builds": []}
    trace = _detect_groovy_trace(raw)
    if trace:
        return {"error": f"Controller Groovy error: {trace}", "builds": []}
    try:
        data = _last_json_line(raw)
    except (json.JSONDecodeError, IndexError) as exc:
        return {"error": f"Could not parse running builds: {exc}", "builds": []}
    return {"env": env, "controller": controller, "error": None,
            "count": data.get("count", 0), "builds": data.get("builds", [])}


def increase(env: str, controller: str, new_limit: int) -> dict:
    """Raise the fiftypods pod limit. Bounded: > current used, > current hard,
    and <= HARD_CAP."""
    if env not in ENVS:
        return {"error": f"Unknown environment '{env}'"}
    if not isinstance(new_limit, int) or new_limit <= 0:
        return {"error": "new_limit must be a positive integer"}
    if new_limit > HARD_CAP:
        return {"error": f"new_limit {new_limit} exceeds the hard cap of {HARD_CAP}"}

    # Re-read current state to validate the increase server-side.
    a = audit(env)
    if a.get("error"):
        return {"error": f"Pre-check audit failed: {a['error']}"}
    cur = next((c for c in a["controllers"] if c["controller"] == controller), None)
    if not cur:
        return {"error": f"No fiftypods quota found for controller '{controller}' in {env}"}
    if new_limit <= cur["used"]:
        return {"error": f"new_limit {new_limit} must exceed current usage ({cur['used']})"}
    if new_limit <= cur["hard"]:
        return {"error": f"new_limit {new_limit} must exceed the current limit ({cur['hard']})"}

    auth = _env_auth(env)
    ns = cur["namespace"]
    script = _GROOVY_SET.replace("__NS__", ns).replace("__LIMIT__", str(new_limit))
    try:
        raw = run_groovy_script(_cjoc_url(env), script, auth, timeout=45)
    except httpx.HTTPError as exc:
        return {"error": f"CJOC Script Console call failed: {exc}"}
    trace = _detect_groovy_trace(raw)
    if trace:
        return {"error": f"CJOC Groovy error: {trace}"}
    try:
        res = _last_json_line(raw)
    except (json.JSONDecodeError, IndexError) as exc:
        return {"error": f"Could not parse update result: {exc}"}
    if res.get("error"):
        return {"error": res["error"]}
    return {"env": env, "controller": controller, "namespace": ns, "error": None,
            "previous_hard": cur["hard"], "hard": int(res.get("hard") or new_limit),
            "used": int(res.get("used") or cur["used"])}


def abort_build(env: str, controller: str, job: str, number: int) -> dict:
    """Abort one running build on a controller to free its agent pod(s)."""
    if env not in ENVS:
        return {"error": f"Unknown environment '{env}'"}
    auth = _env_auth(env)
    if not auth:
        return {"error": f"No Jenkins credentials configured for {env}"}
    # Job full names contain no newlines; guard the placeholder swap.
    safe_job = (job or "").replace('"', '')
    script = _GROOVY_ABORT.replace("__JOB__", safe_job).replace("__NUM__", str(int(number)))
    try:
        raw = run_groovy_script(_controller_url(env, controller), script, auth, timeout=30)
    except httpx.HTTPError as exc:
        return {"error": f"Controller Script Console call failed: {exc}"}
    trace = _detect_groovy_trace(raw)
    if trace:
        return {"error": f"Controller Groovy error: {trace}"}
    result = raw.strip().splitlines()[-1] if raw.strip() else ""
    ok = result == "ABORTED"
    return {"env": env, "controller": controller, "job": job, "number": number,
            "aborted": ok, "result": result,
            "error": None if ok else f"Abort did not complete: {result or 'no output'}"}


def abort_all_builds(env: str, controller: str, older_than_days: int = 0) -> dict:
    """Abort running builds on a controller (bulk). older_than_days=0 aborts all;
    otherwise only builds running longer than that many days."""
    if env not in ENVS:
        return {"error": f"Unknown environment '{env}'"}
    auth = _env_auth(env)
    if not auth:
        return {"error": f"No Jenkins credentials configured for {env}"}
    try:
        days = max(0, int(older_than_days))
    except (TypeError, ValueError):
        days = 0
    min_ms = days * 86_400_000
    script = _GROOVY_ABORT_ALL.replace("__MIN_MS__", str(min_ms))
    try:
        raw = run_groovy_script(_controller_url(env, controller), script, auth, timeout=90)
    except httpx.HTTPError as exc:
        return {"error": f"Controller Script Console call failed: {exc}"}
    trace = _detect_groovy_trace(raw)
    if trace:
        return {"error": f"Controller Groovy error: {trace}"}
    line = raw.strip().splitlines()[-1] if raw.strip() else ""
    aborted = failed = 0
    for tok in line.split():
        if tok.startswith("ABORTED="):
            try: aborted = int(tok.split("=", 1)[1])
            except ValueError: pass
        elif tok.startswith("FAILED="):
            try: failed = int(tok.split("=", 1)[1])
            except ValueError: pass
    return {"env": env, "controller": controller, "older_than_days": days,
            "aborted": aborted, "failed": failed, "error": None}
