"""
CBJ podTemplate configuration sweep (DMSC-479, prod-east only).

Unlike CloudWatch-based CBJ Resource Analysis, which only shows a container's
Reserved/Limit if it has run recently, this reads the *configured* CPU,
memory, AND ephemeral-storage request/limit straight from what actually got
submitted to Kubernetes for each job's last build — so infrequently-run jobs
still show up.

Confirmed against real prod-east data before building this out:
- Primary source: the Kubernetes plugin logs the fully-RESOLVED pod YAML to
  every build's console output ("Agent ... is provisioned from template ...",
  then "---", then real apiVersion/kind/metadata/spec YAML, ending at the
  first blank line before "Running on ..."). This is MORE accurate than
  parsing the job's own script (Replay), and works regardless of where the
  config came from — inline script, shared library, even the static Cloud
  config — since it reflects what was actually submitted, not the source
  that built it.
- CONFIRMED real gap this closes: a job that delegates its whole pod
  definition to a *trusted* shared library call (`@Library(...) _` at global
  scope) is structurally invisible to Replay — Jenkins only includes
  untrusted/folder-scoped libraries in getOriginalLoadedScripts(). Verified
  directly: a real 16-core container CloudWatch reported was traced (via the
  actual pod name CloudWatch reports) to exactly this pattern — Replay showed
  nothing, the console log showed the full resolved YAML. On the one
  controller sampled, 17 of 33 jobs (52%) hit this pattern.
- Fallback: only when a build's console log has no provisioning block at all
  (e.g. build failed before provisioning, or reused a warm agent) do we fall
  back to Replay script text (podTemplate(yaml:...) or the flatter
  containerTemplate(...) DSL args), same heuristic parsing as before.
- Even the fallback path is not a complete source of truth on its own:
  CloudWatch remains the ground truth for what's actually running; this tool
  adds configured-intent visibility for jobs CloudWatch's lookback window
  misses. Nothing here is exact — text-parsing is inherently heuristic where
  it applies. Anything we can't confidently attribute is flagged explicitly
  (jobs_library_delegated / jobs_unresolved), never silently dropped.

Flow:
  1. list_controllers()      -> every ManagedMaster name on CJOC (196 on
                                 prod-east as of this writing).
  2. sweep_controller(name)  -> per-controller: enumerate Pipeline jobs, pull
                                 each one's last-build console log (primary)
                                 or Replay script (fallback), parse out
                                 container resource fields, dedup jobs that
                                 share the identical podTemplate.
  3. sweep_all()             -> sweep every controller, with light
                                 concurrency, and cache the result to disk
                                 (this is a slow, occasional pull — not a
                                 live per-page-load fetch like CloudWatch).
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import httpx
import yaml

from app.config import get_settings
from app.services.jenkins import run_groovy_script

logger = logging.getLogger(__name__)

CACHE_PATH = Path(__file__).resolve().parents[2] / "data" / "cbj_podtemplate_sweep.json"
SWEEP_CONCURRENCY = 6


# ─── Auth / controller URLs (mirrors copy_controller.py / pvc_cleanup.py) ───

def _prod_auth() -> tuple[str, str] | None:
    s = get_settings()
    token = s.JENKINS_EAST_PROD_TOKEN or s.JENKINS_TOKEN
    return (s.JENKINS_PROD_USER, token) if token else None


def _strip_cjoc(url: str) -> str:
    return url[: -len("/cjoc")] if url.rstrip("/").endswith("/cjoc") else url.rstrip("/")


def _cjoc_url() -> str:
    return f"{_strip_cjoc(get_settings().CLOUDBEES_EAST_PROD_URL)}/cjoc"


def _controller_url(controller: str) -> str:
    # CJOC's registered ManagedMaster.name is occasionally uppercase (e.g.
    # "MDP") even though the controller's real URL slug is lowercase
    # (confirmed via ManagedMaster.getEndpoint() — "mdp", not "MDP"; the
    # uppercase name 404s). Every other controller's name already matches
    # its lowercase URL, so lowercasing here is safe cluster-wide.
    return f"{_strip_cjoc(get_settings().CLOUDBEES_EAST_PROD_URL)}/{controller.lower()}"


def _detect_groovy_trace(out: str) -> str | None:
    if "Exception" in out and ("at " in out or "Script1.groovy" in out):
        first = out.splitlines()[0] if out.splitlines() else "Groovy error"
        return first[:200]
    return None


# ─── Step 1: enumerate controllers ──────────────────────────────────────────

_GROOVY_LIST_CONTROLLERS = r"""
import com.cloudbees.opscenter.server.model.ManagedMaster
import groovy.json.JsonOutput
def names = Jenkins.instance.getAllItems(ManagedMaster).collect { it.name }.sort()
println JsonOutput.toJson(names)
"""


def list_controllers() -> dict:
    """Every controller name registered on CJOC (prod-east)."""
    auth = _prod_auth()
    if not auth:
        return {"controllers": [], "error": "No Jenkins prod-east credentials configured"}
    try:
        raw = run_groovy_script(_cjoc_url(), _GROOVY_LIST_CONTROLLERS, auth, timeout=30)
    except httpx.HTTPError as exc:
        return {"controllers": [], "error": f"CJOC Script Console call failed: {exc}"}

    trace = _detect_groovy_trace(raw)
    if trace:
        return {"controllers": [], "error": f"CJOC Groovy error: {trace}"}
    try:
        names = json.loads(raw.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError) as exc:
        return {"controllers": [], "error": f"Could not parse controller list: {exc}", "raw": raw[:500]}
    return {"controllers": names, "error": None}


# ─── Step 2: per-controller job pull — console-log resolved pod YAML first ──
#
# Enumerates every buildable job type (hudson.model.Job) — Pipeline,
# Multibranch Pipeline branches, AND Freestyle — not just Pipeline. Freestyle
# jobs have no Replay (ReplayAction is Pipeline-only), so they rely entirely
# on the console-log path; that's fine since the Kubernetes plugin logs the
# same resolved-pod-YAML block regardless of job type.
#
# For each job: try the console log's resolved pod YAML first (accurate,
# source-agnostic — see module docstring). Only fall back to Replay script
# text if the log has no provisioning block at all. A job hitting neither,
# but using @Library, is flagged explicitly rather than silently dropped.
_GROOVY_CONTROLLER_SWEEP = r"""
import hudson.model.Job
import org.jenkinsci.plugins.workflow.cps.replay.ReplayAction
import groovy.json.JsonOutput

