import logging
import time

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

# How long to wait for a queued job to become a running build (seconds)
_QUEUE_POLL_TIMEOUT = 30
_QUEUE_POLL_INTERVAL = 2

_CLOUDBEES_LICENSE_SCRIPT = """\
import jenkins.model.Jenkins
def lm = Jenkins.get().getExtensionList(hudson.license.LicenseManager)[0]
def expiresRaw = lm.getExpires()
def expiresDate = (expiresRaw != null) ? new Date(expiresRaw as long) : null
println expiresDate ? expiresDate.format("yyyy-MM-dd") : "No expiration found"
"""


def run_groovy_script(cjoc_url: str, script: str, auth: tuple[str, str], timeout: float = 15) -> str:
    """POST a Groovy script to the Jenkins Script Console and return stdout.

    timeout defaults to 15s; pass a larger value for disk-usage / prune scripts
    that walk JENKINS_HOME and can legitimately take longer.
    """
    url = f"{cjoc_url.rstrip('/')}/scriptText"
    with httpx.Client(auth=auth, timeout=timeout, verify=True, follow_redirects=True) as client:
        resp = client.post(url, data={"script": script})
    resp.raise_for_status()
    return resp.text.strip()


def _auth() -> tuple[str, str]:
    """Return (user, token) for Jenkins basic auth."""
    settings = get_settings()
    return (settings.JENKINS_USER, settings.JENKINS_TOKEN)


def trigger_job(job_url: str, params: dict, auth: tuple[str, str] | None = None) -> dict:
    """
    Trigger a parameterized Jenkins job and return queue / build information.

    job_url   - Base URL of the job, e.g. https://jenkins-east.cloud.cms.gov/job/my-job
    params    - Dict of build parameters to pass to the job.

    Returns a dict with:
      - queue_url:    URL of the created queue item
      - build_url:    URL of the actual build (if it started within the poll window)
      - build_number: Build number (int) or None
      - status:       'queued' | 'running' | 'unknown'
    """
    trigger_url = f"{job_url.rstrip('/')}/buildWithParameters"

    with httpx.Client(auth=auth or _auth(), timeout=15, verify=True, follow_redirects=True) as client:
        resp = client.post(trigger_url, data=params)

    if resp.status_code not in (200, 201):
        raise RuntimeError(
            f"Jenkins returned {resp.status_code} when triggering {trigger_url}: {resp.text[:200]}"
        )

    queue_url = resp.headers.get("Location", "")
    if queue_url and not queue_url.endswith("/"):
        queue_url += "/"

    # Poll the queue item to get the actual build URL
    build_url = None
    build_number = None
    status = "queued"

    if queue_url:
        deadline = time.monotonic() + _QUEUE_POLL_TIMEOUT
        with httpx.Client(auth=auth or _auth(), timeout=10, verify=True) as client:
            while time.monotonic() < deadline:
                try:
                    q_resp = client.get(f"{queue_url}api/json")
                    if q_resp.is_success:
                        q_data = q_resp.json()
                        executable = q_data.get("executable")
                        if executable:
                            build_url = executable.get("url")
                            build_number = executable.get("number")
                            status = "running"
                            break
                        if q_data.get("cancelled"):
                            status = "cancelled"
                            break
                except httpx.RequestError as exc:
                    logger.warning("Error polling queue item %s: %s", queue_url, exc)
                time.sleep(_QUEUE_POLL_INTERVAL)

    return {
        "queue_url": queue_url,
        "build_url": build_url,
        "build_number": build_number,
        "status": status,
    }


def get_job_params(job_url: str, auth: tuple[str, str] | None = None) -> list[dict]:
    """
    Return the parameter definitions for a Jenkins job.
    Each item: {name, type, description, default, choices}
    type is normalised to 'choice' | 'string' | 'text' | 'boolean'.
    """
    api_url = f"{job_url.rstrip('/')}/api/json"
    with httpx.Client(auth=auth or _auth(), timeout=15, verify=True, follow_redirects=True) as client:
        resp = client.get(api_url, params={"tree": "property[parameterDefinitions[name,type,choices,defaultParameterValue[value],description]]"})
    if not resp.is_success:
        raise RuntimeError(f"Jenkins {resp.status_code} fetching params for {job_url}")

    params = []
    for prop in resp.json().get("property", []):
        for p in prop.get("parameterDefinitions", []):
            raw_type = p.get("type", "")
            if "Choice" in raw_type:
                norm_type = "choice"
            elif "Boolean" in raw_type:
                norm_type = "boolean"
            elif "Text" in raw_type:
                norm_type = "text"
            else:
                norm_type = "string"
            # Jenkins returns booleans (and occasionally numbers) as their native
            # JSON type. Callers submit params as strings and dict[str, str]
            # request models reject non-strings, so normalise here: bool ->
            # "true"/"false" (what buildWithParameters expects), None -> "".
            raw_default = p.get("defaultParameterValue", {}).get("value", "")
            if isinstance(raw_default, bool):
                default = "true" if raw_default else "false"
            elif raw_default is None:
                default = ""
            else:
                default = str(raw_default)
            params.append({
                "name": p["name"],
                "type": norm_type,
                "description": p.get("description", ""),
                "default": default,
                "choices": p.get("choices", []),
            })
    return params


def get_build_info(build_url: str) -> dict:
    """
    Retrieve status information for a specific Jenkins build.

    build_url - Full URL to the build, e.g. https://jenkins-east.cloud.cms.gov/job/my-job/42/

    Returns a dict with:
      - build_number
      - result:     'SUCCESS' | 'FAILURE' | 'ABORTED' | 'UNSTABLE' | None (still running)
      - building:   bool
      - url:        canonical build URL
      - duration:   duration in milliseconds
      - timestamp:  build start epoch milliseconds
    """
    api_url = f"{build_url.rstrip('/')}/api/json"

    with httpx.Client(auth=_auth(), timeout=10, verify=True) as client:
        resp = client.get(api_url)

    if not resp.is_success:
        raise RuntimeError(
            f"Jenkins returned {resp.status_code} for build info at {api_url}: {resp.text[:200]}"
        )

    data = resp.json()
    return {
        "build_number": data.get("number"),
        "result": data.get("result"),
        "building": data.get("building", False),
        "url": data.get("url", build_url),
        "duration": data.get("duration"),
        "timestamp": data.get("timestamp"),
    }
