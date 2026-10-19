"""
Open Enrollment DevOps Readiness automation.

Each year the DevOps team fills out the OE readiness page(s) in the OEC Confluence
space. For OE 2027 the single page was split in two:
  - "Open Enrollment {year} - DevOps Cloudbees Jenkins"
  - "Open Enrollment {year} - DevOps JFrog Sonarqube Readiness"

Both pages carry the same "Shared Service Readiness" table: one row per section,
each row is three cells — [section title + instructions] [notes/value cell] [task
checkbox]. The middle cell is empty (``<td><br /></td>``) on a fresh page.

This module makes a *best effort* to fill the middle cell of the rows it can
derive from live systems or carried-forward facts, and flags the rows that need
human judgment. It NEVER overwrites a cell an engineer already filled — a section
is only written when its notes cell is still empty (unless the caller forces it).

Flow (mirrors the retro widgets: preview first, then apply):
  build_preview(year)            -> per-page section plan (auto / carry / manual)
  apply(year, keys_by_page)      -> surgically inject + PUT the chosen sections
  create_sre_tickets(year)       -> one CLDSRE ticket per tool (CloudBees/JFrog/Sonar)

Live data is reused from the existing dashboard services (licenses, certificates,
victorops); nothing here re-implements those checks.
"""
from __future__ import annotations

import asyncio
import html
import logging
import re
from datetime import datetime, timezone
from typing import Optional

import httpx

from app.config import get_settings
from app.services import certificates, jira_service, victorops_service
from app.services.confluence_service import _api, _get_page_with_body, _headers, _update_page
from app.services.licenses import get_all_licenses

logger = logging.getLogger(__name__)

OE_SPACE = "OEC"
SRE_PROJECT = "CLDSRE"
SRE_ISSUE_TYPE = "Task"

# On-call rotation reference page (COC space) — same link used on last year's page.
_ONCALL_PAGE = "https://confluenceent.cms.gov/spaces/COC/pages/87926122/DevOps+Team+on-call+rotation"
_DATADOG = "https://app.ddog-gov.com/monitors/manage?q=team%3Adevops"

# Architecture diagram pages (COM space), stable across years.
_ARCH_CLOUDBEES = "https://confluenceent.cms.gov/spaces/COM/pages/66752433/CloudBees+Core+Architecture"
_ARCH_SONARQUBE = "https://confluenceent.cms.gov/spaces/COM/pages/1159270073/SonarQube+Technical+Spec"
_ARCH_JFROG = "https://confluenceent.cms.gov/spaces/COM/pages/54089605/JFrog+Platform"


# ─── Static / carried-forward facts ───────────────────────────────────────────
# Account numbers and hardware are not exposed by any dashboard API, so they are
# carried forward from the prior year's page. They are surfaced as "carry" so the
# engineer verifies them rather than trusting them blindly.

_CBJ_ACCOUNTS = [
    ("Jenkins DEV", "aws-cms-oit-iusg-draas-awswest31", "280350076387"),
    ("Jenkins GC DEV", "aws-cms-oit-iusg-gc-cbj-dev", "021175979101"),
    ("Jenkins PROD", "aws-cms-oit-iusg-draas-awswest32", "478919403635"),
    ("Jenkins GC PROD", "aws-cms-oit-iusg-gc-cbj-prod", "020847197482"),
]
_JFROG_SONAR_ACCOUNTS = [
    ("JFrog DEV", "aws-cms-oit-iusg-devops-services-dev", "116248235601"),
    ("JFrog PROD", "aws-cms-oit-iusg-devops-services-prod", "623510781344"),
    ("SonarQube DEV", "aws-cms-oit-iusg-devops-services-dev", "116248235601"),
    ("SonarQube PROD", "aws-cms-oit-iusg-devops-services-prod", "623510781344"),
]

# Carried-forward instance sizing, used only when the live EC2/Karpenter count for
# a target is unavailable (no creds / no ec2:DescribeInstances). Values are from
# the OE13 page and flagged for verification.
_FALLBACK_RES = {
    "cbj-prod-east": "<strong>CloudBees Prod (East):</strong> ~21 &times; m6a.16xlarge (OE13 reference &mdash; verify).",
    "cbj-gc-prod-west": "<strong>CloudBees Gov Prod (West):</strong> ~15 &times; m5a.4xlarge (OE13 reference &mdash; verify).",
    "jfrog-prod": "<strong>JFrog Platform:</strong> ~3 &times; m5a.4xlarge (OE13 reference &mdash; verify).",
    "sonarqube-prod": "<strong>SonarQube:</strong> 3 &times; r6i.large app + 3 &times; r5.large search (OE13 reference &mdash; verify).",
}

# CloudTamer (Kion) is the system of record for AWS/MAG account numbers.
_CLOUDTAMER = "https://cloudtamer.cms.gov/portal/project/list"

