"""
CloudBees Copy Controllers — plugin sync via CasC bundle PR.

Per-controller bundles live in CMS-Enterprise/dso-contrl-casc. Each
controller's directory inherits plugins from `CI-parent/plugins.yaml`.
This module:
  1. Reads installed plugins from the prod controller (Script Console)
  2. Reads CI-parent's plugins.yaml + plugin-catalog.yaml from git
  3. Computes the delta (plugins on prod but not in CI-parent)
  4. Writes (or extends) `<controller>-bundle/plugins.yaml` on the
     `develop` branch and bumps `<controller>-bundle/bundle.yaml`'s
     plugins-reference / version fields
  5. Opens or updates a PR from `develop` to `main` with a summary
     of the delta and which plugins aren't in the catalog
"""

from __future__ import annotations

import base64
import logging
import re
from typing import Optional

import httpx

from app.config import get_settings
from app.services.jenkins import run_groovy_script

logger = logging.getLogger(__name__)

CASC_REPO = "CMS-Enterprise/dso-contrl-casc"
CASC_PARENT_DIR = "CI-parent"
DEVELOP_BRANCH = "develop"
MAIN_BRANCH = "main"

# Re-use the prod URL / auth resolver from copy_controller
from app.services.copy_controller import _prod_controller_url, _prod_auth, _detect_groovy_trace


# ─── 1. Discover installed plugins on prod controller ─────────────────────────

_GROOVY_LIST_PLUGINS = r"""
def plugins = Jenkins.instance.pluginManager.plugins.collect { p ->
  p.shortName + "=" + p.version
}
println "BEGIN_PLUGINS"
plugins.sort().each { println it }
println "END_PLUGINS"
"""


def discover_prod_plugins(controller_name: str) -> dict:
    """Return list of {shortName, version} for all plugins installed on the prod controller."""
    auth = _prod_auth()
    if not auth:
        return {"plugins": [], "error": "No Jenkins prod-east credentials configured"}

    try:
        out = run_groovy_script(_prod_controller_url(controller_name), _GROOVY_LIST_PLUGINS, auth=auth)
    except Exception as exc:
        logger.warning("Plugin discovery for %s failed: %s", controller_name, exc)
        return {"plugins": [], "error": f"Controller lookup failed: {exc}"}

    out = (out or "").strip()
    trace = _detect_groovy_trace(out)
    if trace:
        return {"plugins": [], "error": f"Groovy error: {trace}"}

    m = re.search(r"BEGIN_PLUGINS\s*\n(.*?)\nEND_PLUGINS", out, re.DOTALL)
    if not m:
        return {"plugins": [], "error": f"Unexpected output: {out[:200]}"}

    plugins: list[dict] = []
    for line in m.group(1).splitlines():
        line = line.strip()
        if not line or "=" not in line:
            continue
        name, _, ver = line.partition("=")
        plugins.append({"shortName": name.strip(), "version": ver.strip()})
    return {"plugins": plugins, "error": None}


# ─── 2. GitHub helpers (read / write / PR) ────────────────────────────────────

def _gh_headers() -> dict:
    token = get_settings().GITHUB_TOKEN
    if not token:
        raise RuntimeError("GITHUB_TOKEN is not configured")
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _gh_get_file(path: str, ref: str) -> Optional[dict]:
    """Return {'content': str, 'sha': str} or None if 404."""
    url = f"https://api.github.com/repos/{CASC_REPO}/contents/{path}"
    resp = httpx.get(url, params={"ref": ref}, headers=_gh_headers(), timeout=15)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    data = resp.json()
    if data.get("type") != "file":
        return None
    return {
        "content": base64.b64decode(data["content"]).decode("utf-8"),
        "sha":     data["sha"],
    }


