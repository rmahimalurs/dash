"""
Copy Controllers automation — preview prod-east controller config and trigger
the cbc-onboarding-casc Jenkins job on dev-east to create a copy.

MVP scope:
- Preview: best-effort discovery of the prod controller's AWS assume-role list
  (IAM policy `cbc-<controller>-assume-role`) and admins (CJOC Script Console).
  Network CIDRs are not auto-discovered yet — the engineer fills them in.
- Run: triggers cbc-onboarding-casc with TEAM_NAME/CLDSPT_TICKET/AWS_ROLES/
  NETWORK_RANGES/ADMINS/FISMAID parameters. Job/secret/plugin copy is deferred.
"""

from __future__ import annotations

import base64
import json
import logging
import re
from typing import Optional

import httpx

from app.config import get_settings
from app.services.jenkins import run_groovy_script, trigger_job

logger = logging.getLogger(__name__)


# ─── AWS IAM (cross-account) ──────────────────────────────────────────────────


def _boto3_iam_client(region: str = "us-east-1"):
    """
    Return a boto3 IAM client authenticated against the Jenkins prod-east AWS
    account. Tries (1) explicit access keys, (2) role assumption via the
    dashboard's Pod Identity, (3) default credentials chain. Returns None if
    boto3 is unavailable or all auth paths fail.
    """
    try:
        import boto3
        from botocore.exceptions import BotoCoreError, ClientError
    except ImportError:
        logger.warning("boto3 not installed; AWS lookups disabled")
        return None

    settings = get_settings()

    if settings.JENKINS_PROD_EAST_AWS_ACCESS_KEY_ID and settings.JENKINS_PROD_EAST_AWS_SECRET_ACCESS_KEY:
        try:
            return boto3.client(
                "iam",
                region_name=region,
                aws_access_key_id=settings.JENKINS_PROD_EAST_AWS_ACCESS_KEY_ID,
                aws_secret_access_key=settings.JENKINS_PROD_EAST_AWS_SECRET_ACCESS_KEY,
            )
        except (BotoCoreError, ClientError) as exc:
            logger.warning("Could not build IAM client from JENKINS_PROD_EAST_* keys: %s", exc)

    if settings.JENKINS_PROD_EAST_ROLE_ARN:
        try:
            sts = boto3.client("sts")
            assumed = sts.assume_role(
                RoleArn=settings.JENKINS_PROD_EAST_ROLE_ARN,
                RoleSessionName="devops-dashboard-copy-controller",
                DurationSeconds=900,
            )
            creds = assumed["Credentials"]
            return boto3.client(
                "iam",
                region_name=region,
                aws_access_key_id=creds["AccessKeyId"],
                aws_secret_access_key=creds["SecretAccessKey"],
                aws_session_token=creds["SessionToken"],
            )
        except (BotoCoreError, ClientError) as exc:
            logger.warning("Could not assume %s: %s", settings.JENKINS_PROD_EAST_ROLE_ARN, exc)

    try:
        return boto3.client("iam", region_name=region)
    except (BotoCoreError, ClientError) as exc:
        logger.warning("Default IAM client failed: %s", exc)
    return None


def _extract_assume_role_arns(policy_doc: dict) -> list[str]:
    """Pull all sts:AssumeRole Resource ARNs out of an IAM policy document."""
    statements = policy_doc.get("Statement", [])
    if isinstance(statements, dict):
        statements = [statements]
    roles: list[str] = []
    for stmt in statements:
        if stmt.get("Effect", "Allow") != "Allow":
            continue
        actions = stmt.get("Action", [])
        if isinstance(actions, str):
            actions = [actions]
        if not any(a == "sts:AssumeRole" or a == "*" or a == "sts:*" for a in actions):
            continue
        resources = stmt.get("Resource", [])
        if isinstance(resources, str):
            resources = [resources]
        for r in resources:
            if r and r != "*" and r not in roles:
                roles.append(r)
    return roles