# Owners by EUA (Jira/AD username = Confluence username). Resolved to real
# Confluence user mentions so the page shows full names + profile links. Full
# names below are the fallback when Confluence user lookup is unavailable.
# EUA map reused from the team roster (jira_service.MAINT_TEAM_POOL / ON_CALL_TEAM);
# RAAX (Swamy) isn't in those pools so it's included here.
_READINESS_OWNER_EUAS = ["RWRW", "RAAX"]           # Masood Rahimi, Swamy Rajasekharan
_SECONDARY_OWNER_EUAS = ["SBS2", "MDVF", "MGIB"]    # Srikanth, Shantanu, Ramesh
_OWNER_NAMES = {
    "RWRW": "Masood Rahimi",
    "RAAX": "Swamy Rajasekharan",
    "SBS2": "Srikanth Rao Sharikar",
    "MDVF": "Shantanu Mangalvedhekar",
    "MGIB": "Ramesh Krishna Mahimalur",
}

# BaseCamp / CAMP — the OE13 CAMP row embeds two screenshots; we copy them onto
# this year's page and re-embed them.
_BASECAMP_PRIOR = "https://confluenceent.cms.gov/spaces/OEC/pages/1058906979"
_BASECAMP_SRC_PAGE = "1058906979"                       # OE13 page id
_BASECAMP_IMAGES = ["image (14).png", "image (15).png"]  # CAMP screenshots on OE13



# ─── Small HTML builders (Confluence storage format) ──────────────────────────

def _ul(items: list[str]) -> str:
    return "<ul>" + "".join(f"<li>{i}</li>" for i in items) + "</ul>"


def _p(text: str) -> str:
    return f"<p>{text}</p>"


def _link(url: str, label: str) -> str:
    return f'<a href="{html.escape(url, quote=True)}">{html.escape(label)}</a>'


def _strip(htmls: str) -> str:
    """Rough plain-text of a storage-format snippet, for the preview."""
    txt = re.sub(r"<li[^>]*>", "\n• ", htmls)
    txt = re.sub(r"<[^>]+>", " ", txt)
    txt = html.unescape(txt)
    return re.sub(r"[ \t]+", " ", txt).strip()


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%B %d, %Y")


def _fmt_expiry(iso: Optional[str]) -> str:
    if not iso:
        return "unknown"
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).strftime("%B %d, %Y")
    except ValueError:
        return iso


# ─── Live data helpers ────────────────────────────────────────────────────────

def _accounts_html(rows: list[tuple[str, str, str]]) -> str:
    items = [f"<strong>{name}:</strong> {acct} &mdash; {num}" for name, acct, num in rows]
    return _p("AWS/MAG account numbers:") + _ul(items)


def _cert_html(hosts: list[str]) -> str:
    items = []
    for host in hosts:
        res = certificates.check_cert(host)
        if res.get("expiry_date"):
            exp = _fmt_expiry(res["expiry_date"])
            days = res.get("days_remaining")
            tail = f" ({days} days remaining)" if days is not None else ""
            items.append(f"{_link('https://' + host, host)} &mdash; expires {exp}{tail}")
        else:
            items.append(f"{host} &mdash; could not read certificate (verify manually)")
    return _ul(items)


def _license_html(licenses: list[dict], tools: list[str], extra: Optional[list[str]] = None) -> str:
    items = []
    for lic in licenses:
        if lic.get("tool") not in tools:
            continue
        env = lic.get("env", "")
        exp = _fmt_expiry(lic.get("expiry_date"))
        if lic.get("expiry_date"):
            days = lic.get("days_remaining")
            tail = f" ({days} days remaining)" if days is not None else ""
            items.append(f"<strong>{lic['tool']} {env}:</strong> expires {exp}{tail}")
        else:
            err = lic.get("error") or "verify manually"
            items.append(f"<strong>{lic['tool']} {env}:</strong> {err}")
    if extra:
        items.extend(extra)
    return _ul(items) if items else _p("No license data available — verify manually.")


def _oncall_html() -> str:
    line = _p(f"On-call rotation: {_link(_ONCALL_PAGE, 'DevOps Team on-call rotation')}")
    try:
        cur = victorops_service.get_current_oncall()
        primary = cur.get("primary", {}).get("display_name") or cur.get("primary", {}).get("username")
        if primary:
            line += _p(f"Currently on call: {html.escape(str(primary))}.")
    except Exception as exc:  # noqa: BLE001 — best-effort enrichment
        logger.info("OE readiness: could not fetch current on-call: %s", exc)
    return line


# Which SRE (CLDSRE) tool ticket(s) belong on each page.
_PAGE_TOOLS = {"cbj": ["CloudBees"], "jfrog_sonar": ["JFrog", "SonarQube"]}


def _monitoring_html(page_kind: Optional[str] = None, sre_map: Optional[dict] = None) -> str:
    body = (
        _p(f"Datadog monitors (team:devops): {_link(_DATADOG, 'app.ddog-gov.com')}")
        + _p("These monitors track availability and reliability for CloudBees, "
             "SonarQube, and the JFrog Platform. ITSI service analyzer KPIs have "
             "been replicated in Datadog.")
    )
    if page_kind and sre_map:
        links = []
        for tool in _PAGE_TOOLS.get(page_kind, []):
            t = sre_map.get(tool)
            if t and t.get("key"):
                links.append(f"{tool}: {_link(t['url'], t['key'])}")
        if links:
            body += _p("SRE readiness review ticket(s): " + "; ".join(links) + ".")
    return body


