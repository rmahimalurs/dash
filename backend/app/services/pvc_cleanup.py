"""
Controller PVC cleanup (CloudBees Jenkins, prod-east).

Backs the dashboard tile that remediates the long-running Datadog alert
`283161` ([Kubernetes] Jenkins https://jenkins-east.cloud.cms.gov Controllers
PVC Usage), which fires per-namespace when a controller's
`kubelet.volume.stats.used_bytes / capacity_bytes > 0.80` on cluster
`jenkins-prod-east`.

Flow:
  1. list_controllers()   -> namespaces at/over warn (75%) and crit (80%),
                             read straight from Datadog (mirrors the monitor).
  2. controller_usage(c)  -> what is filling JENKINS_HOME (cloudbees-disk-usage-
                             simple plugin), the controller's admins + emails,
                             each resolved to a Slack @handle, and a ready-to-
                             send message for the ADO to sign off on.
  3. prune(c, ...)        -> ADO-gated, dry-run-by-default deletion of the
                             selected categories via the Script Console.

Nothing is deleted until an ADO has approved and the engineer confirms it.
"""
import json
import logging

import httpx

from app.config import get_settings
from app.services import slack_directory
from app.services.jenkins import run_groovy_script
from app.services.copy_controller import (
    _detect_groovy_trace,
    _prod_auth,
    _prod_controller_url,
    discover_admins,
)

logger = logging.getLogger(__name__)

# Categories the prune step understands. Order = suggested cleanup order
# (cheapest/safest first). `builds` keeps the most recent N per job.
PRUNE_CATEGORIES = ("tmp", "caches", "workspaces", "builds", "logs")
DEFAULT_KEEP_BUILDS = 10


# ─── Controller list via Datadog (mirrors monitor 283161) ──────────────────

def _dd_headers() -> dict:
    s = get_settings()
    return {
        "DD-API-KEY": s.DATADOG_API_KEY,
        "DD-APPLICATION-KEY": s.DATADOG_APP_KEY,
    }


def _namespace_from_group(group_name: str) -> str | None:
    """'namespace:cbc-acoms' -> 'cbc-acoms'. Handles multi-tag group names too."""
    for part in group_name.split(","):
        part = part.strip()
        if part.startswith("namespace:"):
            return part.split(":", 1)[1]
    return None


def _controller_from_namespace(ns: str) -> str:
    """cbc-acoms -> acoms; cjoc stays cjoc. Controller name is the Script Console path segment."""
    return ns[len("cbc-"):] if ns.startswith("cbc-") else ns


def list_controllers() -> dict:
    """
    Return controllers whose PVC usage is at/over threshold, split into `over`
    (monitor group in Alert, >= crit) and `approaching` (in Warn, >= warn).

    Read from the existing per-namespace Datadog monitor (group states) rather
    than a raw timeseries query — the dashboard's app key has `monitors_read`
    but not `timeseries_query`. The monitor gives status per namespace, not a
    numeric %; the exact % + breakdown come from controller_usage() on click.
    """
    s = get_settings()
    if not (s.DATADOG_API_KEY and s.DATADOG_APP_KEY):
        return {"over": [], "approaching": [], "error": "Datadog API keys are not configured"}

    url = f"{s.DATADOG_API_BASE.rstrip('/')}/api/v1/monitor/{s.PVC_MONITOR_ID}"
    try:
        with httpx.Client(timeout=20) as client:
            resp = client.get(url, params={"group_states": "all"}, headers=_dd_headers())
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code
        hint = " (app key may lack monitors_read)" if code == 403 else ""
        return {"over": [], "approaching": [], "error": f"Datadog monitor read failed: HTTP {code}{hint}"}
    except httpx.RequestError as exc:
        return {"over": [], "approaching": [], "error": f"Datadog request error: {exc}"}

    groups = (resp.json().get("state", {}) or {}).get("groups", {}) or {}
    over, approaching = [], []
    for name, g in groups.items():
        ns = _namespace_from_group(name)
        if not ns:
            continue
        mon_status = g.get("status")  # Alert | Warn | OK | No Data
        if mon_status == "Alert":
            bucket, st = over, "crit"
        elif mon_status == "Warn":
            bucket, st = approaching, "warn"
        else:
            continue  # OK / No Data (e.g. a deleted PVC) are not actionable
        bucket.append({
            "namespace": ns,
            "controller": _controller_from_namespace(ns),
            "status": st,
            "monitor_status": mon_status,
            "last_triggered_ts": g.get("last_triggered_ts"),
        })

    over.sort(key=lambda x: x["controller"])
    approaching.sort(key=lambda x: x["controller"])
    return {
        "over": over,
        "approaching": approaching,
        "error": None,
        "thresholds": {"warn": s.PVC_WARN_THRESHOLD, "crit": s.PVC_CRIT_THRESHOLD},
        "cluster": s.PVC_CLEANUP_CLUSTER,
        "monitor_id": s.PVC_MONITOR_ID,
    }