def discover_aws_roles(controller_name: str) -> dict:
    """
    Read the cbc-<controller>-assume-role inline policy on the controller's
    IAM role in the Jenkins prod-east account, and return the list of
    sts:AssumeRole Resource ARNs.

    Discovery order:
    1. Direct lookup on the conventional role name `cbc-<controller>`
    2. Fallback: scan all roles for one carrying that inline policy name
    """
    iam = _boto3_iam_client()
    if iam is None:
        return {"roles": [], "error": "AWS access not configured (set JENKINS_PROD_EAST_ROLE_ARN or *_ACCESS_KEY_ID)"}

    policy_name = f"cbc-{controller_name}-assume-role"

    # Path 1 — direct, fast (one or two API calls)
    direct_role = f"cbc-{controller_name}"
    try:
        doc = iam.get_role_policy(RoleName=direct_role, PolicyName=policy_name)["PolicyDocument"]
        return {
            "roles": _extract_assume_role_arns(doc),
            "error": None,
            "policy_source": f"inline policy on role {direct_role!r}",
        }
    except Exception as exc:
        # NoSuchEntity for either role or policy — try the fallback scan
        code = getattr(exc, "response", {}).get("Error", {}).get("Code", "")
        if code and code not in ("NoSuchEntity", "NoSuchEntityException"):
            logger.warning("IAM lookup for %s/%s failed: %s", direct_role, policy_name, exc)
            return {"roles": [], "error": f"IAM lookup failed: {exc}"}
        logger.info("Direct lookup miss (%s/%s); falling back to role scan", direct_role, policy_name)

    # Path 2 — exhaustive scan for the inline policy name
    try:
        for page in iam.get_paginator("list_roles").paginate():
            for r in page.get("Roles", []):
                rn = r["RoleName"]
                try:
                    inlines = iam.list_role_policies(RoleName=rn).get("PolicyNames", [])
                except Exception:
                    continue
                if policy_name in inlines:
                    doc = iam.get_role_policy(RoleName=rn, PolicyName=policy_name)["PolicyDocument"]
                    return {
                        "roles": _extract_assume_role_arns(doc),
                        "error": None,
                        "policy_source": f"inline policy on role {rn!r}",
                    }
    except Exception as exc:
        logger.warning("Role scan for %s failed: %s", policy_name, exc)
        return {"roles": [], "error": f"Role scan failed: {exc}"}

    return {
        "roles": [],
        "error": f"Inline policy {policy_name!r} not found on any role in the target account",
    }


# ─── CJOC RBAC / admins ───────────────────────────────────────────────────────


# Runs on the CONTROLLER's own Jenkins (not CJOC). The controller uses the
# CloudBees nectar RBAC plugin (RoleMatrixAuthorizationStrategyImpl) which
# exposes local groups; each group has getRoles() (role name strings) and
# getUsers()/getMembers().
_GROOVY_LIST_ADMINS = r"""
def strat = Jenkins.instance.authorizationStrategy
if (strat == null) { println "NO_AUTH_STRATEGY"; return }

def admins = new TreeSet<String>()
def groups = []
try { groups = strat.getLocalGroups() ?: [] } catch (Throwable ignored) {}
if (groups.isEmpty()) {
  try { groups = strat.getGroups() ?: [] } catch (Throwable ignored) {}
}

groups.each { g ->
  def hasAdmin = false
  try {
    g.getRoles()?.each { r ->
      if ((r?.toString() ?: "").toLowerCase().contains("admin")) hasAdmin = true
    }
  } catch (Throwable ignored) {}
  if (!hasAdmin) return
  // getUsers() may return either List<String> (SIDs) or List<Member>.
  // Coerce each entry to a string and drop anonymous/empty.
  try {
    g.getUsers()?.each { u ->
      def s = (u instanceof String) ? u : (u?.name ?: u?.toString())
      if (s && s != "anonymous") admins.add(s.toString())
    }
  } catch (Throwable ignored) {}
}

if (admins.isEmpty()) {
  println "EMPTY"
  return
}
println admins.join(",")
"""


def _strip_cjoc(url: str) -> str:
    """Return the base Jenkins URL with a trailing /cjoc suffix removed."""
    return re.sub(r"/cjoc/?$", "", (url or "").rstrip("/"))


def _prod_controller_url(controller_name: str) -> str:
    return f"{_strip_cjoc(get_settings().CLOUDBEES_EAST_PROD_URL)}/{controller_name}"


def _dev_controller_url(controller_name: str) -> str:
    return f"{_strip_cjoc(get_settings().CLOUDBEES_EAST_DEV_URL)}/{controller_name}"


def _dev_cjoc_url() -> str:
    """Return the dev-east CJOC URL (adds /cjoc if the configured URL lacks it)."""
    base = _strip_cjoc(get_settings().CLOUDBEES_EAST_DEV_URL)
    return f"{base}/cjoc"


def _prod_auth() -> tuple[str, str] | None:
    s = get_settings()
    token = s.JENKINS_EAST_PROD_TOKEN or s.JENKINS_TOKEN
    return (s.JENKINS_PROD_USER, token) if token else None


def _dev_auth() -> tuple[str, str] | None:
    s = get_settings()
    token = s.JENKINS_EAST_DEV_TOKEN or s.JENKINS_TOKEN
    return (s.JENKINS_DEV_USER, token) if token else None


def _detect_groovy_trace(out: str) -> str | None:
    """Return a short error description if Groovy output looks like a stack trace."""
    if "Exception" in out and ("at " in out or "Script1.groovy" in out):
        first = out.splitlines()[0] if out.splitlines() else "Groovy error"
        return first[:200]
    return None


# Runs on the dev-east CJOC. Checks whether a ManagedMaster with the given
# name is already registered. Used to make Copy Controllers idempotent —
# skip the onboarding job trigger if the controller already exists.
_GROOVY_CHECK_DEV_EXISTS = r"""
import com.cloudbees.opscenter.server.model.ManagedMaster
def name = "__CONTROLLER__"
def master = Jenkins.instance.getAllItems(ManagedMaster).find { it.name == name }
if (master == null) {
  println "MISSING"
} else {
  println "EXISTS"
  try { println "URL=" + master.getUrl() } catch (Throwable ignored) {}
}
"""