def _gh_put_file(path: str, content: str, message: str, branch: str, sha: Optional[str]) -> dict:
    url = f"https://api.github.com/repos/{CASC_REPO}/contents/{path}"
    payload = {
        "message": message,
        "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
        "branch":  branch,
    }
    if sha:
        payload["sha"] = sha
    resp = httpx.put(url, json=payload, headers=_gh_headers(), timeout=30)
    if not resp.is_success:
        raise RuntimeError(f"GitHub PUT {path} failed: {resp.status_code} {resp.text[:300]}")
    return resp.json()


def _gh_find_pr(head: str, base: str) -> Optional[dict]:
    """Find an open PR from head → base."""
    url = f"https://api.github.com/repos/{CASC_REPO}/pulls"
    # GitHub requires `org:head` for cross-fork; for same-repo just the branch name
    resp = httpx.get(url, params={"head": f"CMS-Enterprise:{head}", "base": base, "state": "open"},
                     headers=_gh_headers(), timeout=15)
    resp.raise_for_status()
    prs = resp.json()
    return prs[0] if prs else None


def _gh_open_pr(title: str, body: str, head: str, base: str) -> dict:
    url = f"https://api.github.com/repos/{CASC_REPO}/pulls"
    resp = httpx.post(url, json={"title": title, "body": body, "head": head, "base": base},
                      headers=_gh_headers(), timeout=20)
    if not resp.is_success:
        raise RuntimeError(f"GitHub PR open failed: {resp.status_code} {resp.text[:300]}")
    return resp.json()


def _gh_update_pr_body(pr_number: int, body: str) -> None:
    url = f"https://api.github.com/repos/{CASC_REPO}/pulls/{pr_number}"
    resp = httpx.patch(url, json={"body": body}, headers=_gh_headers(), timeout=15)
    resp.raise_for_status()


# ─── 3. plugins.yaml + plugin-catalog.yaml parsing ────────────────────────────

_PLUGINS_ID_RE = re.compile(r"^\s*-\s*id:\s*([A-Za-z0-9_\-]+)\s*$")


def _parse_plugin_ids(plugins_yaml: str) -> set[str]:
    """Pull plugin IDs out of a plugins.yaml. Lines starting with `#` are ignored."""
    ids: set[str] = set()
    for line in plugins_yaml.splitlines():
        if line.lstrip().startswith("#"):
            continue
        m = _PLUGINS_ID_RE.match(line)
        if m:
            ids.add(m.group(1))
    return ids


# Catalog format: keys directly under `includePlugins:` are plugin shortNames.
# Lines starting with `#` are commented and skipped.
_CATALOG_KEY_RE = re.compile(r"^(\s*)([A-Za-z0-9_\-]+):\s*$")


def _parse_catalog_ids(catalog_yaml: str) -> set[str]:
    """Pull plugin shortNames out of plugin-catalog.yaml's includePlugins map."""
    ids: set[str] = set()
    in_include = False
    include_indent: Optional[int] = None
    for line in catalog_yaml.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        if stripped.startswith("includePlugins:"):
            in_include = True
            include_indent = len(line) - len(stripped)
            continue
        if in_include:
            indent = len(line) - len(stripped)
            if stripped and indent <= (include_indent or 0):
                in_include = False
                continue
            m = _CATALOG_KEY_RE.match(line)
            # plugin name is at exactly 2 levels of indent below includePlugins typically
            if m and not stripped.startswith("version"):
                ids.add(m.group(2))
    return ids


# ─── 4. bundle.yaml manipulation ──────────────────────────────────────────────