# ─── Per-controller usage breakdown + ADO discovery ────────────────────────

# Runs on a single controller's Script Console. Returns a JSON blob with the
# JENKINS_HOME disk breakdown (from cloudbees-disk-usage-simple, cached) plus
# email addresses for the admin SIDs we pass in. Values from the plugin are in
# kibibytes (KiB).
_GROOVY_USAGE = r"""
import groovy.json.JsonOutput
import jenkins.model.Jenkins
import hudson.model.User
import hudson.tasks.Mailer

def j = Jenkins.get()
def root = j.getRootDir()
def out = [:]
out.jenkinsHome = root.getAbsolutePath()
out.totalSpace = root.getTotalSpace()
out.freeSpace = root.getUsableSpace()

def dirs = []
def jobs = []
try {
  def plugin = j.getPlugin("cloudbees-disk-usage-simple")
  if (plugin != null) {
    plugin.getDirectoriesUsages().each { d ->
      dirs << [name: (d.displayName ?: (d.path ? d.path.toString() : "?")), kib: d.usage]
    }
    plugin.getJobsUsages().each { ji ->
      jobs << [name: ji.fullName, kib: ji.usage]
    }
    out.diskUsageSource = "plugin"
  } else {
    out.diskUsageSource = "missing"
  }
} catch (Throwable t) {
  out.diskUsageSource = "error"
  out.diskUsageError = t.toString()
}
out.directories = dirs
out.jobs = jobs.sort { -it.kib }.take(25)

def adminSids = "__SIDS__".split(",").findAll { it }
def admins = []
adminSids.each { sid ->
  def email = null
  try {
    def u = User.getById(sid, false)
    if (u != null) {
      def p = u.getProperty(Mailer.UserProperty.class)
      if (p != null) email = p.getAddress()
    }
  } catch (Throwable ignored) {}
  admins << [sid: sid, email: email]
}
out.admins = admins
println JsonOutput.toJson(out)
"""


def _kib_to_bytes(kib) -> int:
    try:
        return int(kib) * 1024
    except (TypeError, ValueError):
        return 0


# Map a disk-usage plugin directory basename to a cleanable category. The plugin
# reports display names like "JENKINS_HOME/jobs" and "java.io.tmpdir", so we
# match on the last path segment (plus a tmp special-case), not the whole string.
_DIR_CATEGORY = {
    "caches": "caches",
    "workspace": "workspaces",
    "jobs": "builds",     # build history lives under jobs/*/builds
    "builds": "builds",
    "logs": "logs",
}


def _dir_to_category(name: str) -> str | None:
    n = (name or "").strip().lower()
    if "tmpdir" in n or n.rsplit("/", 1)[-1] == "tmp":
        return "tmp"
    return _DIR_CATEGORY.get(n.rsplit("/", 1)[-1])