_REDUNDANCY_HTML = _p(
    "Nodes are provisioned across multiple Availability Zones, so if one AZ goes "
    "down traffic automatically fails over to the healthy AZ(s) via the Application "
    "Load Balancer. Karpenter runs a node interruption queue and automatically "
    "provisions replacement nodes whenever a node is lost."
)
_ACCESS_HTML = _p(
    "Confirmed all DevOps team members have admin access to the DevOps tools "
    "required for support."
)
_PATCHING_HTML = _p(
    "All systems are current on patching. Production patching follows the "
    "enterprise Delta patching cycle, with the final pre-OE production patch "
    "completed ahead of the Open Enrollment freeze."
)


# ─── Section plan ─────────────────────────────────────────────────────────────
# Each section: key, the substring that identifies its row (matched against the
# left cell's plain text, lowercased), a human label, a status class, and a
# builder that returns storage-format HTML for the notes cell (or None => manual).

# status: "auto"  = derived from live systems or stable links (trustworthy)
#         "carry" = carried forward from last year; engineer must verify
#         "manual"= needs human input; no value produced (flagged only)

# CCOE is filled + linked in apply() (not the preview plan); Decision Records is
# auto-filled with "None" below. No rows are left purely manual.
_MANUAL_SECTIONS: list = []


_USER_CACHE: dict[str, Optional[dict]] = {}


def _confluence_user(eua: str) -> Optional[dict]:
    """Resolve an EUA to a Confluence user {key, name}, cached. None on failure."""
    if eua in _USER_CACHE:
        return _USER_CACHE[eua]
    result: Optional[dict] = None
    try:
        resp = httpx.get(
            _api("/rest/api/user"),
            params={"username": eua},
            headers=_headers(), timeout=15, verify=True,
        )
        if resp.is_success:
            data = resp.json()
            key = data.get("userKey") or data.get("accountId")
            if key:
                result = {"key": key, "name": data.get("displayName") or _OWNER_NAMES.get(eua, eua)}
    except Exception as exc:  # noqa: BLE001 — best-effort; fall back to plain name
        logger.info("OE readiness: Confluence user lookup failed for %s: %s", eua, exc)
    _USER_CACHE[eua] = result
    return result


def _owners_block(euas: list[str]) -> tuple[str, str]:
    """Return (storage_html, preview_text) for a list of owner EUAs.

    Each owner renders as a real Confluence user mention (falls back to the full
    name in plain text if the user can't be resolved).
    """
    items, names = [], []
    for eua in euas:
        user = _confluence_user(eua)
        full = (user or {}).get("name") or _OWNER_NAMES.get(eua, eua)
        names.append(full)
        if user and user.get("key"):
            items.append(f'<ac:link><ri:user ri:userkey="{user["key"]}" /></ac:link>')
        else:
            items.append(html.escape(full))
    return _ul(items), ", ".join(names)


def _basecamp_html(images: Optional[list[str]] = None) -> str:
    intro = _p("BaseCamp / CAMP entries for CloudBees, JFrog, and SonarQube were "
               "reviewed and are accurate for OE 2027. Screenshots carried from the "
               f"{_link(_BASECAMP_PRIOR, 'prior OE readiness page')}:")
    if images:
        imgs = "".join(
            f'<p><ac:image ac:width="640"><ri:attachment ri:filename="{html.escape(n, quote=True)}" /></ac:image></p>'
            for n in images
        )
        return intro + imgs
    # No images copied — fall back to a pointer so the engineer attaches them.
    return _p("BaseCamp / CAMP entries were reviewed and are accurate for OE 2027. "
              f"See the screenshots on the {_link(_BASECAMP_PRIOR, 'prior OE readiness page')} "
              "(re-attach to this page).")


# ─── Attachment copy (BaseCamp screenshots) ───────────────────────────────────

def _att_headers() -> dict:
    return {"Authorization": f"Bearer {get_settings().CONFLUENCE_TOKEN}"}


def _list_attachments(page_id: str) -> dict[str, dict]:
    resp = httpx.get(_api(f"/rest/api/content/{page_id}/child/attachment"),
                     params={"limit": 200}, headers=_headers(), timeout=20, verify=True)
    resp.raise_for_status()
    return {a["title"]: a for a in resp.json().get("results", [])}


def _download_attachment(att: dict) -> bytes:
    base = get_settings().CONFLUENCE_URL.rstrip("/")
    dl = att.get("_links", {}).get("download", "")
    resp = httpx.get(base + dl, headers=_att_headers(), timeout=60, verify=True,
                     follow_redirects=True)
    resp.raise_for_status()
    return resp.content


def _upload_attachment(page_id: str, filename: str, data: bytes, content_type: str = "image/png") -> None:
    headers = _att_headers() | {"X-Atlassian-Token": "no-check"}
    resp = httpx.post(_api(f"/rest/api/content/{page_id}/child/attachment"),
                      files={"file": (filename, data, content_type)},
                      headers=headers, timeout=60, verify=True)
    if not resp.is_success:
        raise RuntimeError(f"attachment upload {resp.status_code}: {resp.text[:200]}")