def jobs = Jenkins.get().getAllItems(Job)
def podYamlCandidates = []
def replayCandidates = []
def libraryDelegatedNoLog = []
int noBuild = 0
int noReplay = 0
int MAX_LOG_LINES = 4000

jobs.each { job ->
  def b = job.getLastBuild()
  if (b == null) { noBuild++; return }

  def blocks = []
  try {
    def reader = new BufferedReader(b.getLogReader())
    try {
      def buffer = []
      boolean collecting = false
      boolean sawDashes = false
      int linesRead = 0
      String line
      while (linesRead < MAX_LOG_LINES && (line = reader.readLine()) != null) {
        linesRead++
        if (!collecting) {
          if (line.contains("is provisioned from template")) {
            collecting = true
            sawDashes = false
            buffer = []
          }
          continue
        }
        if (!sawDashes) {
          if (line.trim() == "---") { sawDashes = true }
          continue
        }
        if (line.trim().isEmpty()) {
          if (buffer) { blocks << buffer.join("\n") }
          collecting = false
          continue
        }
        buffer << line
      }
      if (collecting && buffer) { blocks << buffer.join("\n") }
    } finally {
      reader.close()
    }
  } catch (Throwable ignored) {}

  if (blocks) {
    podYamlCandidates << [job: job.fullName, buildNumber: b.number, blocks: blocks]
    return
  }

  def replay = b.getAction(ReplayAction.class)
  if (replay == null || !replay.isEnabled()) { noReplay++; return }
  def mainScript = replay.getOriginalScript() ?: ""
  def loaded = replay.getOriginalLoadedScripts() ?: [:]
  def combined = mainScript
  loaded.values().each { combined += "\n" + it }
  if (combined.contains("podTemplate") || combined.contains("containerTemplate")) {
    replayCandidates << [job: job.fullName, buildNumber: b.number, script: combined]
  } else if (mainScript.contains("@Library")) {
    // Confirmed real gap, not theoretical: a trusted shared library's source is
    // NOT included in getOriginalLoadedScripts(), and its console log (this
    // build) had no provisioning block either (build likely failed early, or
    // reused a warm agent) — flag explicitly rather than silently dropping.
    libraryDelegatedNoLog << job.fullName
  }
}
println JsonOutput.toJson([
  totalJobs: jobs.size(), noBuild: noBuild, noReplay: noReplay,
  podYamlCandidates: podYamlCandidates, replayCandidates: replayCandidates,
  libraryDelegatedNoLog: libraryDelegatedNoLog,
])
"""


def _fetch_controller_scripts(controller: str) -> dict:
    auth = _prod_auth()
    if not auth:
        return {"error": "No Jenkins prod-east credentials configured"}
    try:
        raw = run_groovy_script(_controller_url(controller), _GROOVY_CONTROLLER_SWEEP, auth, timeout=90)
    except httpx.HTTPError as exc:
        return {"error": f"Script Console call failed: {exc}"}

    # Try JSON first: this script's payload is raw pipeline script text, which
    # legitimately contains words like "Exception" and "at " constantly, so
    # the Exception/"at "-substring trace heuristic (fine for small status
    # JSON elsewhere in this app) false-positives on real script content here.
    # Only fall back to it if the output isn't valid JSON at all.
    try:
        return json.loads(raw.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        pass

    trace = _detect_groovy_trace(raw)
    if trace:
        return {"error": f"Controller Groovy error: {trace}"}
    return {"error": "Could not parse controller output (not valid JSON)", "raw": raw[:500]}


# ─── Step 3: parse container resource fields out of raw YAML / script text ─

_YAML_BLOCK_RE = re.compile(r'"""(.*?)"""|\'\'\'(.*?)\'\'\'', re.DOTALL)
_CONTAINER_TEMPLATE_RE = re.compile(r"containerTemplate\(([^()]*(?:\([^()]*\)[^()]*)*)\)")


def _rows_from_containers(containers: list, source: str) -> list[dict]:
    """Shared extraction: given a parsed spec.containers list (from either a
    console-log pod YAML or an embedded Replay yaml: block), pull name + CPU/
    memory/ephemeral-storage request/limit out of each container."""
    rows: list[dict] = []
    for c in containers:
        if not isinstance(c, dict):
            continue
        name = c.get("name")
        res = c.get("resources") or {}
        req = res.get("requests") or {}
        lim = res.get("limits") or {}
        if not name and not req and not lim:
            continue
        rows.append({
            "container": name,
            "cpu_request": req.get("cpu"),
            "cpu_limit": lim.get("cpu"),
            "mem_request": req.get("memory"),
            "mem_limit": lim.get("memory"),
            "ephemeral_request": req.get("ephemeral-storage"),
            "ephemeral_limit": lim.get("ephemeral-storage"),
            "source": source,
        })
    return rows


def _parse_pod_yaml_doc(text: str) -> list[dict]:
    """Parse a clean, complete pod YAML document — the console-log block
    (already isolated by the Groovy sweep: everything between "---" and the
    next blank line). This is the primary, most accurate source."""
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError:
        return []
    if not isinstance(doc, dict):
        return []
    spec = doc.get("spec") if "spec" in doc else doc
    if not isinstance(spec, dict):
        return []
    containers = spec.get("containers")
    if not isinstance(containers, list):
        return []
    return _rows_from_containers(containers, "console-log")


def _clean_yaml_indent(block: str) -> str:
    """Groovy triple-quoted YAML is usually indented to match the source
    code; yaml.safe_load tolerates a consistent extra indent fine, but a
    ragged one (mixed indentation from string concatenation) does not, so
    dedent to the block's minimum indentation first."""
    lines = [l for l in block.splitlines() if l.strip()]
    if not lines:
        return block
    min_indent = min(len(l) - len(l.lstrip()) for l in lines)
    return "\n".join(l[min_indent:] if len(l) >= min_indent else l for l in block.splitlines())