def _suggest_categories(directories: list[dict]) -> list[dict]:
    """Map plugin directory sizes to cleanable categories, largest first."""
    agg: dict[str, int] = {}
    for d in directories:
        cat = _dir_to_category(d.get("name") or "")
        if cat:
            agg[cat] = agg.get(cat, 0) + _kib_to_bytes(d.get("kib"))
    suggestions = [
        {"category": cat, "bytes": b, "cleanable": True}
        for cat, b in agg.items()
    ]
    suggestions.sort(key=lambda x: x["bytes"], reverse=True)
    return suggestions


def _greeting(names: list[str]) -> str:
    """'Hi,' / 'Hi Alice,' / 'Hi Alice and Bob,' / 'Hi Alice, Bob, and Carol,'."""
    names = [n for n in dict.fromkeys(n for n in names if n)]  # de-dupe, keep order
    if not names:
        return "Hi,"
    if len(names) == 1:
        return f"Hi {names[0]},"
    if len(names) == 2:
        return f"Hi {names[0]} and {names[1]},"
    return f"Hi {', '.join(names[:-1])}, and {names[-1]},"


def _compose_ado_message(controller: str, pct: float, ado_names: list[str],
                         top: list[dict], categories: list[dict], engineer: str) -> str:
    """Build the copy-and-send Slack message the engineer sends to the ADOs for sign-off."""
    def _gb(n): return f"{n / 1024**3:.1f} GB"
    top_str = ", ".join(f"{t['name']} ({_gb(_kib_to_bytes(t.get('kib')))})" for t in top[:3]) or "n/a"
    cat_str = ", ".join(c["category"] for c in categories) or "old builds / workspaces / caches"
    greeting = _greeting(ado_names)
    return (
        f"{greeting}\n\n"
        f"The CloudBees Jenkins controller *{controller}* (prod-east) is at *{pct}%* disk usage on its "
        f"PVC and is {'over' if pct >= get_settings().PVC_CRIT_THRESHOLD * 100 else 'approaching'} the "
        f"alert threshold. Top consumers: {top_str}.\n\n"
        f"To free space we'd like to prune: {cat_str}. This won't affect running jobs. "
        f"Can you confirm it's OK to proceed?\n\n"
        f"Thanks,\n{engineer}"
    )