def get_dev_build_info(build_url: str) -> dict:
    """
    Fetch Jenkins build info for a dev-east build (needs dev-east SA auth,
    not the prod-east auth that jenkins.get_build_info hardcodes).
    Returns {building, result, number, url} or {error: str}.
    """
    settings = get_settings()
    user = settings.JENKINS_DEV_USER
    token = settings.JENKINS_EAST_DEV_TOKEN or settings.JENKINS_TOKEN
    if not token or not user:
        return {"error": "No dev-east Jenkins credentials configured"}

    api_url = f"{build_url.rstrip('/')}/api/json"
    try:
        resp = httpx.get(api_url, auth=(user, token), timeout=10, verify=True, follow_redirects=True)
    except httpx.RequestError as exc:
        return {"error": f"Jenkins fetch failed: {exc}"}
    if not resp.is_success:
        return {"error": f"Jenkins {resp.status_code}: {resp.text[:200]}"}
    data = resp.json()
    return {
        "building":     data.get("building", False),
        "result":       data.get("result"),
        "number":       data.get("number"),
        "url":          data.get("url", build_url),
        "duration":     data.get("duration"),
        "timestamp":    data.get("timestamp"),
        "error":        None,
    }


def check_controller_exists_on_dev(controller_name: str) -> dict:
    """
    Return {'exists': bool, 'error': str | None}. Queries dev-east CJOC's
    Script Console to see if the ManagedMaster is already registered.
    """
    settings = get_settings()
    user = settings.JENKINS_DEV_USER
    token = settings.JENKINS_EAST_DEV_TOKEN or settings.JENKINS_TOKEN
    if not token or not user:
        return {"exists": False, "error": "No dev-east Jenkins credentials configured"}

    script = _GROOVY_CHECK_DEV_EXISTS.replace("__CONTROLLER__", controller_name)
    try:
        out = run_groovy_script(_dev_cjoc_url(), script, auth=(user, token))
    except Exception as exc:
        logger.warning("Dev-east existence check for %s failed: %s", controller_name, exc)
        return {"exists": False, "error": f"CJOC lookup failed: {exc}"}

    out = (out or "").strip()
    trace = _detect_groovy_trace(out)
    if trace:
        return {"exists": False, "error": f"Groovy error: {trace}"}
    first_line = out.splitlines()[0] if out else ""
    if first_line == "EXISTS":
        return {"exists": True, "error": None}
    if first_line == "MISSING":
        return {"exists": False, "error": None}
    return {"exists": False, "error": f"Unexpected output: {out[:200]}"}


def discover_admins(controller_name: str) -> dict:
    """
    Return the admin SIDs configured on the prod controller via the
    CloudBees nectar RBAC plugin. Runs Groovy on the controller's own
    Script Console (not CJOC).
    """
    auth = _prod_auth()
    if not auth:
        return {"admins": [], "error": "No Jenkins prod-east credentials configured"}

    try:
        out = run_groovy_script(_prod_controller_url(controller_name), _GROOVY_LIST_ADMINS, auth=auth)
    except Exception as exc:
        logger.warning("Admins lookup for %s failed: %s", controller_name, exc)
        return {"admins": [], "error": f"Controller lookup failed: {exc}"}

    out = (out or "").strip()
    if out == "NO_AUTH_STRATEGY":
        return {"admins": [], "error": "Controller has no authorization strategy configured"}
    if out == "EMPTY":
        return {"admins": [], "error": "No RBAC groups with admin role found; please enter admins manually."}
    trace = _detect_groovy_trace(out)
    if trace:
        return {"admins": [], "error": f"Controller Groovy error: {trace}"}
    admins = [a.strip() for a in out.split(",") if a.strip()]
    return {"admins": admins, "error": None}


# ─── Credentials export / apply (from cloudbees/jenkins-scripts) ─────────────

# The CloudBees credentials-migration scripts; baked in verbatim so we can
# run them via Script Console on prod (export) and on dev (apply).
_GROOVY_EXPORT_CREDENTIALS = r"""
import com.cloudbees.plugins.credentials.SystemCredentialsProvider
import com.cloudbees.plugins.credentials.domains.DomainCredentials
import com.thoughtworks.xstream.converters.Converter
import com.thoughtworks.xstream.converters.MarshallingContext
import com.thoughtworks.xstream.converters.UnmarshallingContext
import com.thoughtworks.xstream.io.HierarchicalStreamReader
import com.thoughtworks.xstream.io.HierarchicalStreamWriter
import java.util.Base64
import hudson.util.Secret
import com.cloudbees.plugins.credentials.SecretBytes
import hudson.util.XStream2
import jenkins.model.Jenkins

def instance = Jenkins.get()
def credentials = []

def systemProvider = instance.getExtensionList(SystemCredentialsProvider.class)
if (!systemProvider.empty) {
    def systemStore = systemProvider.first().getStore()
    for (domain in systemStore.domains) {
        credentials.add(new DomainCredentials(domain, systemStore.getCredentials(domain)))
    }
}

def converter = new Converter() {
    @Override
    void marshal(Object object, HierarchicalStreamWriter writer, MarshallingContext context) {
        switch (object.class) {
            case Secret: writer.value = Secret.toString(object as Secret); break
            case SecretBytes: writer.value = Base64.getEncoder().encodeToString((object as SecretBytes).getPlainData()); break
        }
    }
    @Override
    Object unmarshal(HierarchicalStreamReader reader, UnmarshallingContext context) { null }
    @Override
    boolean canConvert(Class type) { type == Secret.class || type == SecretBytes.class }
}

def stream = new XStream2()
stream.registerConverter(converter)

def encoded = []
def sections = credentials.collate(25)
for (section in sections) {
    encoded.add("\"${Base64.getEncoder().encodeToString(stream.toXML(section).bytes)}\"")
}
println encoded.toString()
"""