def _parse_replay_yaml_blocks(script: str) -> list[dict]:
    """Fallback: find triple-quoted blocks in a Replay script that look like
    a k8s Pod spec (podTemplate(yaml: \"\"\"...\"\"\") style) and pull
    resources out of each."""
    rows: list[dict] = []
    for m in _YAML_BLOCK_RE.finditer(script):
        block = m.group(1) or m.group(2) or ""
        if "containers:" not in block or ("apiVersion" not in block and "kind:" not in block and "spec:" not in block):
            continue
        try:
            doc = yaml.safe_load(_clean_yaml_indent(block))
        except yaml.YAMLError:
            continue
        if not isinstance(doc, dict):
            continue
        spec = doc.get("spec") if "spec" in doc else doc
        if not isinstance(spec, dict):
            continue
        containers = spec.get("containers")
        if not isinstance(containers, list):
            continue
        rows.extend(_rows_from_containers(containers, "replay-yaml"))
    return rows


def _parse_container_template_dsl(script: str) -> list[dict]:
    """Fallback for the flatter `containerTemplate(name:..., resourceRequestCpu:...)`
    DSL style, when there's no embedded YAML block."""
    rows: list[dict] = []
    for m in _CONTAINER_TEMPLATE_RE.finditer(script):
        args = m.group(1)

        def field(key: str) -> str | None:
            fm = re.search(rf"{key}\s*:\s*['\"]([^'\"]+)['\"]", args)
            return fm.group(1) if fm else None

        name = field("name")
        cpu_req = field("resourceRequestCpu")
        cpu_lim = field("resourceLimitCpu")
        mem_req = field("resourceRequestMemory")
        mem_lim = field("resourceLimitMemory")
        eph_req = field("resourceRequestEphemeralStorage")
        eph_lim = field("resourceLimitEphemeralStorage")
        if not any([cpu_req, cpu_lim, mem_req, mem_lim, eph_req, eph_lim]):
            continue
        rows.append({
            "container": name,
            "cpu_request": cpu_req,
            "cpu_limit": cpu_lim,
            "mem_request": mem_req,
            "mem_limit": mem_lim,
            "ephemeral_request": eph_req,
            "ephemeral_limit": eph_lim,
            "source": "containerTemplate-dsl",
        })
    return rows


