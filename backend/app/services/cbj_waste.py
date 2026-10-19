"""
CBJ resource-waste ADO email — the action layer on top of cbj_resource_analysis.

The Monitoring page surfaces over-provisioned CBJ containers (podTemplates and
controllers reserving far more CPU/memory than they ever use, which forces
Karpenter into bigger/extra nodes). This module lets an engineer email the
owning ADO team a right-sizing request, mirroring the PVC-cleanup email flow.

Team → ADO resolution (prod-east only): a Container Insights namespace like
`cbc-acoms` maps to the controller `acoms`; its ADOs are the controller's
CJOC RBAC admins (reused from copy_controller.discover_admins), resolved to
email + Slack name the same way pvc_cleanup does. gc-prod-west has no CJOC
auth wired, so it falls back to manual recipient entry (best-effort).
"""

import logging

from app.config import get_settings
from app.services import slack_directory
from app.services.cbj_resource_analysis import compute_env_sync
from app.services.copy_controller import (
    _detect_groovy_trace,
    _prod_auth,
    _prod_controller_url,
    discover_admins,
)
from app.services.jenkins import run_groovy_script
from app.services.pvc_cleanup import _controller_from_namespace, _greeting, _html_escape

logger = logging.getLogger(__name__)

# Only warn about containers actually wasting resources (using <30% of reserved
# CPU). "ok" rows are omitted from both the tile and the email.
_WASTEFUL = ("critical", "warning")

# Resolve a set of admin SIDs to their configured email addresses on one
# controller's Script Console. Deliberately lighter than pvc_cleanup's usage
# Groovy — no disk-usage plugin calls, just Mailer.UserProperty lookups.
_GROOVY_SID_EMAILS = r"""
import groovy.json.JsonOutput
import hudson.model.User
import hudson.tasks.Mailer

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
println JsonOutput.toJson(admins)
"""


def _team_rows(env: str, target: str, namespace: str, rows: list[dict] | None = None) -> list[dict]:
    """Wasteful rows for one team (namespace), sorted by CPU wasted, biggest first."""
    if rows is None:
        rows = compute_env_sync(env, target)
    team = [r for r in rows if r.get("namespace") == namespace and r.get("status") in _WASTEFUL]
    team.sort(key=lambda r: (r["cpu_wasted_cores"] if r["cpu_wasted_cores"] is not None else -1), reverse=True)
    # Join configured disk (ephemeral-storage) from the podTemplate sweep — CloudWatch
    # doesn't measure disk, but teams over-request it too (Srikanth, DMSC-479).
    disk = _disk_by_container(_controller_from_namespace(namespace))
    for r in team:
        d = disk.get(r.get("container"))
        r["disk_request"] = d["request"] if d else None
        r["disk_limit"] = d["limit"] if d else None
    return team


def teams_with_waste(env: str, target: str = "agents") -> dict:
    """
    Aggregate the analysis by team (namespace), keeping only teams with at
    least one wasteful container. Sorted by total CPU wasted, biggest first.
    Used to populate the email tile's team picker.
    """
    rows = compute_env_sync(env, target)
    by_ns: dict[str, list[dict]] = {}
    for r in rows:
        if r.get("status") in _WASTEFUL:
            by_ns.setdefault(r["namespace"], []).append(r)

    teams = []
    for ns, team_rows in by_ns.items():
        team_rows.sort(key=lambda r: (r["cpu_wasted_cores"] if r["cpu_wasted_cores"] is not None else -1), reverse=True)
        total_cpu = sum(r["cpu_wasted_cores"] or 0 for r in team_rows)
        total_mem = sum(r["mem_wasted_gb"] or 0 for r in team_rows)
        worst = "critical" if any(r["status"] == "critical" for r in team_rows) else "warning"
        teams.append({
            "namespace": ns,
            "controller": _controller_from_namespace(ns),
            "container_count": len(team_rows),
            "total_cpu_wasted_cores": round(total_cpu, 2),
            "total_mem_wasted_gb": round(total_mem, 2),
            "worst_status": worst,
            "rows": team_rows,
        })

    teams.sort(key=lambda t: t["total_cpu_wasted_cores"], reverse=True)
    return {
        "env": env,
        "target": target,
        # ADO auto-resolution only works where a prod-east CJOC is reachable.
        "resolvable_ados": env == "prod-east",
        "teams": teams,
        "error": None,
    }