_GROOVY_APPLY_CREDENTIALS_TEMPLATE = r"""
import com.cloudbees.plugins.credentials.SystemCredentialsProvider
import com.cloudbees.plugins.credentials.domains.DomainCredentials
import hudson.util.XStream2
import java.util.Base64
import jenkins.model.Jenkins

def encoded = __ENCODED__
if (!encoded) { println "EMPTY_INPUT"; return }

def updated = 0
def added = 0
def errors = []

for (slice in encoded) {
    def decoded = new String(Base64.getDecoder().decode(slice))
    def list = new XStream2().fromXML(decoded) as List<DomainCredentials>
    def store = Jenkins.get().getExtensionList(SystemCredentialsProvider.class).first().getStore()
    for (domain in list) {
        for (credential in domain.credentials) {
            try {
                if (store.updateCredentials(domain.getDomain(), credential, credential)) {
                    updated++
                } else if (store.addCredentials(domain.getDomain(), credential)) {
                    added++
                } else {
                    errors.add(credential.id.toString())
                }
            } catch (Throwable t) {
                errors.add(credential.id.toString() + ": " + t.message)
            }
        }
    }
}
println "RESULT updated=" + updated + " added=" + added + " errors=" + errors.size()
if (!errors.isEmpty()) { println "ERRORS: " + errors.join(", ") }
"""


def export_credentials_from_prod(controller_name: str) -> dict:
    """Export all system-level credentials from the prod controller's Script Console."""
    auth = _prod_auth()
    if not auth:
        return {"encoded": None, "error": "No Jenkins prod-east credentials configured"}

    try:
        out = run_groovy_script(_prod_controller_url(controller_name), _GROOVY_EXPORT_CREDENTIALS, auth=auth)
    except Exception as exc:
        logger.warning("Credentials export for %s failed: %s", controller_name, exc)
        return {"encoded": None, "error": f"Export failed: {exc}"}

    out = (out or "").strip()
    trace = _detect_groovy_trace(out)
    if trace:
        return {"encoded": None, "error": f"Export Groovy error: {trace}"}
    # The export prints: ["base64...", "base64...", ...] — a literal Groovy list.
    # Strip surrounding whitespace and return verbatim so it can be embedded
    # directly into the apply script's `def encoded = ...` line.
    if not out.startswith("[") or not out.endswith("]"):
        return {"encoded": None, "error": f"Unexpected export output: {out[:160]}"}
    return {"encoded": out, "error": None}


def apply_credentials_to_dev(controller_name: str, encoded: str) -> dict:
    """Apply previously exported credentials onto the dev controller."""
    auth = _dev_auth()
    if not auth:
        return {"error": "No Jenkins dev-east credentials configured"}

    encoded = (encoded or "").strip()
    if not encoded.startswith("[") or not encoded.endswith("]"):
        return {"error": "Encoded payload must be a Groovy list like [\"base64\", \"base64\"]"}

    # Embed the list verbatim into the apply template.
    script = _GROOVY_APPLY_CREDENTIALS_TEMPLATE.replace("__ENCODED__", encoded)
    try:
        out = run_groovy_script(_dev_controller_url(controller_name), script, auth=auth)
    except Exception as exc:
        logger.warning("Credentials apply to %s failed: %s", controller_name, exc)
        return {"error": f"Apply failed: {exc}"}

    out = (out or "").strip()
    trace = _detect_groovy_trace(out)
    if trace:
        return {"error": f"Apply Groovy error: {trace}"}
    return {"output": out, "error": None}


# ─── Job export / apply ───────────────────────────────────────────────────────