def _ensure_bundle_yaml(existing: Optional[str], controller_name: str) -> tuple[str, bool]:
    """
    Return (updated_bundle_yaml, changed). Ensures:
    - parent: CI-parent
    - plugins: ["plugins.yaml"] is declared
    - version is bumped if changes are made
    """
    if not existing:
        body = (
            f'apiVersion: "2"\n'
            f'id: "{controller_name}-bundle"\n'
            f'description: "Auto-generated for {controller_name} (Copy Controllers)"\n'
            f'version: "1"\n'
            f'parent: "CI-parent"\n'
            f'jcasc:\n'
            f'  - "jenkins.yaml"\n'
            f'plugins:\n'
            f'  - "plugins.yaml"\n'
        )
        return body, True

    text = existing
    changed = False

    # Add a plugins: section if missing
    if "plugins:" not in text:
        text = text.rstrip() + '\nplugins:\n  - "plugins.yaml"\n'
        changed = True
    elif '"plugins.yaml"' not in text and "'plugins.yaml'" not in text and "plugins.yaml" not in text:
        # plugins: present but doesn't reference plugins.yaml
        text = re.sub(r"(plugins:\s*\n)", r'\1  - "plugins.yaml"\n', text, count=1)
        changed = True

    # Bump version (string field) if we changed anything
    if changed:
        def bump(m):
            try:
                v = int(m.group(2)) + 1
                return f'{m.group(1)}"{v}"'
            except ValueError:
                return m.group(0)
        new_text = re.sub(r'(version:\s*)"(\d+)"', bump, text, count=1)
        if new_text != text:
            text = new_text

    return text, changed


def _render_plugins_yaml(plugin_ids: list[str]) -> str:
    """Render a plugins.yaml file from a sorted list of plugin shortNames."""
    lines = ["plugins:"]
    for pid in sorted(plugin_ids):
        lines.append(f"- id: {pid}")
    return "\n".join(lines) + "\n"


# ─── 5. Main orchestration ────────────────────────────────────────────────────