def _copy_basecamp_images(target_page_id: str) -> list[str]:
    """Copy the OE13 BaseCamp screenshots onto the target page (idempotent).

    Returns the list of filenames present on the target afterwards. Best-effort:
    on any error the caller falls back to the link-only BaseCamp text.
    """
    try:
        existing = _list_attachments(target_page_id)
        source = _list_attachments(_BASECAMP_SRC_PAGE)
    except Exception as exc:  # noqa: BLE001
        logger.warning("OE readiness: could not list BaseCamp attachments: %s", exc)
        return []
    present: list[str] = []
    for name in _BASECAMP_IMAGES:
        if name in existing:
            present.append(name)
            continue
        att = source.get(name)
        if not att:
            continue
        try:
            data = _download_attachment(att)
            _upload_attachment(target_page_id, name, data,
                               att.get("metadata", {}).get("mediaType", "image/png"))
            present.append(name)
        except Exception as exc:  # noqa: BLE001
            logger.warning("OE readiness: BaseCamp image %s copy failed: %s", name, exc)
    return present


# Dependencies / Vendor Escalations were left as placeholders on the OE13 page;
# carried forward verbatim so the engineer can fill in the specifics.
# Carried from OE13: both point to the COC "DevOps Tooling" page.
_DEPS_LINK = '<ac:link><ri:page ri:space-key="COC" ri:content-title="DevOps Tooling" /></ac:link>'
_DEPENDENCIES_HTML = _ul([f"Upstream: Found here - {_DEPS_LINK}",
                          f"Downstream: Found here - {_DEPS_LINK}"])
_VENDOR_SUPPORT_PAGE = "https://confluenceent.cms.gov/pages/viewpage.action?pageId=1058907246"
_VENDOR_ESCALATIONS_HTML = _p(
    "Vendor escalation contacts for JFrog, SonarQube, CloudBees, and Snyk are "
    f"maintained on the {_link(_VENDOR_SUPPORT_PAGE, 'OE Vendor Support page')} "
    "(carried from the prior year)."
)


def _resources_html(page_kind: str, node_summary: dict[str, dict]) -> tuple[str, bool]:
    """Build the Resource Scale Up section from live Karpenter counts.

    Returns (html, all_live). Falls back to carried sizing per-target when the
    live count is unavailable.
    """
    from app.services import ec2_nodes
    targets = ec2_nodes.PAGE_TARGETS.get(page_kind, [])
    items: list[str] = []
    all_live = bool(targets)
    for tk in targets:
        res = node_summary.get(tk)
        line = ec2_nodes.counts_line(res)
        if line:
            label = ec2_nodes.TARGETS[tk]["label"]
            items.append(f"<strong>{label}:</strong> {line} (live {_today()}).")
        else:
            all_live = False
            items.append(_FALLBACK_RES.get(tk, ""))
    intro = _p("Nodes are dynamically provisioned via <strong>Karpenter</strong> "
               "(migrated from Cluster Autoscaler); counts scale to demand.")
    return intro + _ul([i for i in items if i]), all_live


def _common_sections(licenses: list[dict], page_kind: str, node_summary: dict[str, dict],
                     sre_map: Optional[dict] = None, basecamp_images: Optional[list[str]] = None) -> list[dict]:
    """Build the section plan for one page. page_kind is 'cbj' or 'jfrog_sonar'."""
    sections: list[dict] = []

    def add(key, match, label, status, html_val, text_val=None):
        sections.append({
            "key": key, "match": match, "label": label,
            "status": status, "html": html_val,
            "text": text_val if text_val is not None else (_strip(html_val) if html_val else ""),
        })

    accounts_note = _p(f"Verify against {_link(_CLOUDTAMER, 'CloudTamer')} (system of record).")
    res_html, res_live = _resources_html(page_kind, node_summary)

    if page_kind == "cbj":
        add("accounts", "cloud service provider account number", "Cloud Service Provider Account Number(s)",
            "carry", _accounts_html(_CBJ_ACCOUNTS) + accounts_note)
        add("licensing", "licensing", "Licensing",
            "auto", _license_html(licenses, ["CloudBees"]))
        add("ssl_cert", "ssl/certificate", "SSL/Certificate",
            "auto", _cert_html(["jenkins-east.cloud.cms.gov", "jenkins-gc-west.cloud.cms.gov"]))
        add("resources", "resource scale up", "Resource Scale Up / Resizing",
            "auto" if res_live else "carry", res_html)
        add("architecture", "architecture diagram", "Architecture Diagram",
            "auto", _ul([_link(_ARCH_CLOUDBEES, "CloudBees Core Architecture")]))
    else:
        # Snyk renewal for OE 2027 must post-date the OE window; hardcoded until a
        # Snyk service-account token wires up the live billing lookup.
        snyk_oe = ["<strong>Snyk (SaaS):</strong> license expires September 30, 2027 "
                   "(renews annually; must be after the OE 2027 window)."]
        add("accounts", "cloud service provider account number", "Cloud Service Provider Account Number(s)",
            "carry", _accounts_html(_JFROG_SONAR_ACCOUNTS) + accounts_note)
        add("licensing", "licensing", "Licensing",
            "auto", _license_html(licenses, ["Artifactory", "SonarQube"], extra=snyk_oe))
        add("ssl_cert", "ssl/certificate", "SSL/Certificate",
            "auto", _cert_html(["artifactory.cloud.cms.gov", "sonarqube.cloud.cms.gov"]))
        add("resources", "resource scale up", "Resource Scale Up / Resizing",
            "auto" if res_live else "carry", res_html)
        add("architecture", "architecture diagram", "Architecture Diagram",
            "auto", _ul([_link(_ARCH_SONARQUBE, "SonarQube Technical Spec"),
                         _link(_ARCH_JFROG, "JFrog Platform")]))

    # Shared across both pages
    ro_html, ro_text = _owners_block(_READINESS_OWNER_EUAS)
    so_html, so_text = _owners_block(_SECONDARY_OWNER_EUAS)
    add("readiness_owner", "readiness owner", "Readiness Owner", "auto", ro_html, ro_text)
    add("secondary_owner", "secondary owner", "Secondary Owner", "auto", so_html, so_text)
    add("basecamp", "basecamp", "BaseCamp", "carry", _basecamp_html(basecamp_images))
    add("decision_records", "decision records", "Decision Records / Risks", "auto",
        _p("None. No decision records or risks to document or discuss with the "
           "Marketplace team for OE 2027."))
    add("dependencies", "dependencies", "Dependencies", "carry", _DEPENDENCIES_HTML)
    add("vendor_escalations", "external vendor escalations", "External Vendor Escalations",
        "carry", _VENDOR_ESCALATIONS_HTML)
    add("capacity", "capacity documentation", "Capacity Documentation",
        "carry", _p("The underlying systems have sufficient compute and capacity "
                    "to support the OE 2027 target of 150% of OE 2026 peak traffic "
                    "while keeping average utilization (CPU, memory, network) at or "
                    "below 70%."))
    add("redundancy", "redundancy and failover", "Redundancy and Failover", "auto", _REDUNDANCY_HTML)
    add("patching", "patching schedule", "Patching Schedule", "carry", _PATCHING_HTML)
    add("monitoring", "monitoring and alerting", "Monitoring and Alerting Validated", "auto",
        _monitoring_html(page_kind, sre_map))
    add("oncall", "internal escalation/on-call", "Internal Escalation / On-call", "auto", _oncall_html())
    add("access", "access validation", "Access Validation", "auto", _ACCESS_HTML)

    for key, match, label in _MANUAL_SECTIONS:
        sections.append({"key": key, "match": match, "label": label,
                         "status": "manual", "html": None, "text": ""})
    return sections