# Runs on the prod controller. Walks every folder + job, captures config XML,
# returns a base64-encoded JSON list — one entry per item, ordered so parent
# folders precede their children. Filter to a specific set of fullNames if
# JOB_NAMES_OR_EMPTY is non-empty.
_GROOVY_EXPORT_JOBS = r"""
import com.cloudbees.hudson.plugins.folder.AbstractFolder
import com.cloudbees.hudson.plugins.folder.Folder
import groovy.json.JsonOutput
import hudson.model.Job
import jenkins.model.Jenkins
import java.util.Base64
import java.util.regex.Pattern

def wantedList = __JOB_NAMES_OR_EMPTY__ as List
def hasFilter  = !wantedList.isEmpty()

// Split entries into exact-match names vs. wildcard patterns. Wildcards
// support `*` (any character run, including `/`), so `foo*` matches
// `foo`, `foo/bar`, `foo-anything`; `folder/*` matches every item under
// `folder`.
def exactSet = new HashSet<String>()
def patterns = new ArrayList<Pattern>()
wantedList.each { entry ->
  def s = entry?.toString()?.trim()
  if (!s) return
  if (s.contains("*")) {
    // Escape regex metacharacters except `*`, then convert `*` to `.*`
    def escaped = s.replaceAll(/([.+?^${}()|\[\]\\])/, /\\$1/).replaceAll(/\*/, ".*")
    patterns.add(Pattern.compile('^' + escaped + '$'))
  } else {
    exactSet.add(s)
  }
}

def matches = { String name ->
  if (!hasFilter) return true
  if (exactSet.contains(name)) return true
  for (p in patterns) { if (p.matcher(name).matches()) return true }
  return false
}

// Skip items whose parent is a scan-driven container (Multibranch Pipeline,
// Organization Folder, etc.) — those parents extend AbstractFolder but are
// not the plain com.cloudbees.hudson.plugins.folder.Folder. Their children
// are discovered automatically by SCM scan, so exporting them creates
// orphaned branch jobs that fight the scanner.
def isAutoDiscoveredChild = { item ->
  def p = item.parent
  return p instanceof AbstractFolder && !(p instanceof Folder)
}

def items = []
Jenkins.instance.getAllItems().each { item ->
  def isFolder = item instanceof AbstractFolder   // catches Folder + Multibranch + Org Folder
  def isJob    = item instanceof Job
  if (!isFolder && !isJob) return
  if (isAutoDiscoveredChild(item)) return         // skip branch jobs inside Multibranch
  def fullName = item.fullName
  if (!matches(fullName)) return
  String xml = null
  try {
    xml = item.configFile.asString()
  } catch (Throwable t) {
    items.add([fullName: fullName, type: isFolder ? "folder" : "job", error: "config read: " + t.message])
    return
  }
  items.add([
    fullName: fullName,
    type:     isFolder ? "folder" : "job",
    depth:    fullName.split("/").length,
    xml_b64:  Base64.encoder.encodeToString(xml.getBytes("UTF-8")),
  ])
}

items.sort { a, b -> a.depth <=> b.depth }
def jsonStr = JsonOutput.toJson(items)
println "BEGIN_JOBS_B64"
println Base64.encoder.encodeToString(jsonStr.getBytes("UTF-8"))
println "END_JOBS_B64"
"""

# Runs on the dev controller. Decodes the payload, creates/updates folders and
# jobs in depth-order so parent folders exist before children.
_GROOVY_APPLY_JOBS = r"""
import com.cloudbees.hudson.plugins.folder.Folder
import groovy.json.JsonSlurper
import jenkins.model.Jenkins
import java.util.Base64
import javax.xml.transform.stream.StreamSource

// Payload is chunked because a single Groovy/Java string literal may not
// exceed 65,535 UTF-8 bytes. Each chunk is a separate string constant;
// we join them at runtime with a StringBuilder to avoid constant pool
// overflow.
def payloadChunks = __PAYLOAD_CHUNKS__ as List
def sb = new StringBuilder()
payloadChunks.each { sb.append(it) }
def payloadB64 = sb.toString()
def jsonStr    = new String(Base64.decoder.decode(payloadB64), "UTF-8")
def items      = new JsonSlurper().parseText(jsonStr)
if (!items) { println "EMPTY_INPUT"; return }

def created = 0
def updated = 0
def skipped = 0
def errors  = []

items.each { item ->
  if (item.error) { skipped++; return }
  def fullName = item.fullName.toString()
  def xml = new String(Base64.decoder.decode(item.xml_b64.toString()), "UTF-8")
  try {
    def existing = Jenkins.instance.getItemByFullName(fullName)
    if (existing != null) {
      existing.updateByXml(new StreamSource(new java.io.StringReader(xml)))
      updated++
    } else {
      def parts = fullName.tokenize("/")
      def name = parts.pop()
      def parent = parts ? Jenkins.instance.getItemByFullName(parts.join("/")) : Jenkins.instance
      if (parent == null) {
        errors.add(fullName + ": parent folder missing")
      } else {
        parent.createProjectFromXML(name, new java.io.ByteArrayInputStream(xml.getBytes("UTF-8")))
        created++
      }
    }
  } catch (Throwable t) {
    errors.add(fullName + ": " + t.message)
  }
}

println "RESULT created=" + created + " updated=" + updated + " skipped=" + skipped + " errors=" + errors.size()
if (!errors.isEmpty()) { println "ERRORS: " + errors.take(20).join("; ") }
"""