def controller_usage(controller: str, engineer: str = "") -> dict:
    """
    Return the disk breakdown for one controller, its admins resolved to Slack
    handles, suggested cleanup categories, and a ready-to-send ADO message.
    """
    auth = _prod_auth()
    if not auth:
        return {"error": "No Jenkins prod-east credentials configured"}

    # Reuse the battle-tested RBAC admin discovery, then resolve emails + disk usage
    # in one Script Console round-trip against the controller itself.
    admin_result = discover_admins(controller)
    sids = admin_result.get("admins", []) or []

    script = _GROOVY_USAGE.replace("__SIDS__", ",".join(sids))
    url = _prod_controller_url(controller)
    try:
        raw = run_groovy_script(url, script, auth, timeout=60)
    except httpx.HTTPError as exc:
        return {"error": f"Script Console call failed: {exc}"}

    trace = _detect_groovy_trace(raw)
    if trace:
        return {"error": f"Controller Groovy error: {trace}"}
    try:
        data = json.loads(raw.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError) as exc:
        return {"error": f"Could not parse usage output: {exc}", "raw": raw[:500]}

    directories = data.get("directories", [])
    suggestions = _suggest_categories(directories)
    top_jobs = data.get("jobs", [])

    # Resolve admins to Slack. Load the directory once and index by handle so we
    # can fall back from email to the EUA ID: CMS Slack handles ARE the user's EUA
    # ID, which is exactly the Jenkins SID — so contractors whose Jenkins email is
    # a vendor address (leidos.com, caci.com, ...) still resolve via @<sid>.
    directory = slack_directory.load_directory()
    handle_index: dict[str, dict] = {}
    for entry in directory.values():
        h = (entry.get("handle") or "").lower()
        if h and h not in handle_index:
            handle_index[h] = entry

    # AD deactivation status for every admin SID (SID == EUA == sAMAccountName).
    # Disabled accounts are excluded from ADO emails; 'unknown' (AD unreachable)
    # is treated as active so we never silently drop a real recipient.
    from app.services import ldap_accounts
    sids = [(a.get("sid") or "").strip() for a in data.get("admins", []) if a.get("sid")]
    ad_status = ldap_accounts.get_disabled_status(sids)

    admins = []
    for a in data.get("admins", []):
        sid = (a.get("sid") or "").strip()
        email = a.get("email")
        entry = directory.get(email.strip().lower()) if email else None
        matched_by = "email" if entry else None
        if not entry and sid:
            entry = handle_index.get(sid.lower())
            matched_by = "eua" if entry else None
        status = ad_status.get(sid.lower(), "unknown") if sid else "unknown"
        admins.append({
            "sid": sid,
            "email": email,
            "slack_handle": entry.get("handle") if entry else None,
            "slack_name": entry.get("name") if entry else None,
            "matched_by": matched_by,
            "ad_status": status,
            "deactivated": status == "disabled",
        })

    # Best-effort %used for the message (recompute from plugin totals if present)
    total = data.get("totalSpace") or 0
    free = data.get("freeSpace") or 0
    pct = round((total - free) / total * 100, 1) if total else 0.0

    # Greet ALL admins we could resolve to a real name (Slack directory). If none
    # resolved, greet generically ("Hi,") rather than exposing raw SIDs — the
    # engineer picks the ADO(s) from the list shown in the UI.
    ado_names = [a["slack_name"] for a in admins if a.get("slack_name")]
    message = _compose_ado_message(controller, pct, ado_names, top_jobs, suggestions, engineer or "the DevOps team")

    from app.services import email_notices
    return {
        "error": None,
        "controller": controller,
        "email_history": email_notices.history("pvc", controller),
        "jenkins_home": data.get("jenkinsHome"),
        "total_bytes": total,
        "free_bytes": free,
        "pct": pct,
        "disk_usage_source": data.get("diskUsageSource"),
        "disk_usage_error": data.get("diskUsageError"),
        "directories": [{"name": d.get("name"), "bytes": _kib_to_bytes(d.get("kib"))} for d in directories],
        "top_jobs": [{"name": t.get("name"), "bytes": _kib_to_bytes(t.get("kib"))} for t in top_jobs],
        "suggested_categories": suggestions,
        "admins": admins,
        "admin_discovery_error": admin_result.get("error"),
        "ado_message": message,
    }


# ─── ADO analysis email (CMS SMTP relay) ───────────────────────────────────