def _parse_replay_script(script: str) -> list[dict]:
    rows = _parse_replay_yaml_blocks(script)
    if not rows:
        rows = _parse_container_template_dsl(script)
    return rows


# ─── Step 4: dedup shared podTemplates within a controller ─────────────────

def _fingerprint(row: dict) -> tuple:
    return (row.get("container"), row.get("cpu_request"), row.get("cpu_limit"),
            row.get("mem_request"), row.get("mem_limit"),
            row.get("ephemeral_request"), row.get("ephemeral_limit"))


def _jenkins_build_url(controller: str, job_full_name: str, build_number: int | None) -> str | None:
    """https://jenkins-east.cloud.cms.gov/<controller>/job/a/job/b/job/c/<N>/console
    — matches the buildUrl Jenkins itself logs (confirmed against real console
    output), so this is a real, clickable link to the exact evidence."""
    if build_number is None:
        return None
    segments = "/".join(f"job/{part}" for part in job_full_name.split("/") if part)
    base = _strip_cjoc(get_settings().CLOUDBEES_EAST_PROD_URL)
    return f"{base}/{controller}/{segments}/{build_number}/console"


def _dedup_rows(job_rows: list[tuple[str, int | None, dict]], controller: str) -> list[dict]:
    """job_rows: list of (job_name, build_number, container_row). Groups
    identical configs (same container name + same request/limit) across jobs
    on one controller, since a shared library or copy-pasted podTemplate can
    back many jobs. Each job entry in the group carries a direct link to the
    exact build console output the numbers were read from."""
    groups: dict[tuple, dict] = {}
    for job_name, build_number, row in job_rows:
        fp = _fingerprint(row)
        if fp not in groups:
            groups[fp] = {**row, "jobs": []}
        groups[fp]["jobs"].append({
            "job": job_name,
            "build": build_number,
            "url": _jenkins_build_url(controller, job_name, build_number),
        })
    out = list(groups.values())
    for g in out:
        g["job_count"] = len(g["jobs"])
    out.sort(key=lambda g: g["job_count"], reverse=True)
    return out