def _build_export_script(job_list: list[str] | None, all_jobs: bool) -> str:
    """Inline the wanted-jobs Set literal into the export Groovy template."""
    if all_jobs:
        literal = "[]"
    else:
        cleaned = [j.strip() for j in (job_list or []) if j.strip()]
        if not cleaned:
            literal = "[]"
        else:
            # Single-quoted Groovy strings; backslash-escape any embedded quotes.
            escaped = [j.replace("\\", "\\\\").replace("'", "\\'") for j in cleaned]
            literal = "[" + ", ".join(f"'{e}'" for e in escaped) + "]"
    return _GROOVY_EXPORT_JOBS.replace("__JOB_NAMES_OR_EMPTY__", literal)


def export_jobs_from_prod(controller_name: str, *, all_jobs: bool, job_list: list[str] | None) -> dict:
    """Export jobs + folders from the prod controller; returns a base64 JSON payload."""
    auth = _prod_auth()
    if not auth:
        return {"payload": None, "count": 0, "error": "No Jenkins prod-east credentials configured"}

    script = _build_export_script(job_list, all_jobs)
    try:
        out = run_groovy_script(_prod_controller_url(controller_name), script, auth=auth)
    except Exception as exc:
        logger.warning("Jobs export for %s failed: %s", controller_name, exc)
        return {"payload": None, "count": 0, "error": f"Export failed: {exc}"}

    out = (out or "").strip()
    trace = _detect_groovy_trace(out)
    if trace:
        return {"payload": None, "count": 0, "error": f"Export Groovy error: {trace}"}

    m = re.search(r"BEGIN_JOBS_B64\s*\n(.+?)\nEND_JOBS_B64", out, re.DOTALL)
    if not m:
        return {"payload": None, "count": 0, "error": f"Unexpected export output: {out[:200]}"}

    payload_b64 = m.group(1).strip()
    try:
        items = json.loads(base64.b64decode(payload_b64).decode("utf-8"))
    except Exception as exc:
        return {"payload": None, "count": 0, "error": f"Payload decode failed: {exc}"}

    return {
        "payload": payload_b64,
        "count":   len(items),
        "folders": sum(1 for i in items if i.get("type") == "folder"),
        "jobs":    sum(1 for i in items if i.get("type") == "job"),
        "errors":  [i.get("error") for i in items if i.get("error")],
        "error":   None,
    }


def apply_jobs_to_dev(controller_name: str, payload_b64: str) -> dict:
    """Apply previously exported jobs/folders onto the dev controller."""
    auth = _dev_auth()
    if not auth:
        return {"error": "No Jenkins dev-east credentials configured"}

    payload_b64 = (payload_b64 or "").strip()
    if not payload_b64:
        return {"error": "Empty payload"}
    # Validate base64 + JSON shape before sending
    try:
        items = json.loads(base64.b64decode(payload_b64).decode("utf-8"))
        if not isinstance(items, list):
            raise ValueError("payload must be a JSON list")
    except Exception as exc:
        return {"error": f"Invalid payload: {exc}"}

    # Chunk to sidestep Groovy's 65,535-byte string literal limit. 30 KB
    # per chunk is safely under and keeps the generated script readable.
    CHUNK_SIZE = 30_000
    chunks = [payload_b64[i:i + CHUNK_SIZE] for i in range(0, len(payload_b64), CHUNK_SIZE)]
    # Each chunk is pure base64 (no quotes, backslashes, or `$` — no escaping needed)
    chunks_literal = "[" + ", ".join(f'"{c}"' for c in chunks) + "]"
    script = _GROOVY_APPLY_JOBS.replace("__PAYLOAD_CHUNKS__", chunks_literal)
    try:
        out = run_groovy_script(_dev_controller_url(controller_name), script, auth=auth)
    except Exception as exc:
        logger.warning("Jobs apply to %s failed: %s", controller_name, exc)
        return {"error": f"Apply failed: {exc}"}

    out = (out or "").strip()
    trace = _detect_groovy_trace(out)
    if trace:
        return {"error": f"Apply Groovy error: {trace}"}
    return {"output": out, "items_in_payload": len(items), "error": None}


# ─── Public flows ─────────────────────────────────────────────────────────────


# ─── Network CIDR discovery via CJOC in-cluster K8s API ──────────────────────