def _fmt_bytes(n) -> str:
    try:
        n = float(n or 0)
    except (TypeError, ValueError):
        return "0 B"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def _email_html(controller: str, usage: dict, ado_names: list[str], engineer: str) -> str:
    """Inline-styled HTML for the ADO sign-off email (email clients need inline CSS)."""
    pct = usage.get("pct", 0)
    crit = get_settings().PVC_CRIT_THRESHOLD * 100
    over_word = "over" if pct >= crit else "approaching"
    greeting = _greeting(ado_names)

    top_jobs = [j for j in (usage.get("top_jobs") or []) if j.get("bytes")][:10]
    top_rows = "".join(
        f'<tr>'
        f'<td style="padding:6px 10px;border-bottom:1px solid #eee;font-family:monospace;font-size:13px;color:#111">{_html_escape(j.get("name"))}</td>'
        f'<td style="padding:6px 10px;border-bottom:1px solid #eee;text-align:right;white-space:nowrap;color:#444">{_fmt_bytes(j.get("bytes"))}</td>'
        f'</tr>'
        for j in top_jobs
    ) or '<tr><td style="padding:6px 10px;color:#888" colspan="2">No per-job breakdown available.</td></tr>'

    cats = [c for c in (usage.get("suggested_categories") or []) if c.get("bytes")]
    cat_rows = "".join(
        f'<tr>'
        f'<td style="padding:6px 10px;border-bottom:1px solid #eee;color:#111">{_html_escape(c.get("category"))}</td>'
        f'<td style="padding:6px 10px;border-bottom:1px solid #eee;text-align:right;white-space:nowrap;color:#444">{_fmt_bytes(c.get("bytes"))}</td>'
        f'</tr>'
        for c in cats
    ) or '<tr><td style="padding:6px 10px;color:#888" colspan="2">Old builds / workspaces / caches.</td></tr>'

    total = usage.get("total_bytes") or 0
    free = usage.get("free_bytes") or 0
    used = total - free if total else 0
    pct_color = "#dc2626" if pct >= crit else "#d97706"

    return f"""\
<div style="font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:#1f2937;max-width:640px;margin:0 auto;padding:8px">
  <p style="font-size:15px;margin:0 0 14px">{_html_escape(greeting)}</p>

  <p style="font-size:14px;line-height:1.55;margin:0 0 16px">
    The CloudBees Jenkins controller <strong>{_html_escape(controller)}</strong> (prod-east) is at
    <strong style="color:{pct_color}">{pct}%</strong> disk usage on its PVC and is {over_word} the
    alert threshold (<span style="color:#6b7280">Datadog monitor 283161</span>). We'd like your sign-off to
    prune old data and reclaim space. <strong>This will not affect running jobs.</strong>
  </p>

  <table role="presentation" cellpadding="0" cellspacing="0" style="border-collapse:collapse;margin:0 0 18px">
    <tr>
      <td style="padding:4px 14px 4px 0;color:#6b7280;font-size:13px">Volume</td>
      <td style="padding:4px 0;font-size:13px;color:#111">{_fmt_bytes(used)} used of {_fmt_bytes(total)} &nbsp;·&nbsp; {_fmt_bytes(free)} free</td>
    </tr>
  </table>

  <h3 style="font-size:13px;text-transform:uppercase;letter-spacing:.04em;color:#374151;margin:0 0 6px">Top consumers</h3>
  <table role="presentation" cellpadding="0" cellspacing="0" style="border-collapse:collapse;width:100%;margin:0 0 20px;border:1px solid #eee">
    <thead><tr style="background:#f9fafb">
      <th style="padding:6px 10px;text-align:left;font-size:12px;color:#6b7280;border-bottom:1px solid #eee">Job / directory</th>
      <th style="padding:6px 10px;text-align:right;font-size:12px;color:#6b7280;border-bottom:1px solid #eee">Size</th>
    </tr></thead>
    <tbody>{top_rows}</tbody>
  </table>

  <h3 style="font-size:13px;text-transform:uppercase;letter-spacing:.04em;color:#374151;margin:0 0 6px">Proposed cleanup</h3>
  <table role="presentation" cellpadding="0" cellspacing="0" style="border-collapse:collapse;width:100%;margin:0 0 20px;border:1px solid #eee">
    <thead><tr style="background:#f9fafb">
      <th style="padding:6px 10px;text-align:left;font-size:12px;color:#6b7280;border-bottom:1px solid #eee">Category</th>
      <th style="padding:6px 10px;text-align:right;font-size:12px;color:#6b7280;border-bottom:1px solid #eee">Reclaimable</th>
    </tr></thead>
    <tbody>{cat_rows}</tbody>
  </table>

  <p style="font-size:14px;line-height:1.55;margin:0 0 18px">
    Old build history is pruned keeping the most recent builds per job; temp files, caches, and workspaces
    are regenerated on the next run. <strong>Please reply to confirm it's OK to proceed.</strong>
  </p>

  <p style="font-size:13px;color:#6b7280;margin:0;border-top:1px solid #eee;padding-top:12px">
    Sent by {_html_escape(engineer or "the CMS Cloud DevOps team")} via the DevOps Dashboard.
  </p>
</div>"""


