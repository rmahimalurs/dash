"""
Artifactory repository cache refresh / reindex.

Prod only. Mirrors scripts/jfrog-wipe-npm-cache.sh and
scripts/jfrog-evict-docker-cache.sh:

* Remote (proxy) repos: Artifactory's `zapCaches` REST endpoint is broken on
  our version (7.133.x / 7.146.x return a server-side NPE), so we refresh by
  DELETEing the cached folders, which forces a re-fetch from upstream on the
  next request. Either a single package/path or, as a full wipe, every
  top-level folder discovered via AQL.
* Local / Virtual repos: Recalculate Index via the per-package-type reindex
  endpoint (e.g. POST /api/npm/{repo}/reindex).
"""
import logging
from concurrent.futures import ThreadPoolExecutor

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

_ART = "/artifactory"

# Per-package-type reindex endpoints for LOCAL/VIRTUAL repos.
# Value is a builder that returns the path relative to the Artifactory root.
# Types not listed keep their metadata automatically (Maven, Docker, PyPI, Go,
# Generic, VCS, ...) so there is nothing to recalculate manually.
_REINDEX: dict = {
    "Npm": lambda r: f"/api/npm/{r}/reindex",
    "NuGet": lambda r: f"/api/nuget/{r}/reindex",
    "Debian": lambda r: f"/api/deb/reindex/{r}",
    "Opkg": lambda r: f"/api/opkg/reindex/{r}",
    "YUM": lambda r: f"/api/yum/{r}?async=1",
    "Rpm": lambda r: f"/api/yum/{r}?async=1",
    "Alpine": lambda r: f"/api/alpine/{r}?async=1",
    "Gems": lambda r: f"/api/gems/{r}/reindex",
    "CRAN": lambda r: f"/api/cran/{r}/reindex",
    "Conda": lambda r: f"/api/conda/{r}/reindex",
    "Helm": lambda r: f"/api/helm/{r}/reindex",
    "Cargo": lambda r: f"/api/cargo/{r}/reindex",
}


def _prod():
    """Return (base_url, admin_token) for prod. Raises if not configured."""
    settings = get_settings()
    token = settings.ARTIFACTORY_PROD_ADMIN_TOKEN
    if not token:
        raise RuntimeError("ARTIFACTORY_PROD_ADMIN_TOKEN is not configured")
    return settings.ARTIFACTORY_PROD_URL.rstrip("/"), token


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def list_repos() -> list[dict]:
    """List all prod repositories for the dropdown: key, type, packageType."""
    base, token = _prod()
    with httpx.Client(timeout=30) as client:
        resp = client.get(f"{base}{_ART}/api/repositories", headers=_headers(token))
        resp.raise_for_status()
        repos = resp.json()
    out = [
        {
            "key": r.get("key"),
            "type": (r.get("type") or "").upper(),  # LOCAL / REMOTE / VIRTUAL
            "package_type": r.get("packageType") or "Generic",
        }
        for r in repos
        if r.get("key")
    ]
    out.sort(key=lambda r: r["key"].lower())
    return out


def _repo_index() -> dict:
    """Map repo key -> {type, package_type} for dispatch."""
    return {r["key"]: r for r in list_repos()}


def _aql_top_folders(client: httpx.Client, base: str, token: str, repo: str) -> list[str]:
    """Top-level (depth 1) folder names in a repo, via AQL."""
    query = (
        f'items.find({{"repo":"{repo}","type":"folder","depth":"1"}}).include("name")'
    )
    resp = client.post(
        f"{base}{_ART}/api/search/aql",
        headers={**_headers(token), "Content-Type": "text/plain"},
        content=query,
    )
    resp.raise_for_status()
    return [x["name"] for x in resp.json().get("results", []) if x.get("name")]


def _delete_path(base: str, token: str, repo: str, path: str) -> bool:
    """DELETE one cached folder/path. 200/204/404 all count as done."""
    with httpx.Client(timeout=60) as client:
        resp = client.delete(f"{base}{_ART}/{repo}/{path.strip('/')}/", headers=_headers(token))
    return resp.status_code in (200, 204, 404)


def _refresh_remote(base: str, token: str, repo: str, package: str | None) -> dict:
    """Delete cached content so Artifactory re-fetches from upstream.

    Cached artifacts for a remote repo live in the sibling `<repo>-cache`
    repository, so all AQL/DELETE operations target that.
    """
    cache_repo = f"{repo}-cache"
    if package:
        ok = _delete_path(base, token, cache_repo, package)
        return {
            "ok": ok,
            "action": "cache-refresh",
            "detail": f"Deleted cached path '{package}' (re-fetches on next request)"
            if ok
            else f"Failed to delete cached path '{package}'",
            "deleted": 1 if ok else 0,
        }

    # Full wipe: delete every top-level cached folder in parallel.
    with httpx.Client(timeout=30) as client:
        folders = _aql_top_folders(client, base, token, cache_repo)
    if not folders:
        return {"ok": True, "action": "cache-refresh", "detail": "Cache already empty", "deleted": 0}

    with ThreadPoolExecutor(max_workers=10) as pool:
        results = list(pool.map(lambda f: _delete_path(base, token, cache_repo, f), folders))
    deleted = sum(1 for r in results if r)
    return {
        "ok": deleted == len(folders),
        "action": "cache-refresh",
        "detail": f"Wiped {deleted}/{len(folders)} cached folders (re-fetch on next request)",
        "deleted": deleted,
    }


def _reindex(base: str, token: str, repo: str, package_type: str) -> dict:
    """Recalculate index for a local/virtual repo, by package type."""
    builder = _REINDEX.get(package_type)
    if builder is None:
        return {
            "ok": True,
            "action": "reindex",
            "detail": f"{package_type} indexes are auto-maintained; no manual reindex needed",
            "deleted": 0,
        }
    with httpx.Client(timeout=60) as client:
        resp = client.post(f"{base}{_ART}{builder(repo)}", headers=_headers(token))
    ok = resp.status_code in (200, 202)
    return {
        "ok": ok,
        "action": "reindex",
        "detail": (resp.text or "Recalculation scheduled").strip()[:200]
        if ok
        else f"Reindex returned HTTP {resp.status_code}",
        "deleted": 0,
    }


def refresh_repos(repo_keys: list[str], package: str | None = None) -> list[dict]:
    """
    Refresh each repo. Remote -> cache delete; Local/Virtual -> reindex.
    Returns one result dict per repo.
    """
    base, token = _prod()
    index = _repo_index()
    results: list[dict] = []
    for key in repo_keys:
        meta = index.get(key)
        if not meta:
            results.append({"repo": key, "type": "?", "ok": False, "action": "-", "detail": "Repo not found"})
            continue
        rtype = meta["type"]
        ptype = meta["package_type"]
        try:
            if rtype == "REMOTE":
                r = _refresh_remote(base, token, key, package)
            else:  # LOCAL / VIRTUAL
                r = _reindex(base, token, key, ptype)
        except httpx.HTTPError as exc:
            r = {"ok": False, "action": "-", "detail": f"Request error: {exc}", "deleted": 0}
        results.append({"repo": key, "type": rtype, "package_type": ptype, **r})
    return results