# Runs on the CJOC. Uses the in-pod ServiceAccount token + CA bundle to call
# the K8s API directly (CJOC already has RBAC to manage NetworkPolicies in
# the controller namespaces it owns, so no extra ClusterRoleBinding needed).
# Lists NetworkPolicies in namespace `cbc-<controller>` and pulls every
# egress.to.ipBlock.cidr entry.
_GROOVY_LIST_NETWORK_CIDRS = r"""
import groovy.json.JsonSlurper
import java.net.HttpURLConnection
import java.net.URL
import javax.net.ssl.HttpsURLConnection
import javax.net.ssl.SSLContext
import javax.net.ssl.TrustManagerFactory
import java.security.KeyStore
import java.security.cert.CertificateFactory
import java.security.cert.X509Certificate

def controllerName = "__CONTROLLER__"
def ns = "cbc-" + controllerName

def tokenFile = new File("/var/run/secrets/kubernetes.io/serviceaccount/token")
def caFile    = new File("/var/run/secrets/kubernetes.io/serviceaccount/ca.crt")
if (!tokenFile.exists()) { println "NO_SA_TOKEN"; return }
if (!caFile.exists())    { println "NO_CA_BUNDLE"; return }

// Build a trust store from the SA CA bundle so we can validate the apiserver cert
def cf = CertificateFactory.getInstance("X.509")
def caCerts = []
caFile.text.findAll(/(?s)-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----/).each { pem ->
  caCerts.add(cf.generateCertificate(new ByteArrayInputStream(pem.bytes)) as X509Certificate)
}
def ks = KeyStore.getInstance(KeyStore.defaultType)
ks.load(null, null)
caCerts.eachWithIndex { c, i -> ks.setCertificateEntry("sa-ca-" + i, c) }
def tmf = TrustManagerFactory.getInstance(TrustManagerFactory.defaultAlgorithm)
tmf.init(ks)
def ctx = SSLContext.getInstance("TLS")
ctx.init(null, tmf.trustManagers, null)

def host = System.getenv("KUBERNETES_SERVICE_HOST") ?: "kubernetes.default.svc"
def port = System.getenv("KUBERNETES_SERVICE_PORT") ?: "443"
def url = new URL("https://" + host + ":" + port + "/apis/networking.k8s.io/v1/namespaces/" + ns + "/networkpolicies")

def conn = url.openConnection() as HttpsURLConnection
conn.setSSLSocketFactory(ctx.socketFactory)
conn.setRequestProperty("Authorization", "Bearer " + tokenFile.text.trim())
conn.setRequestProperty("Accept", "application/json")
conn.setConnectTimeout(10_000)
conn.setReadTimeout(15_000)

int code = conn.responseCode
if (code != 200) {
  def err = conn.errorStream?.text ?: ""
  println "HTTP_" + code + ": " + err.take(300)
  return
}

def body = conn.inputStream.text
def doc = new JsonSlurper().parseText(body)
def items = doc.items ?: []

def cidrs = new LinkedHashSet<String>()  // preserve order, dedupe
items.each { np ->
  def egress = np.spec?.egress ?: []
  egress.each { rule ->
    (rule.to ?: []).each { peer ->
      def cidr = peer?.ipBlock?.cidr
      if (cidr) cidrs.add(cidr.toString())
    }
  }
}

println "NAMESPACE=" + ns
println "NP_COUNT=" + items.size()
println "CIDRS=" + cidrs.join(",")
"""


def discover_network_cidrs(controller_name: str) -> dict:
    """
    Read egress ipBlock CIDRs from all NetworkPolicies in the controller's
    `cbc-<name>` namespace, via Groovy on CJOC using its in-cluster SA.
    """
    auth = _prod_auth()
    if not auth:
        return {"cidrs": [], "namespace": None, "np_count": 0, "error": "No Jenkins prod-east credentials configured"}

    settings = get_settings()
    cjoc_url = settings.JENKINS_PROD_EAST_CJOC_URL
    script = _GROOVY_LIST_NETWORK_CIDRS.replace("__CONTROLLER__", controller_name)
    try:
        out = run_groovy_script(cjoc_url, script, auth=auth)
    except Exception as exc:
        logger.warning("Network CIDR discovery for %s failed: %s", controller_name, exc)
        return {"cidrs": [], "namespace": None, "np_count": 0, "error": f"CJOC lookup failed: {exc}"}

    out = (out or "").strip()
    trace = _detect_groovy_trace(out)
    if trace:
        return {"cidrs": [], "namespace": None, "np_count": 0, "error": f"Groovy error: {trace}"}
    if out.startswith("NO_SA_TOKEN") or out.startswith("NO_CA_BUNDLE"):
        return {"cidrs": [], "namespace": None, "np_count": 0, "error": out}
    if out.startswith("HTTP_"):
        return {"cidrs": [], "namespace": None, "np_count": 0, "error": f"K8s API error: {out[:300]}"}

    parsed: dict[str, str] = {}
    for line in out.splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            parsed[k.strip()] = v.strip()

    ns = parsed.get("NAMESPACE")
    try:
        np_count = int(parsed.get("NP_COUNT", "0"))
    except ValueError:
        np_count = 0
    cidr_str = parsed.get("CIDRS", "")
    cidrs = [c.strip() for c in cidr_str.split(",") if c.strip()]

    if not cidrs:
        return {
            "cidrs": [], "namespace": ns, "np_count": np_count,
            "error": f"No egress ipBlock CIDRs found across {np_count} NetworkPolicies in {ns!r}",
        }
    return {"cidrs": cidrs, "namespace": ns, "np_count": np_count, "error": None}