def _html_escape(s) -> str:
    s = "" if s is None else str(s)
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
             .replace('"', "&quot;"))


def email_ado(controller: str, engineer: str = "") -> dict:
    """
    Email the controller's ADO admins a formatted disk-usage analysis + sign-off
    request via the CMS SMTP relay, cc'ing the DevOps distro. Reuses
    controller_usage() for the breakdown + email resolution.
    """
    from app.services import email_service  # local import avoids an import cycle
    from app.services import email_notices

    usage = controller_usage(controller, engineer)
    if usage.get("error"):
        return {"sent": False, "error": usage["error"]}

    admins = usage.get("admins") or []
    # Exclude AD-deactivated admins from the recipient list (keep 'unknown').
    active = [a for a in admins if not a.get("deactivated")]
    excluded = [a for a in admins if a.get("deactivated")]
    to = [a["email"] for a in active if a.get("email")]
    if not to:
        base = ("No ADO email addresses resolved for this controller"
                if not admins else
                "All resolved ADO admins are deactivated in AD")
        return {
            "sent": False,
            "error": f"{base} — cannot send email. Contact the ADO on Slack instead.",
            "excluded_deactivated": [
                {"sid": a["sid"], "email": a.get("email"), "name": a.get("slack_name")}
                for a in excluded
            ],
        }

    ado_names = [a["slack_name"] for a in active if a.get("slack_name")]
    pct = usage.get("pct", 0)
    # Escalating notice: 1st send plain, 2nd "[Second Notice]", 3rd+ "[Final Notice]".
    ordinal, prefix = email_notices.peek_next("pvc", controller)
    subject = f"{prefix}Action needed: prune Jenkins controller {controller} — {pct}% PVC usage (prod-east)"
    html = _email_html(controller, usage, ado_names, engineer)

    cc = get_settings().PVC_EMAIL_CC
    result = email_service.send_html_email(
        to=to, subject=subject, html_body=html,
        cc=[cc] if cc else None,
    )
    result["subject"] = subject
    result.setdefault("to", to)
    result["excluded_deactivated"] = [
        {"sid": a["sid"], "email": a.get("email"), "name": a.get("slack_name")}
        for a in excluded
    ]
    if result.get("sent"):
        email_notices.record("pvc", controller, to, engineer)
    result["notice_ordinal"] = ordinal
    result["email_history"] = email_notices.history("pvc", controller)
    return result


# ─── Prune (ADO-gated, async background task + poller) ──────────────────────
#
# A synchronous Script Console prune over a large JENKINS_HOME times the gateway
# out (~60s → 504). Instead, the START script writes a status marker file, spawns
# a background thread to do the work, and returns immediately; the STATUS script
# cheaply reads the marker so the dashboard can poll to completion.
#
# The marker lives at $JENKINS_HOME/.pvc-prune-status.json. Dry-run counts what
# WOULD be removed (deletes nothing); the real run deletes and reports freed
# space via a getUsableSpace() delta. `builds` keeps the most recent N per job.

MARKER = ".pvc-prune-status.json"
_HEARTBEAT_STALE_MS = 120000  # a "running" marker not updated in 2 min is stale