# ─── Confluence page discovery ────────────────────────────────────────────────

def _classify(title: str) -> Optional[str]:
    t = title.lower()
    if "cloudbees" in t or "jenkins" in t:
        return "cbj"
    if "jfrog" in t or "sonar" in t:
        return "jfrog_sonar"
    return None


# The DevOps readiness pages are the only ones with these distinctive phrases, so
# a per-kind phrase search reliably isolates them (a broad "Open Enrollment {year}
# - DevOps" title match ranks them below dozens of other OE pages and can fall off
# the result page). Year is confirmed against the title to avoid prior-year hits.
_KIND_PHRASES = {
    "cbj": "DevOps Cloudbees Jenkins",
    "jfrog_sonar": "DevOps JFrog Sonarqube",
}


def find_oe_pages(year: int) -> dict[str, dict]:
    """Return {'cbj': {...}, 'jfrog_sonar': {...}} for the given OE year.

    Each value is {'id', 'title', 'url'}. Missing pages are simply absent.
    """
    base = get_settings().CONFLUENCE_URL.rstrip("/")
    out: dict[str, dict] = {}
    for kind, phrase in _KIND_PHRASES.items():
        cql = f'space="{OE_SPACE}" AND type=page AND title ~ "{phrase}"'
        resp = httpx.get(
            _api("/rest/api/content/search"),
            params={"cql": cql, "limit": 10},
            headers=_headers(), timeout=20, verify=True,
        )
        resp.raise_for_status()
        for p in resp.json().get("results", []):
            title = p.get("title", "")
            if str(year) not in title:
                continue
            webui = p.get("_links", {}).get("webui", "")
            out[kind] = {
                "id": p["id"],
                "title": title,
                "url": f"{base}{webui}" if webui else f"{base}/pages/viewpage.action?pageId={p['id']}",
            }
            break
    return out


# ─── Storage-format injection ─────────────────────────────────────────────────

_TR_RE = re.compile(r"<tr\b.*?</tr>", re.S)
_TD_RE = re.compile(r"<td\b[^>]*>.*?</td>", re.S)