def _resolve_sid_emails(controller: str, sids: list[str]) -> dict[str, str | None]:
    """{sid: email|None} for the controller's admins, via its Script Console."""
    if not sids:
        return {}
    auth = _prod_auth()
    if not auth:
        return {sid: None for sid in sids}
    script = _GROOVY_SID_EMAILS.replace("__SIDS__", ",".join(sids))
    try:
        raw = run_groovy_script(_prod_controller_url(controller), script, auth, timeout=45)
    except Exception as exc:
        logger.warning("cbj_waste: SID->email lookup failed for %s: %s", controller, exc)
        return {sid: None for sid in sids}
    if _detect_groovy_trace(raw):
        return {sid: None for sid in sids}
    import json
    try:
        data = json.loads(raw.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        return {sid: None for sid in sids}
    return {a.get("sid"): a.get("email") for a in data if a.get("sid")}


def _resolve_admins(controller: str) -> tuple[list[dict], str | None]:
    """
    Resolve a controller's ADO admins to {sid, email, slack_name, slack_handle}.
    Returns (admins, error). Mirrors pvc_cleanup's Slack resolution: fall back
    from email match to EUA-as-handle, since a CMS Slack handle == EUA == Jenkins SID.
    """
    admin_result = discover_admins(controller)
    sids = admin_result.get("admins", []) or []
    if not sids:
        return [], admin_result.get("error")

    sid_emails = _resolve_sid_emails(controller, sids)

    directory = slack_directory.load_directory()
    handle_index: dict[str, dict] = {}
    for entry in directory.values():
        h = (entry.get("handle") or "").lower()
        if h and h not in handle_index:
            handle_index[h] = entry

    # AD deactivation status (SID == EUA == sAMAccountName). Disabled admins are
    # excluded from emails; 'unknown' (AD unreachable) is treated as active.
    from app.services import ldap_accounts
    ad_status = ldap_accounts.get_disabled_status(sids)

    admins = []
    for sid in sids:
        email = sid_emails.get(sid)
        entry = directory.get(email.strip().lower()) if email else None
        if not entry and sid:
            entry = handle_index.get(sid.lower())
        status = ad_status.get(sid.lower(), "unknown")
        admins.append({
            "sid": sid,
            "email": email,
            "slack_handle": entry.get("handle") if entry else None,
            "slack_name": entry.get("name") if entry else None,
            "ad_status": status,
            "deactivated": status == "disabled",
        })
    return admins, admin_result.get("error")


_ENV_LABEL = {"prod-east": "prod-east", "gc-prod-west": "gc-prod-west"}


def team_ados(env: str, target: str, namespace: str, engineer: str = "") -> dict:
    """
    Resolve the owning ADOs for one team plus the wasteful containers we'd warn
    about, and a drafted plain-text message the engineer can review/edit.
    """
    controller = _controller_from_namespace(namespace)
    rows = _team_rows(env, target, namespace)

    if env == "prod-east":
        admins, admin_error = _resolve_admins(controller)
        note = None
    else:
        admins, admin_error = [], None
        note = ("Automatic ADO lookup isn't wired for gc-prod-west — enter recipient "
                "email(s) manually below.")

    ado_names = [a["slack_name"] for a in admins if a.get("slack_name")]
    message = _compose_message(env, target, controller, rows, ado_names, engineer or "the DevOps team")

    from app.services import email_notices
    return {
        "env": env,
        "target": target,
        "namespace": namespace,
        "controller": controller,
        "email_history": email_notices.history("cbj_waste", f"{env}:{namespace}:{target}"),
        "rows": rows,
        "admins": admins,
        "admin_discovery_error": admin_error,
        "resolvable_ados": env == "prod-east",
        "note": note,
        "ado_message": message,
        "error": None,
    }


def _kind_word(target: str) -> str:
    return "controller" if target == "controllers" else "build agent (podTemplate)"


def _cpu_cell(r: dict) -> str:
    pair = _recommend_cpu(r)
    return f"{_n(pair[0], 2)}/{_n(pair[1], 2)}" if pair else "—"


def _mem_cell(r: dict) -> str:
    pair = _recommend_mem(r)
    return f"{_n(pair[0], 1)}/{_n(pair[1], 1)}Gi" if pair else "—"


def _disk_cell(r: dict) -> str:
    req, lim = r.get("disk_request"), r.get("disk_limit")
    return f"{req or '—'}/{lim or '—'}" if (req or lim) else "—"


def _disk_suggest_cell(r: dict) -> str:
    if not (r.get("disk_request") or r.get("disk_limit")):
        return "—"
    return f"{_DISK_DEFAULT_REQUEST_GI}/{_DISK_DEFAULT_LIMIT_GI}Gi"


def _recommendation_table(rows: list[dict]) -> str:
    """Fixed-width monospace table (container | current CPU reserved | suggested
    CPU req/limit | suggested Mem req/limit [| current disk req/limit | suggested
    disk]), meant for a ``` code block so Slack/Jira preserve the column
    alignment. Scanning down 'current' vs 'suggested' side by side shows the
    gap at a glance, no per-line parsing. Every flagged container is shown --
    a table scales fine, unlike a sentence per container."""
    if not rows:
        return "(no container detail available)"

    has_disk = any(r.get("disk_request") or r.get("disk_limit") for r in rows)

    headers = ["Container", "CPU now", "CPU suggest", "Mem suggest"]
    if has_disk:
        headers += ["Disk req/limit", "Disk suggest"]

    def _row(r):
        row = [r.get("container") or "", _n(r.get("cpu_reserved_cores")), _cpu_cell(r), _mem_cell(r)]
        if has_disk:
            row += [_disk_cell(r), _disk_suggest_cell(r)]
        return row

    data = [_row(r) for r in rows]
    widths = [max(len(h), *(len(row[i]) for row in data)) for i, h in enumerate(headers)]

    def _fmt(row):
        return "  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row))

    lines = [_fmt(headers), _fmt(["-" * w for w in widths])]
    lines += [_fmt(row) for row in data]
    return "\n".join(lines)


def _compose_message(env: str, target: str, controller: str, rows: list[dict],
                     ado_names: list[str], engineer: str) -> str:
    """Plain-text copy-and-send message (Slack/manual), mirrors pvc_cleanup._compose_ado_message."""
    greeting = _greeting(ado_names)
    kind = _kind_word(target)
    table = _recommendation_table(rows)
    return (
        f"{greeting}\n\n"
        f"Your CloudBees Jenkins {kind}(s) under *{controller}* ({_ENV_LABEL.get(env, env)}) are "
        f"reserving considerably more CPU/memory than they use at peak over the last 7 days. The "
        f"\"suggest\" columns below are request/limit — the two numbers to set in your podTemplate:\n\n"
        f"```\n{table}\n```\n\n"
        f"Karpenter provisions nodes based on what's *reserved*, not what's used — so an oversized "
        f"request directly forces bigger or extra nodes even when the container is idle.\n\n"
        f"These are recommended starting values. Please test the pipelines after making the changes "
        f"and monitor for CPU throttling, OOMKilled containers, or ephemeral-storage errors. The "
        f"values can then be adjusted based on actual workload requirements.\n\n"
        f"We're happy to help review the configuration and select safe values.\n\n"
        f"Thanks,\n{engineer}"
    )


def _n(v, digits: int = 2) -> str:
    return "—" if v is None else f"{v:.{digits}f}"


def _pct(v) -> str:
    return "—" if v is None else f"{v * 100:.1f}%"


# Recommended-values margin/rounding: request = peak usage + 25% headroom,
# rounded up to a clean increment. Goal is a *minimal* starting point (start
# small, bump it if the pipeline actually throttles/OOMs), not generous
# headroom — so limit is capped at a sensible ceiling rather than a flat 2x:
# below the ceiling, limit = min(2x request, ceiling); at/above it, limit is
# just request + a modest 25% buffer instead of doubling an already-large ask.
_CPU_STEP = 0.25       # cores
_MEM_STEP = 0.5        # GiB
_MARGIN = 1.25
_LIMIT_MULTIPLIER = 2
_CPU_LIMIT_CEILING = 2.0   # cores
_MEM_LIMIT_CEILING = 2.0   # GiB

# No CloudWatch disk-usage metric exists (see _disk_by_container), so disk
# can't be recommended from observed peak usage the way CPU/memory can. This
# is a conservative flat starting point, not a usage-derived number — labeled
# as such in the email so it isn't mistaken for real measured data.
_DISK_DEFAULT_REQUEST_GI = 1
_DISK_DEFAULT_LIMIT_GI = 2


def _round_up(value: float, step: float) -> float:
    import math
    return max(step, math.ceil(value / step) * step)


def _capped_limit(request: float, step: float, ceiling: float) -> float:
    """Below the ceiling: min(2x request, ceiling) -- generous relative to a
    small request, but never past the ceiling. At/above the ceiling: request
    already IS the "start minimal" number, so just add a modest 25% buffer
    instead of doubling an already-large ask."""
    if request < ceiling:
        return min(_round_up(request * _LIMIT_MULTIPLIER, step), ceiling)
    return _round_up(request * _MARGIN, step)


def _recommend_cpu(r: dict) -> tuple[float, float] | None:
    """(request_cores, limit_cores), or None if we have no peak-usage reading."""
    used = r.get("cpu_used_at_peak_cores")
    if used is None:
        return None
    request = _round_up(used * _MARGIN, _CPU_STEP)
    return request, _capped_limit(request, _CPU_STEP, _CPU_LIMIT_CEILING)


def _recommend_mem(r: dict) -> tuple[float, float] | None:
    """(request_gb, limit_gb), or None if we have no peak-usage reading."""
    used = r.get("mem_used_at_peak_gb")
    if used is None:
        return None
    request = _round_up(used * _MARGIN, _MEM_STEP)
    return request, _capped_limit(request, _MEM_STEP, _MEM_LIMIT_CEILING)


def _qty_to_bytes(q) -> float | None:
    """Parse a k8s quantity ('20Gi', '500m'... only storage units here) to bytes,
    for picking the largest request per container. Returns None if unparseable."""
    import re
    if not q:
        return None
    m = re.match(r"^\s*([\d.]+)\s*([KMGTP]i?)?\s*$", str(q))
    if not m:
        return None
    mult = {"": 1, "K": 1e3, "M": 1e6, "G": 1e9, "T": 1e12, "P": 1e15,
            "Ki": 1024, "Mi": 1024 ** 2, "Gi": 1024 ** 3, "Ti": 1024 ** 4, "Pi": 1024 ** 5}
    return float(m.group(1)) * mult.get(m.group(2) or "", 1)


def _disk_by_container(controller: str) -> dict[str, dict]:
    """{container_name: {'request': str|None, 'limit': str|None}} of configured
    ephemeral-storage from the podTemplate sweep cache for this controller —
    CloudWatch has no disk metric, so requested disk comes from the pod YAML the
    podTemplate Config feature already collects. Picks the entry with the largest
    request per container name. Returns {} if no sweep has run."""
    try:
        from app.services.cbj_podtemplate_config import load_cache
        cache = load_cache() or {}
    except Exception as exc:  # noqa: BLE001 - degrade to no disk data, never fail the email
        logger.warning("cbj_waste: could not load podTemplate cache for disk join: %s", exc)
        return {}
    out: dict[str, dict] = {}
    for r in cache.get("results", []):
        if r.get("controller") != controller:
            continue
        for c in r.get("containers", []):
            name = c.get("container")
            req, lim = c.get("ephemeral_request"), c.get("ephemeral_limit")
            if not name or (req is None and lim is None):
                continue
            cur = out.get(name)
            if cur is None or (_qty_to_bytes(req) or 0) > (_qty_to_bytes(cur.get("request")) or 0):
                out[name] = {"request": req, "limit": lim}
    return out


def _email_html(env: str, target: str, controller: str, rows: list[dict],
                ado_names: list[str], engineer: str) -> str:
    greeting = _greeting(ado_names)
    kind = _kind_word(target)

    def _fmt_pair(pair: tuple[float, float] | None, suffix: str) -> str:
        if not pair:
            return "—"
        return f"{_n(pair[0], 2)}→{_n(pair[1], 2)}{suffix}"

    def _fmt_str_pair(a, b) -> str:
        if not a and not b:
            return "—"
        return f"{a or '—'}→{b or '—'}"

    has_disk = any(r.get("disk_request") or r.get("disk_limit") for r in rows)
    disk_th = (
        '<th style="padding:6px 10px;text-align:right;font-size:12px;color:#6b7280;border-bottom:1px solid #eee">Disk req→limit</th>'
        if has_disk else ""
    )
    disk_suggest_th = (
        '<th style="padding:6px 10px;text-align:right;font-size:12px;color:#0b4f8a;border-bottom:1px solid #eee">Suggested Disk</th>'
        if has_disk else ""
    )

    def _row_html(r):
        status = r.get("status")
        color = "#dc2626" if status == "critical" else "#d97706" if status == "warning" else "#111"
        row_has_disk = bool(r.get("disk_request") or r.get("disk_limit"))
        disk_cell = (
            f'<td style="padding:6px 10px;border-bottom:1px solid #eee;text-align:right;color:#444">{_html_escape(_fmt_str_pair(r.get("disk_request"), r.get("disk_limit")))}</td>'
            if has_disk else ""
        )
        disk_suggest_cell = ""
        if has_disk:
            suggest = f"{_DISK_DEFAULT_REQUEST_GI}→{_DISK_DEFAULT_LIMIT_GI}Gi" if row_has_disk else "—"
            disk_suggest_cell = f'<td style="padding:6px 10px;border-bottom:1px solid #eee;text-align:right;color:#0b4f8a;font-weight:600">{_html_escape(suggest)}</td>'
        return (
            "<tr>"
            f'<td style="padding:6px 10px;border-bottom:1px solid #eee;font-family:monospace;font-size:13px;color:#111">{_html_escape(r.get("container"))}</td>'
            f'<td style="padding:6px 10px;border-bottom:1px solid #eee;text-align:right;color:#444">{_n(r.get("cpu_reserved_cores"))}</td>'
            f'<td style="padding:6px 10px;border-bottom:1px solid #eee;text-align:right;color:#444">{_n(r.get("cpu_used_at_peak_cores"))} ({_pct(r.get("cpu_pct_used"))})</td>'
            f'<td style="padding:6px 10px;border-bottom:1px solid #eee;text-align:right;font-weight:600;color:{color}">{_n(r.get("cpu_wasted_cores"))}</td>'
            f'<td style="padding:6px 10px;border-bottom:1px solid #eee;text-align:right;color:#444">{_n(r.get("mem_reserved_gb"))}→{_n(r.get("mem_used_at_peak_gb"))}GB</td>'
            f'{disk_cell}'
            f'<td style="padding:6px 10px;border-bottom:1px solid #eee;text-align:right;color:#0b4f8a;font-weight:600">{_html_escape(_fmt_pair(_recommend_cpu(r), " core"))}</td>'
            f'<td style="padding:6px 10px;border-bottom:1px solid #eee;text-align:right;color:#0b4f8a;font-weight:600">{_html_escape(_fmt_pair(_recommend_mem(r), "Gi"))}</td>'
            f'{disk_suggest_cell}'
            "</tr>"
        )

    body_rows = "".join(_row_html(r) for r in rows) or (
        '<tr><td style="padding:6px 10px;color:#888" colspan="8">No container detail available.</td></tr>'
    )

    return f"""\
<div style="font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:#1f2937;max-width:680px;margin:0 auto;padding:8px">
  <p style="font-size:15px;margin:0 0 14px">{_html_escape(greeting)}</p>

  <p style="font-size:14px;line-height:1.55;margin:0 0 16px">
    Your CloudBees Jenkins {_html_escape(kind)}(s) under <strong>{_html_escape(controller)}</strong>
    (<span style="color:#6b7280">{_html_escape(_ENV_LABEL.get(env, env))}</span>) are reserving
    considerably more CPU/memory than they actually use at their busiest moment over the last 7 days.
    The "Suggested" columns show a starting <em>request → limit</em> for each — the two numbers to
    set in your podTemplate.
  </p>

  <table role="presentation" cellpadding="0" cellspacing="0" style="border-collapse:collapse;width:100%;margin:0 0 4px;border:1px solid #eee">
    <thead><tr style="background:#f9fafb">
      <th style="padding:6px 10px;text-align:left;font-size:12px;color:#6b7280;border-bottom:1px solid #eee">Container</th>
      <th style="padding:6px 10px;text-align:right;font-size:12px;color:#6b7280;border-bottom:1px solid #eee">CPU reserved</th>
      <th style="padding:6px 10px;text-align:right;font-size:12px;color:#6b7280;border-bottom:1px solid #eee">CPU used @ peak</th>
      <th style="padding:6px 10px;text-align:right;font-size:12px;color:#6b7280;border-bottom:1px solid #eee">CPU wasted</th>
      <th style="padding:6px 10px;text-align:right;font-size:12px;color:#6b7280;border-bottom:1px solid #eee">Mem res→used</th>
      {disk_th}
      <th style="padding:6px 10px;text-align:right;font-size:12px;color:#0b4f8a;border-bottom:1px solid #eee">Suggested CPU</th>
      <th style="padding:6px 10px;text-align:right;font-size:12px;color:#0b4f8a;border-bottom:1px solid #eee">Suggested Mem</th>
      {disk_suggest_th}
    </tr></thead>
    <tbody>{body_rows}</tbody>
  </table>

  <p style="font-size:14px;line-height:1.55;margin:18px 0 18px">
    <strong>Why this matters:</strong> Karpenter sizes and provisions nodes based on what a container
    <em>reserves</em>, not what it uses — so an oversized request directly forces a bigger (or an extra)
    node even when the container is idle. Trimming the requests toward the suggested numbers above lets
    Karpenter pack more onto fewer, smaller nodes.
  </p>

  <p style="font-size:14px;line-height:1.55;margin:0 0 8px">
    These are recommended starting values. Please test the pipelines after making the changes and
    monitor for CPU throttling, OOMKilled containers, or ephemeral-storage errors. The values can
    then be adjusted based on actual workload requirements.
  </p>
  <p style="font-size:14px;line-height:1.55;margin:0 0 18px">
    We're happy to help review the configuration and select safe values.
  </p>

  <p style="font-size:13px;color:#6b7280;margin:0;border-top:1px solid #eee;padding-top:12px">
    Sent by {_html_escape(engineer or "the CMS Cloud DevOps team")} via the DevOps Dashboard.
  </p>
</div>"""


def email_team(env: str, target: str, namespace: str, engineer: str = "",
               extra_emails: list[str] | None = None) -> dict:
    """
    Email the team's ADOs a right-sizing request for their wasteful containers.
    Recipients = auto-resolved ADO emails (prod-east) plus any manually-entered
    addresses (required for gc-prod-west). cc's the DevOps distro.
    """
    from app.services import email_service  # local import avoids an import cycle
    from app.services import email_notices

    controller = _controller_from_namespace(namespace)
    rows = _team_rows(env, target, namespace)
    if not rows:
        return {"sent": False, "error": f"No wasteful containers found for {namespace} — nothing to email."}

    if env == "prod-east":
        admins, _ = _resolve_admins(controller)
    else:
        admins = []
    # Exclude AD-deactivated admins (keep 'unknown'); manual extra_emails always kept.
    active = [a for a in admins if not a.get("deactivated")]
    excluded = [a for a in admins if a.get("deactivated")]
    ado_names = [a["slack_name"] for a in active if a.get("slack_name")]

    to = [a["email"] for a in active if a.get("email")]
    for e in (extra_emails or []):
        e = (e or "").strip()
        if e and e not in to:
            to.append(e)
    if not to:
        return {
            "sent": False,
            "error": "No recipient email addresses — auto-resolution found none and none were entered. "
                     "Contact the ADO on Slack instead.",
        }

    kind = _kind_word(target)
    # Escalating notice per team+env+target: 1st plain, 2nd "[Second Notice]", 3rd+ "[Final Notice]".
    notice_key = f"{env}:{namespace}:{target}"
    ordinal, prefix = email_notices.peek_next("cbj_waste", notice_key)
    subject = f"{prefix}Action needed: right-size CBJ {kind}(s) under {controller} ({_ENV_LABEL.get(env, env)})"
    html = _email_html(env, target, controller, rows, ado_names, engineer)

    cc = get_settings().CBJ_WASTE_EMAIL_CC
    result = email_service.send_html_email(to=to, subject=subject, html_body=html, cc=[cc] if cc else None)
    result["subject"] = subject
    result.setdefault("to", to)
    result.setdefault("cc", [cc] if cc else [])
    result["controller"] = controller
    result["namespace"] = namespace
    result["excluded_deactivated"] = [
        {"sid": a["sid"], "email": a.get("email"), "name": a.get("slack_name")}
        for a in excluded
    ]
    if result.get("sent"):
        email_notices.record("cbj_waste", notice_key, to, engineer)
    result["notice_ordinal"] = ordinal
    result["email_history"] = email_notices.history("cbj_waste", notice_key)
    return result