_GROOVY_PRUNE_START = r"""
import groovy.json.JsonOutput
import groovy.json.JsonSlurper
import jenkins.model.Jenkins
import hudson.model.Job
import org.springframework.security.core.context.SecurityContextHolder

def j = Jenkins.get()
def root = j.getRootDir()
def markerFile = new File(root, ".pvc-prune-status.json")
// A spawned Thread does NOT inherit the Script Console's authentication, so
// Jenkins.getAllItems(Job) would run as anonymous and see zero jobs (no Read).
// Capture the caller's security context and re-apply it inside the worker thread
// so job/build enumeration and deletion run with the invoking admin's rights.
def SAVED_CTX = SecurityContextHolder.getContext()

// Do not start a second run while one is genuinely in progress.
def alreadyRunning = false
if (markerFile.exists()) {
  try {
    def cur = new JsonSlurper().parseText(markerFile.getText("UTF-8"))
    if (cur?.state == "running" &&
        (System.currentTimeMillis() - ((cur.lastUpdate ?: 0L) as long) < 120000L)) {
      alreadyRunning = true
      println JsonOutput.toJson([state: "already_running", progress: cur.progress])
    }
  } catch (Throwable ignored) {}
}

if (!alreadyRunning) {
  def cats = "__CATS__".split(",").findAll { it } as Set
  def keep = __KEEP__
  def dryRun = __DRYRUN__

  def deleteTree
  deleteTree = { File f ->
    if (f == null || !f.exists()) return
    if (f.isDirectory()) f.listFiles()?.each { deleteTree(it) }
    f.delete()
  }

  def state = [
    state: "running", dryRun: dryRun, categories: (cats as List), keep: keep,
    startedAt: System.currentTimeMillis(), finishedAt: null,
    progress: [jobsProcessed: 0, totalJobs: 0, buildsDeleted: 0, filesCleared: 0],
    report: [:], freeBefore: root.getUsableSpace(), freeAfter: null,
    reclaimedBytes: null, error: null, lastUpdate: System.currentTimeMillis(),
  ]
  def writeMarker = {
    state.lastUpdate = System.currentTimeMillis()
    def tmp = new File(root, ".pvc-prune-status.json.tmp")
    tmp.setText(JsonOutput.toJson(state), "UTF-8")
    tmp.renameTo(markerFile)
  }
  writeMarker()  // marker exists before we return

  Thread.start {
    SecurityContextHolder.setContext(SAVED_CTX)  // run as the invoking admin
    try {
      def fsCats = [tmp: "tmp", caches: "caches", workspaces: "workspace", logs: "logs"]
      fsCats.each { cat, dirName ->
        if (!cats.contains(cat)) return
        def dir = new File(root, dirName)
        int items = 0
        if (dir.exists() && dir.isDirectory()) {
          dir.listFiles()?.each { child ->
            items++
            if (!dryRun) deleteTree(child)
          }
        }
        state.report[cat] = [items: items]
        state.progress.filesCleared = (state.progress.filesCleared ?: 0) + items
        writeMarker()
      }
      if (cats.contains("builds")) {
        def jobs = j.getAllItems(Job)
        state.progress.totalJobs = jobs.size()
        int deleted = 0
        int processed = 0
        jobs.each { job ->
          def idx = 0
          job.getBuilds().each { b ->
            idx++
            if (idx <= keep) return
            deleted++
            if (!dryRun) { try { b.delete() } catch (Throwable ignored) {} }
          }
          processed++
          if (processed % 100 == 0) {
            state.progress.jobsProcessed = processed
            state.progress.buildsDeleted = deleted
            writeMarker()
          }
        }
        state.progress.jobsProcessed = processed
        state.progress.buildsDeleted = deleted
        state.report["builds"] = [items: deleted, keep: keep]
      }
      state.freeAfter = root.getUsableSpace()
      state.reclaimedBytes = state.freeAfter - state.freeBefore
      state.state = "done"
      state.finishedAt = System.currentTimeMillis()
      writeMarker()
    } catch (Throwable t) {
      state.state = "error"
      state.error = t.toString()
      state.finishedAt = System.currentTimeMillis()
      writeMarker()
    }
  }
  println JsonOutput.toJson([state: "started", dryRun: dryRun])
}
"""