def preview_copy_controller(controller_name: str) -> dict:
    """Best-effort discovery of prod-east controller config for the modal preview."""
    controller_name = (controller_name or "").strip()
    if not controller_name:
        raise ValueError("controller_name is required")
    if not re.match(r"^[a-zA-Z0-9][a-zA-Z0-9\-_]{0,63}$", controller_name):
        raise ValueError("controller_name must be alphanumeric + dash/underscore, ≤ 64 chars")

    aws = discover_aws_roles(controller_name)
    admins = discover_admins(controller_name)
    networks = discover_network_cidrs(controller_name)
    dev_state = check_controller_exists_on_dev(controller_name)

    return {
        "controller_name": controller_name,
        "aws_roles": aws["roles"],
        "aws_roles_error": aws.get("error"),
        "aws_policy_arn": aws.get("policy_arn"),
        "network_cidrs":   networks["cidrs"],
        "network_cidrs_error": networks.get("error"),
        "network_namespace":   networks.get("namespace"),
        "network_np_count":    networks.get("np_count", 0),
        "admins": admins["admins"],
        "admins_error": admins.get("error"),
        "already_exists_on_dev": dev_state.get("exists", False),
        "dev_existence_error":   dev_state.get("error"),
    }


def run_copy_controller(
    *,
    controller_name: str,
    aws_roles: list[str],
    network_ranges: list[str],
    admins: list[str],
    cldspt_ticket: str = "CLDSPT-99999",
    fisma_id: str = "test",
    migrate_all_jobs: bool = False,
    job_list: list[str] | None = None,
    copy_secrets: bool = False,
    copy_plugins: bool = False,
    auth: tuple[str, str] | None = None,
) -> dict:
    """Trigger cbc-onboarding-casc on the dev-east tooling Jenkins with the supplied params."""
    settings = get_settings()
    if not (controller_name or "").strip():
        raise ValueError("controller_name is required")

    job_url = f"{settings.JENKINS_DEV_EAST_TOOLING_URL.rstrip('/')}/{settings.CBC_ONBOARDING_JOB_PATH}"

    params = {
        "TEAM_NAME":      controller_name,
        "CLDSPT_TICKET":  cldspt_ticket or "CLDSPT-99999",
        "AWS_ROLES":      ",".join(aws_roles),
        "NETWORK_RANGES": ",".join(network_ranges),
        "ADMINS":         ",".join(admins),
        "FISMAID":        fisma_id or "test",
    }

    if auth is None:
        auth = (settings.JENKINS_DEV_USER, settings.JENKINS_EAST_DEV_TOKEN or settings.JENKINS_TOKEN)

    # Idempotency guard: if the controller already exists on dev-east, DO
    # NOT re-trigger the onboarding job — it would fail or (worse) create a
    # duplicate. Follow-up steps (secrets/jobs/plugins/network) still run.
    dev_state = check_controller_exists_on_dev(controller_name)
    if dev_state.get("exists"):
        result = {
            "queue_url":    None,
            "build_url":    None,
            "build_number": None,
            "status":       "skipped_already_exists",
        }
        already_existed = True
    else:
        result = trigger_job(job_url, params, auth=auth)
        already_existed = False

    # If secrets copy was requested, export from prod NOW so we have the
    # encoded payload ready. Apply happens via a separate endpoint after
    # the engineer confirms the dev controller exists.
    secrets_payload: dict = {}
    if copy_secrets:
        secrets_payload = export_credentials_from_prod(controller_name)

    jobs_payload: dict = {}
    wants_jobs = bool(migrate_all_jobs or (job_list or []))
    if wants_jobs:
        jobs_payload = export_jobs_from_prod(
            controller_name,
            all_jobs=migrate_all_jobs,
            job_list=job_list,
        )

    plugins_result: dict = {}
    if copy_plugins:
        try:
            from app.services.cloudbees_plugins import sync_plugins_to_bundle
            plugins_result = sync_plugins_to_bundle(controller_name)
        except Exception as exc:
            logger.warning("Plugins sync for %s failed: %s", controller_name, exc)
            plugins_result = {"error": str(exc)}

    return {
        "controller_name": controller_name,
        "already_existed_on_dev": already_existed,
        "job_url":      job_url,
        "queue_url":    result.get("queue_url"),
        "build_url":    result.get("build_url"),
        "build_number": result.get("build_number"),
        "status":       result.get("status", "queued"),
        "parameters":   params,
        "secrets_encoded": secrets_payload.get("encoded"),
        "secrets_error":   secrets_payload.get("error"),
        "jobs_payload":    jobs_payload.get("payload"),
        "jobs_count":      jobs_payload.get("count", 0),
        "jobs_folders":    jobs_payload.get("folders", 0),
        "jobs_jobs":       jobs_payload.get("jobs", 0),
        "jobs_error":      jobs_payload.get("error"),
        "jobs_export_errors": jobs_payload.get("errors", []),
        "plugins_delta":        plugins_result.get("delta", []),
        "plugins_catalog_gaps": plugins_result.get("catalog_gaps", []),
        "plugins_files_changed": plugins_result.get("files_changed", []),
        "plugins_pr_url":       plugins_result.get("pr_url"),
        "plugins_pr_number":    plugins_result.get("pr_number"),
        "plugins_summary":      plugins_result.get("summary"),
        "plugins_no_changes":   plugins_result.get("no_changes", False),
        "plugins_error":        plugins_result.get("error"),
        "pending_followups": {
            "jobs":    wants_jobs,
            "secrets": bool(copy_secrets),
            "plugins": bool(copy_plugins),
        },
    }