# ─── Public: sweep one controller / all controllers ─────────────────────────

def sweep_controller(controller: str) -> dict:
    data = _fetch_controller_scripts(controller)
    if data.get("error"):
        return {"controller": controller, "error": data["error"], "containers": []}

    job_rows: list[tuple[str, int | None, dict]] = []
    unresolved_jobs: list[str] = []

    for cand in data.get("podYamlCandidates", []):
        job_name = cand.get("job")
        build_number = cand.get("buildNumber")
        rows: list[dict] = []
        for block in cand.get("blocks", []):
            rows.extend(_parse_pod_yaml_doc(block))
        if not rows:
            unresolved_jobs.append(job_name)
            continue
        for r in rows:
            job_rows.append((job_name, build_number, r))

    for cand in data.get("replayCandidates", []):
        job_name = cand.get("job")
        build_number = cand.get("buildNumber")
        rows = _parse_replay_script(cand.get("script") or "")
        if not rows:
            unresolved_jobs.append(job_name)
            continue
        for r in rows:
            job_rows.append((job_name, build_number, r))

    containers = _dedup_rows(job_rows, controller)
    return {
        "controller": controller,
        "error": None,
        "total_jobs": data.get("totalJobs", 0),
        "jobs_no_build": data.get("noBuild", 0),
        "jobs_no_replay": data.get("noReplay", 0),
        "jobs_library_delegated": data.get("libraryDelegatedNoLog", []),
        "jobs_with_podtemplate": len({j for j, _, _ in job_rows}),
        "jobs_unresolved": unresolved_jobs,
        "containers": containers,
    }


def sweep_all(controllers: list[str] | None = None, on_progress=None) -> dict:
    """Sweep every controller with light concurrency. Individual controller
    failures do not abort the run — they're recorded per-controller."""
    if controllers is None:
        listed = list_controllers()
        if listed.get("error"):
            return {"error": listed["error"], "results": [], "swept_at": None}
        controllers = listed["controllers"]

    results: list[dict] = []
    done = 0
    total = len(controllers)
    with ThreadPoolExecutor(max_workers=SWEEP_CONCURRENCY) as pool:
        futures = {pool.submit(sweep_controller, c): c for c in controllers}
        for fut in as_completed(futures):
            controller = futures[fut]
            try:
                results.append(fut.result())
            except Exception as exc:  # noqa: BLE001 - keep sweeping other controllers
                results.append({"controller": controller, "error": str(exc), "containers": []})
            done += 1
            if on_progress:
                on_progress(done, total, controller)

    results.sort(key=lambda r: r["controller"])
    payload = {
        "error": None,
        "swept_at": int(time.time()),
        "controller_count": total,
        "results": results,
    }
    return payload


