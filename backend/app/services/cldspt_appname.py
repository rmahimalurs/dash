"""Work out which CMS application a GitHub access request belongs to.

The Application Name field is what makes a ticket actionable: Jira cascades
the Primary Approver, Backup Approver and Business Owner off it, so a blank
one is why 36 of the open requests have nobody to approve them.

Two signals, in the order Swamy described them:

1. The justification text on the ticket, which names the system in prose.
   The candidate patterns here follow the ones in the team's
   create_github_cldspt_tickets.py, which were tuned against real tickets.
2. The requester's AD groups, when the prose says nothing useful. CMS group
   names encode the application: ``ct-ado-<application>-<role>`` and
   ``<APPLICATION>_USER_<ENV>``.

Both produce *candidates*, not answers. A candidate is only promoted to a
name when the live CMDB catalog confirms it, and the result always says which
signal it came from so a reader can judge it. Nothing here writes to Jira:
setting Application Name triggers Jira's own cascade, which emails the
second-stage approver before any Business Owner has signed off.
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# Ordered most specific first; the first candidate the catalog confirms wins.
CANDIDATE_PATTERNS = [
    re.compile(r"FISMA ID:?\s*([A-Za-z0-9][A-Za-z0-9 \-]{1,20}[A-Za-z0-9])", re.IGNORECASE),
    # A real capitalized acronym inside parens: "(CERT RC, Contract #...)".
    # Case-sensitive on purpose so it does not match ordinary prose.
    re.compile(r"\(([A-Z][A-Z0-9]{1,9}(?:[ \-][A-Z][A-Z0-9]{1,9}){0,2})[,)]"),
    # The same shape named in plain prose: "Migration of CERT RC application".
    re.compile(r"\b([A-Z]{2,10}(?:[ \-][A-Z]{2,10}){1,2})\b"),
    re.compile(r"system:?\s*([A-Za-z0-9][A-Za-z0-9 \-/]{1,30}?)[;.,\n]", re.IGNORECASE),
    re.compile(r"Project Name:?\s*([A-Za-z0-9][A-Za-z0-9 \-/&]{2,100}?)(?:\s+[Cc]ontract|[.\n(])", re.IGNORECASE),
    # "the HealthEdge ClaimsCore contract": a CamelCase compound in prose.
    re.compile(r"\b([A-Z][a-z]{2,}[A-Z][A-Za-z0-9]{2,})\b"),
    # Lowest confidence: a bare ALL-CAPS token. Heavily filtered below.
    re.compile(r"\b([A-Z][A-Z0-9]{1,7})\b"),
]

# Tools, platforms and org boilerplate that appear in these justifications
# constantly and are never the application being requested.
GENERIC_TERMS = {
    "IT", "US", "AWS", "OIT", "VPN", "COR", "PHI", "PII", "CMS", "OC", "CO",
    "CTR", "NA", "ID", "LAN", "KMS", "RPA", "SSH", "API", "URL", "PR", "CI",
    "DEVOPS", "GITHUB", "GIT", "COPILOT", "CO-PILOT", "ENT", "EUA", "SDLC",
    "CLOUDTAMER", "KION", "SPLUNK", "ARTIFACTORY", "ZSCALER", "SERVICENOW",
    "SHAREPOINT", "JIRA", "CONFLUENCE", "TEAMS", "OUTLOOK", "SLACK", "ZOOM",
    "WEBEX", "EMAIL", "HIDM", "EDITOR", "ADMIN", "USER", "PROD", "DEV", "TEST",
    "IMP", "UAT", "QA", "SOC", "ISSO", "ADO", "GSA", "HHS", "CCSQ", "OHTP",
    # The GitHub org itself shows up in almost every justification.
    "CMS-ENTERPRISE", "CMSENTERPRISE", "ENTERPRISE", "CMS ENTERPRISE",
    # Access and contract boilerplate.
    "SOW", "LLC", "INC", "TEAM", "PMO", "GTL", "COTR", "IDIQ", "TO", "RFP",
    # Generic tooling that is never the application being requested.
    "SAS", "SQL", "ETL", "SSO", "MFA", "IAM", "RDS", "EC2", "S3", "VPC",
    "JENKINS", "SONARQUBE", "SNYK", "DOCKER", "KUBERNETES", "TERRAFORM",
    "HEALTHEDGE", "PERATON", "GDIT", "DEI",
}

# A candidate is only trustworthy enough to label a ticket with when the
# catalog confirms it AND it is not one of these near-misses: short tokens
# that match something in the catalog by coincidence.
MIN_CONFIRMED_LENGTH = 3

# AD groups that say nothing about an application.
GENERIC_GROUPS = {
    "non_cms_emp_vpn", "cloud_eua_users", "cms_emp_vpn", "domain users",
}

# ct-ado-<application>-<role>: the trailing role words are not the application.
_AD_ROLE_WORDS = {
    "readonly", "developer", "admin", "application", "support", "tester",
    "user", "users", "poweruser", "operator", "ops", "cloudops", "security",
    "auditor", "billing", "owner", "lead", "prd", "prod", "imp", "dev",
    "test", "uat", "sandbox", "nonprod",
}


def candidates_from_justification(text: str | None) -> list[str]:
    """Candidate application names in prose order, most specific pattern first."""
    text = text or ""
    out: list[str] = []
    seen: set[str] = set()
    for pattern in CANDIDATE_PATTERNS:
        for m in pattern.finditer(text):
            term = (m.group(1) or "").strip(" -")
            if not term or term.upper() in GENERIC_TERMS:
                continue
            # "CMS VPN" and "CMS IT" are noise the bare word already covers.
            if _strip_org_prefix(term).upper() in GENERIC_TERMS:
                continue
            if term.upper() in seen:
                continue
            seen.add(term.upper())
            out.append(term)
    return out


def candidates_from_ad_groups(groups: list[str]) -> list[str]:
    """Candidate application names out of CMS AD group names.

    ``ct-ado-claimscorevendora-application-admin`` yields
    ``claimscorevendora``; ``CFACTS_USER_PRD`` yields ``CFACTS``. Role and
    environment words are stripped, and groups that describe access rather
    than an application are skipped entirely.
    """
    out: list[str] = []
    seen: set[str] = set()

    def add(term: str) -> None:
        term = term.strip(" -_")
        if len(term) < 3 or term.upper() in GENERIC_TERMS or term.upper() in seen:
            return
        seen.add(term.upper())
        out.append(term)

    for raw in groups or []:
        name = (raw or "").strip()
        if not name or name.lower() in GENERIC_GROUPS:
            continue

        m = re.match(r"^ct-ado-(.+)$", name, re.I)
        if m:
            parts = [p for p in m.group(1).split("-") if p]
            kept = [p for p in parts if p.lower() not in _AD_ROLE_WORDS]
            if kept:
                add("-".join(kept))
            continue

        # VPN-CCE, VPN-BIA-INFA: the application follows the prefix.
        m = re.match(r"^VPN[-_](.+)$", name, re.I)
        if m:
            add(m.group(1).replace("_", "-"))
            continue

        # CFACTS_USER_PRD, DEI_GDIT_Users: leading token is the application.
        if "_" in name:
            head = name.split("_")[0]
            add(head)
            continue

    return out


def infer(justification: str | None, ad_groups: list[str] | None,
          catalog_lookup=None) -> dict:
    """Best guess at the application for one ticket.

    ``catalog_lookup`` takes a candidate string and returns the confirmed
    catalog name, or None. When it is not supplied, candidates are returned
    unconfirmed so the caller can show them as a guess rather than a fact.
    """
    from_just = candidates_from_justification(justification)
    from_ad = candidates_from_ad_groups(ad_groups or [])

    for source, candidates in (("justification", from_just), ("ad_groups", from_ad)):
        for candidate in candidates:
            if catalog_lookup is None:
                continue
            try:
                confirmed = catalog_lookup(candidate)
            except Exception as exc:  # noqa: BLE001 — a catalog miss is not fatal
                logger.warning("Application catalog lookup failed for %r: %s", candidate, exc)
                confirmed = None
            if confirmed and len(str(confirmed)) >= MIN_CONFIRMED_LENGTH:
                return {
                    "name": confirmed,
                    "source": source,
                    "matched_on": candidate,
                    "confirmed": True,
                    "candidates": {"justification": from_just, "ad_groups": from_ad},
                }

    # Nothing confirmed. Offer the strongest candidate as an explicit guess.
    best = from_just[0] if from_just else (from_ad[0] if from_ad else None)
    return {
        "name": best,
        "source": ("justification" if from_just else "ad_groups" if from_ad else None),
        "matched_on": best,
        "confirmed": False,
        "candidates": {"justification": from_just, "ad_groups": from_ad},
    }


def _strip_org_prefix(term: str) -> str:
    """"CMS DIBA" -> "DIBA". The CMS prefix is prose, not part of the name."""
    return re.sub(r"^(?:CMS[\s\-_]+)+", "", term, flags=re.I).strip(" -_")


def variants_of(candidate: str) -> list[str]:
    """Spellings to try against the catalog.

    The catalog's naming is not predictable from prose: "ClaimsCore" in prose
    is "Claims-Core" in the catalog, and NFeed treats those as different
    searches entirely.
    """
    out = [candidate]
    stripped = _strip_org_prefix(candidate)
    if stripped and stripped != candidate:
        out.append(stripped)
    for base in list(out):
        hyphenated = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "-", base)
        if hyphenated not in out:
            out.append(hyphenated)
        if " " in base:
            for v in (base.replace(" ", "-"), base.replace(" ", "")):
                if v not in out:
                    out.append(v)
    return [v for v in out if v]
