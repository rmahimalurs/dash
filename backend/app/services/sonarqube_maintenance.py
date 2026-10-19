"""SonarQube Server release-notes lookup via SonarSource's public Jira.

SonarQube versions are ``2026.4.1.126914`` (year.release.patch.build). A build's
release notes are the issues filed under the Jira fix version
``sqs-<year.release.patch>`` in SonarSource's public SONAR project (id 10139).
The Jira REST API is public (no auth), so this is a read-only lookup mirroring
how the JFrog/CBJ modals surface release notes.
"""
import logging
from urllib.parse import quote

import httpx

logger = logging.getLogger(__name__)

_JIRA_BASE = "https://sonarsource.atlassian.net"
_SONAR_PROJECT_ID = "10139"
_VERSION_PREFIX = "sqs-"   # Jira fix-version names look like "sqs-2026.4.1"


def _display_version(build: str) -> str:
    """Strip the trailing build number: 2026.4.1.126914 -> 2026.4.1."""
    parts = (build or "").strip().split(".")
    return ".".join(parts[:3]) if len(parts) >= 4 else (build or "").strip()


def _find_fix_version_id(client: httpx.Client, name: str) -> str | None:
    resp = client.get(f"{_JIRA_BASE}/rest/api/3/project/{_SONAR_PROJECT_ID}/versions")
    resp.raise_for_status()
    for v in resp.json():
        if v.get("name") == name:
            return str(v.get("id"))
    return None


def fetch_sonarqube_release_notes(version: str) -> dict:
    """Return the resolved issues for a SonarQube build's release.

    Returns ``{available, version, count, entries:[{key,summary,type,url}],
    source_url}``. Best-effort: any failure yields ``{available: False, error}``
    so the modal degrades gracefully.
    """
    display = _display_version(version)
    jira_name = f"{_VERSION_PREFIX}{display}"
    fallback_url = f"{_JIRA_BASE}/projects/SONAR"
    try:
        with httpx.Client(timeout=15, verify=True, follow_redirects=True) as client:
            vid = _find_fix_version_id(client, jira_name)
            if not vid:
                return {
                    "available": False, "version": display,
                    "error": f"No SonarSource release found for {jira_name}",
                    "source_url": fallback_url,
                }
            jql = (f"project = {_SONAR_PROJECT_ID} AND fixVersion = {vid} "
                   f"AND issuetype != Maintenance ORDER BY issuetype ASC, key ASC")
            resp = client.get(
                f"{_JIRA_BASE}/rest/api/3/search/jql",
                params={"jql": jql, "fields": "key,summary,issuetype", "maxResults": 100},
            )
            resp.raise_for_status()
            entries = []
            for it in resp.json().get("issues", []):
                f = it.get("fields", {})
                key = it.get("key")
                entries.append({
                    "key": key,
                    "summary": f.get("summary", ""),
                    "type": (f.get("issuetype") or {}).get("name", ""),
                    "url": f"{_JIRA_BASE}/browse/{key}",
                })
            source_url = (f"{_JIRA_BASE}/issues?jql="
                          + quote(f"project = 10139 AND fixVersion = {vid} AND issuetype != Maintenance"))
            return {
                "available": True, "version": display, "count": len(entries),
                "entries": entries, "source_url": source_url,
            }
    except Exception as exc:  # noqa: BLE001 — release notes are non-fatal
        logger.warning("SonarQube release notes fetch failed for %s: %s", version, exc)
        return {"available": False, "version": display, "error": str(exc), "source_url": fallback_url}