_GROOVY_PRUNE_STATUS = r"""
import groovy.json.JsonOutput
import groovy.json.JsonSlurper
import jenkins.model.Jenkins

def root = Jenkins.get().getRootDir()
def markerFile = new File(root, ".pvc-prune-status.json")
if (!markerFile.exists()) {
  println JsonOutput.toJson([state: "idle"])
} else {
  try {
    def cur = new JsonSlurper().parseText(markerFile.getText("UTF-8"))
    if (cur.state == "running" &&
        (System.currentTimeMillis() - ((cur.lastUpdate ?: 0L) as long) > 120000L)) {
      cur.stale = true
    }
    println JsonOutput.toJson(cur)
  } catch (Throwable t) {
    println JsonOutput.toJson([state: "error", error: "Could not read status: " + t.toString()])
  }
}
"""


def start_prune(controller: str, categories: list[str], ado_confirmed: bool,
                keep_builds: int = DEFAULT_KEEP_BUILDS, dry_run: bool = True) -> dict:
    """
    Kick off an async prune on a controller and return immediately. Poll
    prune_status() for progress/result. Refuses unless `ado_confirmed`; a real
    (non-dry-run) deletion additionally requires PVC_PRUNE_ENABLED.
    """
    if not ado_confirmed:
        return {"error": "ADO confirmation is required before pruning", "denied": True}

    # Hard kill switch — a real deletion is refused unless explicitly enabled.
    if not dry_run and not get_settings().PVC_PRUNE_ENABLED:
        return {
            "error": "Actual pruning is disabled (PVC_PRUNE_ENABLED is off). "
                     "Only dry-run preview is available.",
            "denied": True,
        }

    cats = [c for c in categories if c in PRUNE_CATEGORIES]
    if not cats:
        return {"error": f"No valid categories. Choose from: {', '.join(PRUNE_CATEGORIES)}"}

    auth = _prod_auth()
    if not auth:
        return {"error": "No Jenkins prod-east credentials configured"}

    script = (
        _GROOVY_PRUNE_START
        .replace("__CATS__", ",".join(cats))
        .replace("__KEEP__", str(int(keep_builds)))
        .replace("__DRYRUN__", "true" if dry_run else "false")
    )
    url = _prod_controller_url(controller)
    try:
        raw = run_groovy_script(url, script, auth, timeout=30)  # returns immediately
    except httpx.HTTPError as exc:
        return {"error": f"Prune start failed: {exc}"}

    trace = _detect_groovy_trace(raw)
    if trace:
        return {"error": f"Controller Groovy error: {trace}"}
    try:
        result = json.loads(raw.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError) as exc:
        return {"error": f"Could not parse prune-start output: {exc}", "raw": raw[:500]}

    result["controller"] = controller
    result["categories"] = cats
    result["dry_run"] = dry_run
    result["error"] = None
    return result


def prune_status(controller: str) -> dict:
    """Read the current prune status marker on a controller (fast, read-only)."""
    auth = _prod_auth()
    if not auth:
        return {"error": "No Jenkins prod-east credentials configured"}
    url = _prod_controller_url(controller)
    try:
        raw = run_groovy_script(url, _GROOVY_PRUNE_STATUS, auth, timeout=30)
    except httpx.HTTPError as exc:
        return {"error": f"Prune status failed: {exc}"}

    trace = _detect_groovy_trace(raw)
    if trace:
        return {"error": f"Controller Groovy error: {trace}"}
    try:
        status = json.loads(raw.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError) as exc:
        return {"error": f"Could not parse prune status: {exc}", "raw": raw[:500]}

    status["controller"] = controller
    status.setdefault("error", None)
    # Convenience: total items removed and freed bytes for the UI
    report = status.get("report") or {}
    status["total_items"] = sum(v.get("items", 0) for v in report.values() if isinstance(v, dict))
    status["total_bytes"] = status.get("reclaimedBytes") or 0
    return status