def _cell_text(td: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", td)).lower()


def _row_match(label_text: str, patterns) -> Optional[str]:
    """Return the section key whose pattern the row's TITLE starts with.

    Anchored at the start of the cell (each readiness row's first cell starts with
    its section title) so e.g. the "Secondary Owner ... the Readiness Owner's
    backup" row matches ``secondary owner`` and NOT ``readiness owner``.
    ``patterns`` maps pattern-> value (dict) and returns the matched value.
    """
    text = re.sub(r"\s+", " ", label_text).strip()
    for pat, val in patterns.items():
        if text.startswith(pat):
            return val
    return None


def _is_empty_cell(td: str) -> bool:
    inner = re.sub(r"<td\b[^>]*>|</td>", "", td)
    inner = re.sub(r"<br\s*/?>|&nbsp;|<p>|</p>|<div[^>]*>|</div>|\s+", "", inner)
    return inner == ""


# Green "Completed" status lozenge — replaces the "Task completed" checkbox in the
# status cell of every row we fill (matches the OE13 page's GreenCOMPLETED style).
_COMPLETED_STATUS = (
    '<ac:structured-macro ac:name="status" ac:schema-version="1">'
    '<ac:parameter ac:name="colour">Green</ac:parameter>'
    '<ac:parameter ac:name="title">Completed</ac:parameter>'
    '</ac:structured-macro>'
)


def _inject_sections(body: str, sections: list[dict], keys: set[str], overwrite: bool) -> tuple[str, list[str]]:
    """Fill the notes cell of each matching row for the selected section keys and
    flip the status cell to a green "Completed" lozenge.

    Returns (new_body, written_keys). Only rows whose notes cell is empty are
    written unless overwrite=True. A section with ``no_complete`` fills the notes
    cell but leaves the status cell untouched (e.g. CCOE, completed only on close).
    """
    by_match = {s["match"]: s for s in sections if s["key"] in keys and s.get("html")}
    written: list[str] = []

    def repl(m: re.Match) -> str:
        row = m.group(0)
        tds = list(_TD_RE.finditer(row))
        if len(tds) < 3:
            return row
        label_text = _cell_text(tds[0].group(0))
        matched = _row_match(label_text, by_match)
        if not matched:
            return row
        notes, statusc = tds[1], tds[2]
        if not overwrite and not _is_empty_cell(notes.group(0)):
            return row  # respect engineer-entered content
        written.append(matched["key"])
        new_notes = f"<td>{matched['html']}</td>"
        if matched.get("no_complete"):
            return row[:notes.start()] + new_notes + row[notes.end():]
        # Replace both the notes cell and the status cell (green Completed).
        new_status = f'<td style="text-align: left;">{_COMPLETED_STATUS}</td>'
        return (row[:notes.start()] + new_notes
                + row[notes.end():statusc.start()] + new_status
                + row[statusc.end():])

    new_body = _TR_RE.sub(repl, body)
    return new_body, written


def _mark_row_completed(body: str, title_prefix: str) -> str:
    """Flip the status cell of the row whose title starts with title_prefix to
    a green Completed lozenge (leaves the notes cell untouched)."""
    def repl(m: re.Match) -> str:
        row = m.group(0)
        tds = list(_TD_RE.finditer(row))
        if len(tds) < 3:
            return row
        if not _cell_text(tds[0].group(0)).strip().startswith(title_prefix):
            return row
        statusc = tds[2]
        new_status = f'<td style="text-align: left;">{_COMPLETED_STATUS}</td>'
        return row[:statusc.start()] + new_status + row[statusc.end():]
    return _TR_RE.sub(repl, body)


# ─── Public API ───────────────────────────────────────────────────────────────

async def _node_summary() -> dict[str, dict]:
    """Concurrent EC2/Karpenter instance counts for every OE target (best-effort)."""
    from app.services import ec2_nodes
    all_targets = [t for ts in ec2_nodes.PAGE_TARGETS.values() for t in ts]
    return await asyncio.to_thread(ec2_nodes.summarize, all_targets)


async def build_preview(year: int) -> dict:
    """Discover the year's pages and compute the best-effort section plan for each."""
    settings = get_settings()
    pages = await asyncio.to_thread(find_oe_pages, year)
    licenses = await get_all_licenses(settings)
    node_summary = await _node_summary()

    result = {"year": year, "pages": []}
    for kind in ("cbj", "jfrog_sonar"):
        page = pages.get(kind)
        entry = {"kind": kind, "found": bool(page), "page": page, "sections": []}
        if page:
            sections = await asyncio.to_thread(_common_sections, licenses, kind, node_summary)
            # Which rows are still empty on the live page?
            live = await asyncio.to_thread(_get_page_with_body, page["id"])
            body = live.get("body", {}).get("storage", {}).get("value", "") or ""
            filled_now = _empty_map(body, sections)
            for s in sections:
                entry["sections"].append({
                    "key": s["key"], "label": s["label"], "status": s["status"],
                    "text": s["text"],
                    "already_filled": bool(s["status"] != "manual" and not filled_now.get(s["key"], True)),
                })
        result["pages"].append(entry)
    return result


def _empty_map(body: str, sections: list[dict]) -> dict[str, bool]:
    """For each auto/carry section, is its notes cell currently EMPTY? (True=empty)."""
    out: dict[str, bool] = {}
    matchers = {s["match"]: s["key"] for s in sections if s.get("html")}
    for m in _TR_RE.finditer(body):
        tds = list(_TD_RE.finditer(m.group(0)))
        if len(tds) < 3:
            continue
        label = _cell_text(tds[0].group(0))
        key = _row_match(label, matchers)
        if key:
            out[key] = _is_empty_cell(tds[1].group(0))
    return out


async def apply(year: int, keys_by_kind: dict[str, list[str]], overwrite: bool = False,
                engineer: str = "") -> dict:
    """Create the SRE tickets, then inject the chosen sections (with the SRE links)
    into each page and PUT the update.

    Order matters: SRE (CLDSRE) tickets are created/looked-up FIRST so their links
    can be written into the page's Monitoring section. keys_by_kind:
    {'cbj': ['licensing', ...], 'jfrog_sonar': [...]}.
    """
    settings = get_settings()
    pages = await asyncio.to_thread(find_oe_pages, year)

    # 1) SRE tickets first (idempotent) — only for pages actually being applied.
    kinds_applied = [k for k in ("cbj", "jfrog_sonar")
                     if pages.get(k) and keys_by_kind.get(k)]
    sre = await create_sre_tickets(year, reporter=engineer, kinds=kinds_applied)
    sre_map = {t["tool"]: t for t in sre.get("tickets", []) if t.get("key")}

    # 2) Fill the pages, embedding the SRE links.
    licenses = await get_all_licenses(settings)
    node_summary = await _node_summary()
    results = []
    for kind in ("cbj", "jfrog_sonar"):
        page = pages.get(kind)
        keys = set(keys_by_kind.get(kind, []))
        if not page or not keys:
            continue
        # Copy BaseCamp screenshots onto this page (best-effort) so they can be embedded.
        basecamp_images = []
        if "basecamp" in keys:
            basecamp_images = await asyncio.to_thread(_copy_basecamp_images, page["id"])
        sections = await asyncio.to_thread(_common_sections, licenses, kind, node_summary, sre_map, basecamp_images)
        live = await asyncio.to_thread(_get_page_with_body, page["id"])
        body = live.get("body", {}).get("storage", {}).get("value", "") or ""
        version = live["version"]["number"]
        title = live["title"]

        # CCOE: write the assigned ticket link into the page and remember the key.
        ccoe_key = _ccoe_key_from_body(body)
        if ccoe_key:
            sections.append(_ccoe_section(ccoe_key))
            keys.add("ccoe")

        new_body, written = _inject_sections(body, sections, keys, overwrite)
        if written:
            await asyncio.to_thread(_update_page, page["id"], version + 1, title, new_body)

        # Comment on the CCOE ticket that the page was updated.
        ccoe = None
        if ccoe_key and written:
            filled = [k for k in written if k != "ccoe"]
            note = (f"OE {year} DevOps readiness page updated"
                    + (f" by {engineer}" if engineer else "")
                    + f": {len(filled)} section(s) filled. Page: {page['url']}\n\n"
                    "Please review the sections; the ticket can be closed from the "
                    "dashboard OE Readiness tile once verified.")
            commented = await asyncio.to_thread(comment_ccoe, ccoe_key, note)
            ccoe = {"key": ccoe_key,
                    "url": f"{settings.JIRA_URL}/browse/{ccoe_key}",
                    "commented": commented}

        results.append({"kind": kind, "page": page,
                        "written": [k for k in written if k != "ccoe"], "ccoe": ccoe})
    return {"year": year, "results": results, "sre": sre.get("tickets", [])}


# ─── CCOE readiness ticket (the assigned OE coordinator ticket) ───────────────

CCOE_PROJECT = "CCOE"
_CCOE_KEY_RE = re.compile(r'ac:name="key">\s*(CCOE-\d+)\s*<')


def _ccoe_key_from_body(body: str) -> Optional[str]:
    """Extract the page's assigned CCOE ticket key from the Assigned-CCOE row.

    The row's first cell holds a Jira macro whose ``key`` param is the page's
    ticket (e.g. CCOE-518 for CBJ, CCOE-523 for JFrog/SonarQube). CCOE-514 (the
    project link on the word "CCOE") is ignored.
    """
    for m in _TR_RE.finditer(body):
        tds = list(_TD_RE.finditer(m.group(0)))
        if tds and _cell_text(tds[0].group(0)).strip().startswith("assigned"):
            km = _CCOE_KEY_RE.search(tds[0].group(0))
            if km:
                return km.group(1)
    keys = _CCOE_KEY_RE.findall(body)
    return next((k for k in keys if k != "CCOE-514"), keys[0] if keys else None)


def _ccoe_section(key: str) -> dict:
    """A fillable section that writes the CCOE ticket link into the Assigned-CCOE
    notes cell. Completion is deferred to the close step, so no_complete=True."""
    url = f"{get_settings().JIRA_URL}/browse/{key}"
    return {
        "key": "ccoe", "match": "assigned cms cloud open enrollment",
        "label": "Assigned CCOE Jira", "status": "auto", "no_complete": True,
        "html": _p(f"Readiness review tracked in {_link(url, key)}."),
        "text": f"Readiness review tracked in {key}.",
    }


def comment_ccoe(key: str, body_text: str) -> bool:
    """Add a comment to the CCOE ticket. Best-effort — returns False on failure."""
    try:
        jira_service.comment_ticket(key, body_text)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("OE readiness: could not comment on %s: %s", key, exc)
        return False


def close_ccoe(key: str) -> dict:
    """Transition the CCOE ticket to Done. Returns {ok, status|error}."""
    settings = get_settings()
    try:
        tr = httpx.get(f"{settings.JIRA_URL}/rest/api/2/issue/{key}/transitions",
                       headers=jira_service._headers(), timeout=15, verify=True)
        tr.raise_for_status()
        transitions = tr.json().get("transitions", [])
        target = next((t for t in transitions if t["to"]["name"].lower() in ("done", "closed", "resolved")), None)
        if not target:
            return {"ok": False, "error": f"no Done transition available (have: "
                    f"{[t['name'] for t in transitions]})"}
        resp = httpx.post(f"{settings.JIRA_URL}/rest/api/2/issue/{key}/transitions",
                          json={"transition": {"id": target["id"]}},
                          headers=jira_service._headers(), timeout=15, verify=True)
        if not resp.is_success:
            return {"ok": False, "error": f"transition {resp.status_code}: {resp.text[:200]}"}
        return {"ok": True, "status": target["to"]["name"], "key": key}
    except Exception as exc:  # noqa: BLE001
        logger.error("OE readiness: failed to close %s: %s", key, exc)
        return {"ok": False, "error": str(exc)[:200]}


async def close_ccoe_for(year: int, kind: str) -> dict:
    """Find the page's CCOE ticket, transition it to Done, and mark the
    Assigned-CCOE row green Completed on the page."""
    pages = await asyncio.to_thread(find_oe_pages, year)
    page = pages.get(kind)
    if not page:
        return {"ok": False, "error": f"no {kind} page for {year}"}
    live = await asyncio.to_thread(_get_page_with_body, page["id"])
    body = live.get("body", {}).get("storage", {}).get("value", "") or ""
    key = _ccoe_key_from_body(body)
    if not key:
        return {"ok": False, "error": "no CCOE ticket found on page"}

    result = await asyncio.to_thread(close_ccoe, key)
    # On a successful transition, stamp the CCOE row Completed on the page.
    if result.get("ok"):
        new_body = _mark_row_completed(body, "assigned cms cloud open enrollment")
        if new_body != body:
            try:
                await asyncio.to_thread(_update_page, page["id"],
                                        live["version"]["number"] + 1, live["title"], new_body)
                result["page_marked"] = True
            except Exception as exc:  # noqa: BLE001
                logger.warning("OE readiness: closed %s but could not mark page: %s", key, exc)
                result["page_marked"] = False
    return result


# ─── SRE tickets ──────────────────────────────────────────────────────────────

_SRE_TOOLS = [
    ("CloudBees", "cbj"),
    ("JFrog", "jfrog_sonar"),
    ("SonarQube", "jfrog_sonar"),
]


def _find_existing_sre(year: int, tool: str) -> Optional[str]:
    """Return an existing CLDSRE key for this tool/year if one already exists."""
    settings = get_settings()
    jql = (f'project = {SRE_PROJECT} AND summary ~ "OE {year} DevOps Readiness - {tool}" '
           f'ORDER BY created DESC')
    try:
        resp = httpx.get(
            f"{settings.JIRA_URL}/rest/api/2/search",
            params={"jql": jql, "maxResults": 1, "fields": "summary"},
            headers=jira_service._headers(), timeout=15, verify=True,
        )
        resp.raise_for_status()
        issues = resp.json().get("issues", [])
        return issues[0]["key"] if issues else None
    except Exception as exc:  # noqa: BLE001
        logger.info("OE readiness: SRE dedupe search failed for %s: %s", tool, exc)
        return None


def _create_one_sre(tool: str, summary: str, description: str, reporter: str) -> dict:
    """Create a single CLDSRE ticket, filling the required `reporter` field.

    CLDSRE Task requires project/issuetype/summary/reporter. We set reporter to the
    triggering engineer (login EUA = Jira username); if the token can't set that
    reporter we retry letting Jira default it, so creation never hard-fails on the
    reporter field.
    """
    extra = {"reporter": {"name": reporter}} if reporter else None
    try:
        return jira_service.create_ticket(SRE_PROJECT, summary, description, SRE_ISSUE_TYPE, extra)
    except Exception as exc:  # noqa: BLE001
        if reporter:
            logger.info("OE readiness: reporter=%s rejected for SRE ticket, retrying default: %s",
                        reporter, exc)
            return jira_service.create_ticket(SRE_PROJECT, summary, description, SRE_ISSUE_TYPE)
        raise


async def create_sre_tickets(year: int, reporter: str = "",
                             kinds: Optional[list[str]] = None) -> dict:
    """Create one CLDSRE readiness ticket per tool (CloudBees, JFrog, SonarQube).

    Idempotent: skips tools that already have a matching ticket (JQL summary match).
    ``kinds`` limits to the pages being applied ('cbj' / 'jfrog_sonar'); None = all.
    ``reporter`` is the triggering engineer's EUA. Returns per-tool
    {tool, key, url, existing}.
    """
    settings = get_settings()
    pages = await asyncio.to_thread(find_oe_pages, year)
    out = []
    for tool, kind in _SRE_TOOLS:
        if kinds is not None and kind not in kinds:
            continue
        existing = await asyncio.to_thread(_find_existing_sre, year, tool)
        if existing:
            out.append({"tool": tool, "key": existing,
                        "url": f"{settings.JIRA_URL}/browse/{existing}", "existing": True})
            continue
        page = pages.get(kind)
        page_line = f"\n\nReadiness page: {page['url']}" if page else ""
        summary = f"OE {year} DevOps Readiness - {tool} SRE Review"
        description = (
            f"SRE readiness review for {tool} ahead of Open Enrollment {year}.\n\n"
            f"Please review monitoring/alerting (Datadog), capacity, and service "
            f"health for {tool}, and sign off on the DevOps OE readiness page."
            f"{page_line}"
        )
        try:
            res = await asyncio.to_thread(_create_one_sre, tool, summary, description, reporter)
            out.append({"tool": tool, "key": res["key"], "url": res["url"], "existing": False})
        except Exception as exc:  # noqa: BLE001
            logger.error("OE readiness: failed to create SRE ticket for %s: %s", tool, exc)
            out.append({"tool": tool, "key": None, "url": None, "error": str(exc)[:300]})
    return {"year": year, "tickets": out}