def sync_plugins_to_bundle(controller_name: str) -> dict:
    """
    Sync prod controller plugins to the per-controller CasC bundle:
    - Read prod plugins
    - Read CI-parent plugins + catalog
    - Compute delta (prod plugins not already covered by CI-parent)
    - Write <controller>-bundle/plugins.yaml (merged with anything already there)
    - Ensure <controller>-bundle/bundle.yaml references plugins.yaml + version bump
    - Commit to develop, open/refresh PR develop → main

    Returns: {
      controller_name, delta: [...], catalog_gaps: [...],
      pr_url, pr_number, files_changed: [...], no_changes: bool, error: str|None
    }
    """
    prod = discover_prod_plugins(controller_name)
    if prod.get("error"):
        return {"controller_name": controller_name, "error": prod["error"]}
    prod_ids = {p["shortName"] for p in prod["plugins"]}

    parent_plugins_file = _gh_get_file(f"{CASC_PARENT_DIR}/plugins.yaml", MAIN_BRANCH)
    parent_catalog_file = _gh_get_file(f"{CASC_PARENT_DIR}/plugin-catalog.yaml", MAIN_BRANCH)
    if not parent_plugins_file:
        return {"controller_name": controller_name, "error": f"{CASC_PARENT_DIR}/plugins.yaml not found in {CASC_REPO}"}
    parent_ids   = _parse_plugin_ids(parent_plugins_file["content"])
    catalog_ids  = _parse_catalog_ids(parent_catalog_file["content"]) if parent_catalog_file else set()

    delta = sorted(prod_ids - parent_ids)
    catalog_gaps = sorted(set(delta) - catalog_ids)

    if not delta:
        return {
            "controller_name": controller_name,
            "delta": [],
            "catalog_gaps": [],
            "files_changed": [],
            "pr_url": None,
            "pr_number": None,
            "no_changes": True,
            "error": None,
            "summary": "Prod plugins are a subset of CI-parent — nothing to add to the per-controller bundle.",
        }

    bundle_dir       = f"{controller_name}-bundle"
    plugins_path     = f"{bundle_dir}/plugins.yaml"
    bundle_yaml_path = f"{bundle_dir}/bundle.yaml"

    # Use develop as the working branch (existing pattern)
    existing_plugins = _gh_get_file(plugins_path, DEVELOP_BRANCH)
    existing_bundle  = _gh_get_file(bundle_yaml_path, DEVELOP_BRANCH)

    existing_plugin_ids: set[str] = set()
    if existing_plugins:
        existing_plugin_ids = _parse_plugin_ids(existing_plugins["content"])

    merged_ids = sorted(existing_plugin_ids | set(delta))
    new_plugins_yaml = _render_plugins_yaml(merged_ids)
    new_bundle_yaml, bundle_changed = _ensure_bundle_yaml(
        existing_bundle["content"] if existing_bundle else None,
        controller_name,
    )

    plugins_unchanged = existing_plugins and existing_plugins["content"].strip() == new_plugins_yaml.strip()
    bundle_unchanged  = existing_bundle and not bundle_changed

    if plugins_unchanged and bundle_unchanged:
        return {
            "controller_name": controller_name,
            "delta": delta,
            "catalog_gaps": catalog_gaps,
            "files_changed": [],
            "pr_url": None,
            "pr_number": None,
            "no_changes": True,
            "error": None,
            "summary": "No file changes — bundle already has these plugins.",
        }

    files_changed: list[str] = []

    if not plugins_unchanged:
        _gh_put_file(
            plugins_path, new_plugins_yaml,
            message=f"copy-controllers: sync {controller_name} plugins from prod ({len(delta)} new)",
            branch=DEVELOP_BRANCH,
            sha=existing_plugins["sha"] if existing_plugins else None,
        )
        files_changed.append(plugins_path)

    if not bundle_unchanged:
        _gh_put_file(
            bundle_yaml_path, new_bundle_yaml,
            message=f"copy-controllers: ensure {controller_name}-bundle references plugins.yaml",
            branch=DEVELOP_BRANCH,
            sha=existing_bundle["sha"] if existing_bundle else None,
        )
        files_changed.append(bundle_yaml_path)

    # Open or refresh PR develop → main
    body_lines = [
        f"Sync of plugins from prod controller `{controller_name}` into "
        f"`{bundle_dir}/plugins.yaml` (delta on top of `CI-parent`).",
        "",
        f"- Plugins added to per-controller bundle: **{len(delta)}**",
        f"- Plugins not in `CI-parent/plugin-catalog.yaml` (may need catalog update): "
        f"**{len(catalog_gaps)}**",
        "",
        "<details><summary>Delta plugin list</summary>",
        "",
        "```",
        *delta,
        "```",
        "",
        "</details>",
    ]
    if catalog_gaps:
        body_lines += [
            "",
            "<details><summary>Plugins not in CI-parent catalog</summary>",
            "",
            "```",
            *catalog_gaps,
            "```",
            "",
            "</details>",
        ]

    pr_body = "\n".join(body_lines)
    pr_title = f"copy-controllers: sync {controller_name} plugins ({len(delta)} added)"

    existing_pr = _gh_find_pr(DEVELOP_BRANCH, MAIN_BRANCH)
    if existing_pr:
        # Refresh body so the latest sync's summary shows up
        try:
            _gh_update_pr_body(existing_pr["number"], pr_body)
        except Exception as exc:
            logger.warning("Could not refresh PR body: %s", exc)
        pr_url = existing_pr["html_url"]
        pr_number = existing_pr["number"]
    else:
        pr = _gh_open_pr(pr_title, pr_body, DEVELOP_BRANCH, MAIN_BRANCH)
        pr_url = pr["html_url"]
        pr_number = pr["number"]

    return {
        "controller_name": controller_name,
        "delta": delta,
        "catalog_gaps": catalog_gaps,
        "files_changed": files_changed,
        "pr_url": pr_url,
        "pr_number": pr_number,
        "no_changes": False,
        "error": None,
        "summary": (
            f"Wrote {len(files_changed)} file(s) to develop "
            f"({len(delta)} plugin(s) added, {len(catalog_gaps)} missing from catalog) "
            f"— PR #{pr_number}."
        ),
    }