def save_cache(payload: dict) -> None:
    # Atomic write: a concurrent load_cache() during a sweep-completion write
    # must never see a half-written file. Write to a temp file in the same dir,
    # then os.replace() (atomic rename on the same filesystem).
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = CACHE_PATH.with_suffix(CACHE_PATH.suffix + f".tmp.{os.getpid()}")
    tmp.write_text(json.dumps(payload))
    os.replace(tmp, CACHE_PATH)


_SWEEP_STATE = {"running": False, "done": 0, "total": 0, "started_at": None, "last_error": None}
_sweep_lock = threading.Lock()


def sweep_status() -> dict:
    return dict(_SWEEP_STATE)


def start_background_sweep() -> dict:
    """Kick off sweep_all() on a background thread and return immediately.
    Refuses to start a second sweep while one is already running (196
    controllers takes real time and real load against prod-east)."""
    with _sweep_lock:
        if _SWEEP_STATE["running"]:
            return {"started": False, "already_running": True}
        _SWEEP_STATE.update(running=True, done=0, total=0, started_at=int(time.time()), last_error=None)

    def _worker():
        def progress(done, total, controller):
            _SWEEP_STATE.update(done=done, total=total)

        try:
            result = sweep_all(on_progress=progress)
            if result.get("error"):
                _SWEEP_STATE["last_error"] = result["error"]
            else:
                save_cache(result)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Background podTemplate sweep failed")
            _SWEEP_STATE["last_error"] = str(exc)
        finally:
            _SWEEP_STATE["running"] = False

    threading.Thread(target=_worker, daemon=True).start()
    return {"started": True, "already_running": False}


def load_cache() -> dict | None:
    if not CACHE_PATH.exists():
        return None
    try:
        return json.loads(CACHE_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return None


# ─── CloudWatch cross-validation join ───────────────────────────────────────
#
# Join podTemplate config rows against live CloudWatch actual-usage data, on
# namespace(=cbc-<controller>) + container name — confirmed to match exactly
# via a live test (cbc-qnod's terragrunt/ess-build/etc all matched byte-for-
# byte). Done live at read time, NOT baked into the sweep cache, so "actually
# used" numbers stay fresh independent of when the slow podTemplate sweep
# last ran — same live-fetch-on-read convention as CbjResourceAnalysisWidget.
# A row with no CloudWatch match just means that container hasn't run in
# CloudWatch's lookback window — exactly the case this tool exists to catch,
# not an error.
async def join_cloudwatch_usage(sweep: dict) -> dict:
    from app.services.cbj_resource_analysis import get_cbj_resource_analysis
    from app.services.pvc_cleanup import _controller_from_namespace

    try:
        cw_rows = await get_cbj_resource_analysis("prod-east", "agents")
    except Exception as exc:  # noqa: BLE001 - degrade to config-only, don't fail the page
        logger.warning("CloudWatch join failed, showing podTemplate config only: %s", exc)
        cw_rows = []

    lookup: dict[tuple[str, str], dict] = {}
    for row in cw_rows:
        key = (_controller_from_namespace(row.get("namespace", "")), row.get("container"))
        lookup[key] = row

    for controller_result in sweep.get("results", []):
        controller = controller_result.get("controller")
        for c in controller_result.get("containers", []):
            cw = lookup.get((controller, c.get("container")))
            c["cw_cpu_used_at_peak_cores"] = cw.get("cpu_used_at_peak_cores") if cw else None
            c["cw_mem_used_at_peak_gb"] = cw.get("mem_used_at_peak_gb") if cw else None
            c["cw_status"] = cw.get("status") if cw else None

    sweep["cloudwatch_joined_at"] = int(time.time())
    return sweep
