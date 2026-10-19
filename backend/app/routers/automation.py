import asyncio
import logging

import httpx

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, field_validator

from app.auth.jwt import get_current_user
from app.config import get_settings
from app.services import audit
from app.services.automation_service import (
    get_jfrog_manager_account,
    test_jfrog_ldap_credentials,
    update_jfrog_ldap_password,
    unlock_artifactory_user,
)
from app.services.ad_unlock import unlock_ad_account, reset_ad_password, get_ad_account_status
from app.services import cloudbees_ldap
from app.services import repo_refresh
from app.services import cert_export
from app.services import sonarqube_access
from app.services import pvc_cleanup
from app.services import cbj_waste
from app.services import controller_users
from app.services import artifactory_users
from app.services import jfrog_registry_token
from app.services import cloudbees_access
from app.services import artifactory_access
from app.services import pod_quota
from app.services import jira_service
from app.services.copy_controller import (
    apply_credentials_to_dev,
    apply_jobs_to_dev,
    check_controller_exists_on_dev,
    get_dev_build_info,
    preview_copy_controller,
    run_copy_controller,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/automation", tags=["automation"])


class JFrogPasswordRequest(BaseModel):
    password: str

    @field_validator("password")
    @classmethod
    def password_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Password must not be empty")
        return v


class AccountRequest(BaseModel):
    account: str

    @field_validator("account")
    @classmethod
    def account_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Account name must not be empty")
        return v.strip()


class RotateRequest(BaseModel):
    """Full service-account rotation: reset AD, optionally save to 1Password, then
    update the tool's stored LDAP manager password."""
    password: str | None = None      # required unless generate=True
    generate: bool = False
    save_to_1password: bool = False


class UsernameRequest(BaseModel):
    username: str

    @field_validator("username")
    @classmethod
    def username_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Username must not be empty")
        return v.strip()


class AdResetRequest(BaseModel):
    account: str
    password: str | None = None      # required unless generate=True
    generate: bool = False           # auto-generate a strong password
    save_to_1password: bool = False  # upsert the new password into 1Password

    @field_validator("account")
    @classmethod
    def account_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Account name must not be empty")
        return v.strip()


@router.get("/jfrog-password/{env}/account")
async def get_jfrog_password_account(
    env: str,
    current_user: dict = Depends(get_current_user),
):
    """Return the AD manager account JFrog binds as for this environment."""
    if env not in ("dev", "prod"):
        raise HTTPException(status_code=400, detail="env must be 'dev' or 'prod'")
    return {"env": env, "account": get_jfrog_manager_account(env)}


@router.post("/jfrog-password/{env}/test", status_code=status.HTTP_200_OK)
async def test_jfrog_password(
    env: str,
    body: JFrogPasswordRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """
    Validate the candidate LDAP manager password against JFrog's Access
    LDAP test endpoint WITHOUT saving. Returns {ok, message, status_code}.
    """
    if env not in ("dev", "prod"):
        raise HTTPException(status_code=400, detail="env must be 'dev' or 'prod'")
    try:
        result = await asyncio.to_thread(test_jfrog_ldap_credentials, env, body.password)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    audit.log_event(
        f"automation.jfrog_password_test_{env}",
        current_user["username"],
        details={"env": env, "ok": result.get("ok"), "status_code": result.get("status_code")},
        ip=request.client.host if request.client else None,
    )
    return result


@router.post("/jfrog-password/{env}", status_code=status.HTTP_200_OK)
async def update_jfrog_password(
    env: str,
    body: JFrogPasswordRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """
    Update the LDAP manager password for JFrog Artifactory (dev or prod).
    Tests the credential first via the JFrog test endpoint and refuses to
    save if validation fails. Password is transmitted over HTTPS and never
    logged.
    """
    if env not in ("dev", "prod"):
        raise HTTPException(status_code=400, detail="env must be 'dev' or 'prod'")

    # Belt-and-suspenders: even if the frontend skips its own test step,
    # validate before we touch the live LDAP config.
    try:
        test = await asyncio.to_thread(test_jfrog_ldap_credentials, env, body.password)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if not test.get("ok"):
        raise HTTPException(
            status_code=400,
            detail=f"LDAP credential test failed before save: {test.get('message')}",
        )

    try:
        result = await asyncio.to_thread(update_jfrog_ldap_password, env, body.password)
    except RuntimeError as exc:
        logger.error("JFrog %s LDAP password update failed: %s", env, exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    audit.log_event(
        f"automation.jfrog_password_{env}",
        current_user["username"],
        details={"env": env, "tested": True},
        ip=request.client.host if request.client else None,
    )
    return {**result, "test": test}


# ─── Artifactory user unlock ──────────────────────────────────────────────────


@router.post("/jfrog-unlock/{env}", status_code=status.HTTP_200_OK)
async def jfrog_unlock(
    env: str,
    body: UsernameRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """Unlock a locked-out Artifactory user via the security API."""
    if env not in ("dev", "prod"):
        raise HTTPException(status_code=400, detail="env must be 'dev' or 'prod'")
    try:
        result = await asyncio.to_thread(unlock_artifactory_user, env, body.username)
    except (RuntimeError, ValueError) as exc:
        logger.error("Artifactory %s unlock failed for %s: %s", env, body.username, exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    audit.log_event(
        f"automation.jfrog_unlock_{env}",
        current_user["username"],
        details={"env": env, "username": body.username},
        ip=request.client.host if request.client else None,
    )
    return result


# ─── SonarQube user-access lookup ─────────────────────────────────────────────


@router.post("/sonarqube-access/{env}", status_code=status.HTTP_200_OK)
async def sonarqube_access_lookup(
    env: str,
    body: UsernameRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """Read-only: confirm whether a user is provisioned in SonarQube and list the
    application projects they can access (derived from their group memberships)."""
    if env not in ("dev", "prod"):
        raise HTTPException(status_code=400, detail="env must be 'dev' or 'prod'")
    try:
        result = await asyncio.to_thread(sonarqube_access.get_user_access, env, body.username)
    except httpx.HTTPError as exc:
        logger.error("SonarQube %s access lookup failed for %s: %s", env, body.username, exc)
        raise HTTPException(status_code=502, detail=f"SonarQube API error: {exc}") from exc

    audit.log_event(
        f"automation.sonarqube_access_{env}",
        current_user["username"],
        details={"env": env, "username": body.username, "found": result.get("found")},
        ip=request.client.host if request.client else None,
    )
    return result


# ─── Active Directory account unlock ──────────────────────────────────────────


@router.post("/ad-account-status", status_code=status.HTTP_200_OK)
async def ad_account_status(
    body: AccountRequest,
    current_user: dict = Depends(get_current_user),
):
    """Read-only check of an AD account's current lockout state (no modification)."""
    try:
        return await asyncio.to_thread(get_ad_account_status, body.account)
    except (RuntimeError, ValueError) as exc:
        logger.error("AD status check failed for %s: %s", body.account, exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/ad-unlock", status_code=status.HTTP_200_OK)
async def ad_unlock(
    body: AccountRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """Unlock a locked-out AD account (clears lockoutTime via a delegated svc account)."""
    try:
        result = await asyncio.to_thread(unlock_ad_account, body.account)
    except (RuntimeError, ValueError) as exc:
        logger.error("AD unlock failed for %s: %s", body.account, exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    audit.log_event(
        "automation.ad_unlock",
        current_user["username"],
        details={"account": body.account, "status": result.get("status")},
        ip=request.client.host if request.client else None,
    )
    return result


@router.post("/ad-reset-password", status_code=status.HTTP_200_OK)
async def ad_reset_password(
    body: AdResetRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """Reset an AD account's password (unicodePwd via LDAPS), optionally auto-generating
    it and/or saving it to 1Password."""
    from app.services.password_gen import generate_password
    from app.services.onepassword_service import upsert_ad_password

    password = generate_password() if body.generate else (body.password or "")
    if not password:
        raise HTTPException(status_code=400, detail="Provide a password or enable generate.")

    try:
        result = await asyncio.to_thread(reset_ad_password, body.account, password)
    except (RuntimeError, ValueError) as exc:
        logger.error("AD password reset failed for %s: %s", body.account, exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    # Persist to 1Password before returning so a generated password is never lost.
    op_result = None
    if body.save_to_1password and result.get("status") == "reset":
        try:
            op_result = await upsert_ad_password(body.account, password)
        except Exception as exc:  # non-fatal: AD is already reset
            logger.error("1Password upsert failed for %s: %s", body.account, exc)
            op_result = {"error": str(exc)}

    audit.log_event(
        "automation.ad_reset_password",
        current_user["username"],
        details={
            "account": body.account,
            "status": result.get("status"),
            "generated": body.generate,
            "onepassword": (op_result or {}).get("action") or (op_result or {}).get("error"),
        },
        ip=request.client.host if request.client else None,
    )

    resp = {**result, "onepassword": op_result}
    # Return the generated password once so the operator can capture it.
    if body.generate and result.get("status") == "reset":
        resp["generated_password"] = password
    return resp


async def _rotate_svc_account(
    account: str,
    env: str,
    body: "RotateRequest",
    tool_update_fn,
    tool_test_fn,
    tool: str,
    current_user: dict,
    request: Request,
    gate_on_verify: bool = True,
) -> dict:
    """Reset the AD password, bank it in 1Password, verify it over LDAP, then push
    it to the tool.

    Order is deliberate: AD -> 1Password -> LDAP verify -> tool. The password is
    banked before the tool update so a generated one is never lost.

    ``gate_on_verify`` (default True) HARD-gates the tool update on the LDAP bind
    test — an unverified password is never written into the tool (JFrog/CBJ). When
    False (Datadog Synthetics), the verify is *soft*: it is still attempted and
    reported, but the tool update proceeds regardless (AD reset success is the
    gate). A failed verify (when gated) or a tool-update failure is reported as a
    partial success (the account IS rotated in AD + saved; re-run once fixed).
    """
    from app.services.password_gen import generate_password
    from app.services.onepassword_service import upsert_ad_password

    if not account:
        raise HTTPException(status_code=502, detail="Could not determine the service account to rotate.")
    password = generate_password() if body.generate else (body.password or "")
    if not password:
        raise HTTPException(status_code=400, detail="Provide a password or enable generate.")

    # 1) Reset AD — hard failure aborts before anything else changes.
    try:
        ad = await asyncio.to_thread(reset_ad_password, account, password)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=502, detail=f"AD reset failed for {account}: {exc}") from exc
    if ad.get("status") != "reset":
        raise HTTPException(status_code=502, detail=f"AD reset did not succeed for {account}: {ad.get('message')}")

    # 2) Bank the new password in 1Password before touching the tool.
    op_result = None
    if body.save_to_1password:
        try:
            op_result = await upsert_ad_password(account, password)
        except Exception as exc:
            logger.error("1Password upsert failed for %s: %s", account, exc)
            op_result = {"error": str(exc)}

    # 3) Verify the new password with an LDAP bind (single, no-retry). This GATES
    #    the tool update so a password AD didn't actually accept is never pushed.
    try:
        test = await asyncio.to_thread(tool_test_fn, env, password)
    except Exception as exc:
        logger.error("%s %s LDAP verify raised after AD reset of %s: %s", tool, env, account, exc)
        test = {"ok": False, "message": f"verification error: {exc}"}
    verified = bool(test.get("ok"))

    # 4) Push to the tool. Hard-gated on verify by default; soft when
    #    gate_on_verify is False (verify is informational, update still runs).
    tool_result, tool_error = None, None
    if verified or not gate_on_verify:
        try:
            tool_result = await asyncio.to_thread(tool_update_fn, env, password)
        except Exception as exc:
            logger.error("%s %s tool update failed after AD reset of %s: %s", tool, env, account, exc)
            tool_error = str(exc)
    else:
        tool_error = f"tool update skipped — LDAP verification failed: {test.get('message')}"

    audit.log_event(
        f"automation.{tool}_rotate_{env}",
        current_user["username"],
        details={
            "env": env, "account": account, "generated": body.generate,
            "ad": ad.get("status"),
            "onepassword": (op_result or {}).get("action") or (op_result or {}).get("error"),
            "verified": verified,
            "tool_ok": verified and tool_error is None,
        },
        ip=request.client.host if request.client else None,
    )

    resp = {
        "status": "ok" if ((verified or not gate_on_verify) and not tool_error) else "partial",
        "env": env,
        "account": account,
        "ad_reset": ad,
        "onepassword": op_result,
        "verified": verified,
        "test": test,
        "tool": tool_result,
        "tool_error": tool_error,
    }
    if body.generate:
        resp["generated_password"] = password
    return resp


@router.post("/jfrog-rotate/{env}", status_code=status.HTTP_200_OK)
async def jfrog_rotate(
    env: str,
    body: RotateRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """Full rotation of the Artifactory LDAP manager svc account."""
    if env not in ("dev", "prod"):
        raise HTTPException(status_code=400, detail="env must be 'dev' or 'prod'")
    account = get_jfrog_manager_account(env)
    return await _rotate_svc_account(
        account, env, body, update_jfrog_ldap_password, test_jfrog_ldap_credentials, "jfrog", current_user, request
    )


@router.post("/cloudbees-rotate/{env}", status_code=status.HTTP_200_OK)
async def cloudbees_rotate(
    env: str,
    body: RotateRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """Full rotation of a CloudBees CJOC LDAP manager svc account."""
    try:
        info = await asyncio.to_thread(cloudbees_ldap.discover_manager_account, env)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    account = info.get("account")
    if not account:
        raise HTTPException(status_code=502, detail=info.get("error") or "Could not determine the CBJ manager account.")
    return await _rotate_svc_account(
        account, env, body, cloudbees_ldap.update_password, cloudbees_ldap.test_credentials, "cloudbees", current_user, request
    )


@router.post("/datadog-synthetics-rotate/{sel}", status_code=status.HTTP_200_OK)
async def datadog_synthetics_rotate(
    sel: str,
    body: RotateRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """Full rotation of a Datadog Synthetics svc account (dso-synthetics-a|b).

    Resets the AD password, banks it in 1Password, softly verifies it over LDAP,
    then writes the new password into the matching Datadog secure global variable
    (DSO_SYNTHETICS_A/B_PASSWORD). The LDAP verify is informational — the Datadog
    write proceeds on AD-reset success (gate_on_verify=False)."""
    from app.services import datadog_synthetics
    sel = (sel or "").strip().lower()
    if sel not in ("a", "b"):
        raise HTTPException(status_code=400, detail="sel must be 'a' or 'b'")
    account = datadog_synthetics.account_for(sel)
    return await _rotate_svc_account(
        account, sel, body,
        datadog_synthetics.update_global_variable,
        datadog_synthetics.test_synthetics_ldap,
        "datadog_synthetics", current_user, request,
        gate_on_verify=False,
    )


# ─── Repository Cache Refresh / Reindex (prod only) ───────────────────────────


class RepoRefreshRequest(BaseModel):
    repos: list[str]
    package: str | None = None  # optional path/package to target on remote repos

    @field_validator("repos")
    @classmethod
    def repos_not_empty(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("Select at least one repository")
        return v


@router.get("/repo-refresh/repos")
async def repo_refresh_list(current_user: dict = Depends(get_current_user)):
    """List prod Artifactory repositories (key, type, package_type) for selection."""
    try:
        repos = await asyncio.to_thread(repo_refresh.list_repos)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"repos": repos}


@router.post("/repo-refresh")
async def repo_refresh_run(
    body: RepoRefreshRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """
    Refresh caches (remote) or recalculate index (local/virtual) for the
    selected PROD repos. Remote repos are refreshed by deleting cached content
    so Artifactory re-fetches from upstream; a package/path may be supplied to
    target a single package instead of the whole repo cache.
    """
    try:
        results = await asyncio.to_thread(
            repo_refresh.refresh_repos, body.repos, body.package
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    audit.log_event(
        "automation.repo_refresh",
        current_user["username"],
        details={
            "repos": body.repos,
            "package": body.package or None,
            "ok": sum(1 for r in results if r.get("ok")),
            "total": len(results),
        },
        ip=request.client.host if request.client else None,
    )
    return {"results": results}


# ─── Wildcard cert export ─────────────────────────────────────────────────────


@router.get("/cert-export/targets")
async def cert_export_targets(current_user: dict = Depends(get_current_user)):
    """List (tool, env) export targets and whether each is fully configured."""
    out = []
    for (tool, env) in cert_export.DEPLOY_TARGET:
        ready, reason = cert_export.target_ready(tool, env)
        out.append({"tool": tool, "env": env, "configured": ready, "reason": reason})
    return {"targets": out}


@router.post("/cert-export/{tool}/{env}")
async def cert_export_run(
    tool: str,
    env: str,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """Export the wildcard cert for tool/env: store in 1Password, produce a
    SOPS-encrypted TLS secret, and open a PR against main."""
    if (tool, env) not in cert_export.DEPLOY_TARGET:
        raise HTTPException(status_code=404, detail=f"Unknown target {tool}/{env}")
    try:
        result = await cert_export.run_export(tool, env, username=current_user.get("username"))
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    audit.log_event(
        "automation.cert_export",
        current_user["username"],
        details={"tool": tool, "env": env, "pr_url": result.get("pr_url")},
        ip=request.client.host if request.client else None,
    )
    return result


# ─── Copy Controllers ─────────────────────────────────────────────────────────


class CopyControllerPreviewRequest(BaseModel):
    controller_name: str


class CopyControllerRunRequest(BaseModel):
    controller_name: str
    aws_roles: list[str] = []
    network_ranges: list[str] = []
    admins: list[str] = []
    cldspt_ticket: str = "CLDSPT-99999"
    fisma_id: str = "test"
    migrate_all_jobs: bool = False
    job_list: list[str] = []
    copy_secrets: bool = False
    copy_plugins: bool = False


@router.post("/copy-controller/preview")
async def copy_controller_preview(
    body: CopyControllerPreviewRequest,
    current_user: dict = Depends(get_current_user),
):
    """Best-effort discovery of a prod-east controller's AWS roles, CIDRs, and admins."""
    try:
        return await asyncio.to_thread(preview_copy_controller, body.controller_name)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Copy controller preview failed: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/copy-controller/run", status_code=status.HTTP_201_CREATED)
async def copy_controller_run(
    body: CopyControllerRunRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """Trigger the cbc-onboarding-casc Jenkins job to create the dev-east controller."""
    # Use the engineer's persistent dev-east token. The service's configured
    # credentials remain the fallback if a token could not be issued.
    dev_token = current_user.get("jenkins_dev_token")
    auth = (current_user["username"], dev_token) if dev_token else None

    try:
        result = await asyncio.to_thread(
            run_copy_controller,
            controller_name=body.controller_name,
            aws_roles=body.aws_roles,
            network_ranges=body.network_ranges,
            admins=body.admins,
            cldspt_ticket=body.cldspt_ticket,
            fisma_id=body.fisma_id,
            migrate_all_jobs=body.migrate_all_jobs,
            job_list=body.job_list,
            copy_secrets=body.copy_secrets,
            copy_plugins=body.copy_plugins,
            auth=auth,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Copy controller run failed: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    audit.log_event(
        "automation.copy_controller",
        current_user["username"],
        details={
            "controller_name": body.controller_name,
            "migrate_all_jobs": body.migrate_all_jobs,
            "job_count": len(body.job_list),
            "copy_secrets": body.copy_secrets,
            "copy_plugins": body.copy_plugins,
            "build_url": result.get("build_url") or result.get("queue_url"),
        },
        ip=request.client.host if request.client else None,
    )
    return result


@router.get("/copy-controller/{controller_name}/status")
async def copy_controller_status(
    controller_name: str,
    build_url: str | None = None,
    current_user: dict = Depends(get_current_user),
):
    """
    Poll the state of an in-progress Copy Controllers run.

    Returns whether the dev-east controller is online, and if a build_url is
    supplied, the current onboarding build status. Frontend polls this while
    the ResultPanel is open so it can gate the Apply buttons and show live
    progress.
    """
    existence = await asyncio.to_thread(check_controller_exists_on_dev, controller_name)
    payload: dict = {
        "controller_name":         controller_name,
        "controller_exists_on_dev": existence.get("exists", False),
        "existence_error":         existence.get("error"),
        "build_url":               build_url,
        "build_number":            None,
        "build_building":          None,
        "build_result":            None,
        "build_error":             None,
    }
    if build_url:
        info = await asyncio.to_thread(get_dev_build_info, build_url)
        payload["build_number"]   = info.get("number")
        payload["build_building"] = info.get("building")
        payload["build_result"]   = info.get("result")   # SUCCESS | FAILURE | ABORTED | UNSTABLE | None
        payload["build_error"]    = info.get("error")
    return payload


class ApplySecretsRequest(BaseModel):
    controller_name: str
    encoded: str


@router.post("/copy-controller/apply-secrets")
async def copy_controller_apply_secrets(
    body: ApplySecretsRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """Apply previously-exported credentials onto the dev controller's Script Console."""
    try:
        result = await asyncio.to_thread(
            apply_credentials_to_dev, body.controller_name, body.encoded,
        )
    except Exception as exc:
        logger.error("Apply secrets to %s failed: %s", body.controller_name, exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if result.get("error"):
        raise HTTPException(status_code=502, detail=result["error"])

    audit.log_event(
        "automation.copy_controller_apply_secrets",
        current_user["username"],
        details={"controller_name": body.controller_name, "output": result.get("output", "")[:300]},
        ip=request.client.host if request.client else None,
    )
    return result


class CloudBeesPasswordRequest(BaseModel):
    password: str

    @field_validator("password")
    @classmethod
    def password_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Password must not be empty")
        return v


@router.get("/cloudbees-password/envs")
async def cloudbees_password_envs(current_user: dict = Depends(get_current_user)):
    """Return the list of supported CloudBees CJOC environments for the picker."""
    return {"envs": cloudbees_ldap.known_envs()}


@router.get("/cloudbees-password/{env}/account")
async def cloudbees_password_account(
    env: str,
    current_user: dict = Depends(get_current_user),
):
    """Auto-discover the LDAP manager account currently set on the CJOC."""
    try:
        result = await asyncio.to_thread(cloudbees_ldap.discover_manager_account, env)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return result


@router.post("/cloudbees-password/{env}/test", status_code=status.HTTP_200_OK)
async def cloudbees_password_test(
    env: str,
    body: CloudBeesPasswordRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """Validate the candidate LDAP manager password against AD via ldap3."""
    try:
        result = await asyncio.to_thread(cloudbees_ldap.test_credentials, env, body.password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    audit.log_event(
        f"automation.cloudbees_password_test_{env}",
        current_user["username"],
        details={"env": env, "ok": result.get("ok")},
        ip=request.client.host if request.client else None,
    )
    return result


@router.post("/cloudbees-password/{env}", status_code=status.HTTP_200_OK)
async def cloudbees_password_update(
    env: str,
    body: CloudBeesPasswordRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """Test then save the CloudBees CJOC LDAP manager password."""
    try:
        test = await asyncio.to_thread(cloudbees_ldap.test_credentials, env, body.password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if not test.get("ok"):
        raise HTTPException(
            status_code=400,
            detail=f"LDAP credential test failed before save: {test.get('message')}",
        )

    try:
        result = await asyncio.to_thread(cloudbees_ldap.update_password, env, body.password)
    except RuntimeError as exc:
        logger.error("CloudBees %s password update failed: %s", env, exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    audit.log_event(
        f"automation.cloudbees_password_{env}",
        current_user["username"],
        details={"env": env, "tested": True},
        ip=request.client.host if request.client else None,
    )
    return {**result, "test": test}


class ApplyJobsRequest(BaseModel):
    controller_name: str
    payload: str   # base64-encoded JSON list from the export step


@router.post("/copy-controller/apply-jobs")
async def copy_controller_apply_jobs(
    body: ApplyJobsRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """Apply previously-exported jobs/folders onto the dev controller's Script Console."""
    try:
        result = await asyncio.to_thread(
            apply_jobs_to_dev, body.controller_name, body.payload,
        )
    except Exception as exc:
        logger.error("Apply jobs to %s failed: %s", body.controller_name, exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if result.get("error"):
        raise HTTPException(status_code=502, detail=result["error"])

    audit.log_event(
        "automation.copy_controller_apply_jobs",
        current_user["username"],
        details={
            "controller_name": body.controller_name,
            "items_in_payload": result.get("items_in_payload", 0),
            "output": (result.get("output", "") or "")[:300],
        },
        ip=request.client.host if request.client else None,
    )
    return result


# ─── Controller PVC cleanup (prod-east) ────────────────────────────────────

class PrunePvcRequest(BaseModel):
    """Prune a controller's JENKINS_HOME. Refuses unless the ADO has signed off."""
    categories: list[str]
    ado_confirmed: bool = False
    ado: str | None = None          # who approved (for the audit trail)
    keep_builds: int = pvc_cleanup.DEFAULT_KEEP_BUILDS
    dry_run: bool = True
    pct: float | None = None        # %used at prune time (from the loaded usage view, for the CLDSPT ticket)

    @field_validator("categories")
    @classmethod
    def categories_not_empty(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("Select at least one category to prune")
        return v


@router.get("/pvc-cleanup/controllers")
async def pvc_cleanup_controllers(current_user: dict = Depends(get_current_user)):
    """List prod-east controllers at/over the PVC warn/crit thresholds (via Datadog)."""
    return await asyncio.to_thread(pvc_cleanup.list_controllers)


@router.get("/pvc-cleanup/{controller}/usage")
async def pvc_cleanup_usage(
    controller: str,
    current_user: dict = Depends(get_current_user),
):
    """Disk breakdown + ADO admins (resolved to Slack handles) + a ready-to-send message."""
    engineer = current_user.get("display_name") or current_user.get("username", "")
    result = await asyncio.to_thread(pvc_cleanup.controller_usage, controller, engineer)
    if result.get("error"):
        raise HTTPException(status_code=502, detail=result["error"])
    return result


@router.post("/pvc-cleanup/{controller}/email-ado")
async def pvc_cleanup_email_ado(
    controller: str,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """Email the controller's ADO admins a formatted disk-usage analysis + sign-off
    request via the CMS SMTP relay (cc: the DevOps distro)."""
    engineer = current_user.get("display_name") or current_user.get("username", "")
    result = await asyncio.to_thread(pvc_cleanup.email_ado, controller, engineer)
    if not result.get("sent"):
        raise HTTPException(status_code=502, detail=result.get("error") or "Email failed to send.")
    audit.log_event(
        "automation.pvc_cleanup_email_ado",
        current_user["username"],
        details={"controller": controller, "to": result.get("to"), "cc": result.get("cc")},
        ip=request.client.host if request.client else None,
    )
    return result


@router.post("/pvc-cleanup/{controller}/prune")
async def pvc_cleanup_prune(
    controller: str,
    body: PrunePvcRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """Start an async prune on a controller and return immediately (poll the
    status endpoint for progress). ADO-gated; a real deletion also requires the
    PVC_PRUNE_ENABLED server flag. dry_run=true just counts."""
    if not body.ado_confirmed:
        raise HTTPException(status_code=403, detail="ADO confirmation is required before pruning")

    result = await asyncio.to_thread(
        pvc_cleanup.start_prune,
        controller,
        body.categories,
        body.ado_confirmed,
        body.keep_builds,
        body.dry_run,
    )
    if result.get("denied"):
        raise HTTPException(status_code=403, detail=result["error"])
    if result.get("error"):
        raise HTTPException(status_code=502, detail=result["error"])

    # Audit the kickoff of a real deletion (not dry-run), with the approver.
    if not body.dry_run and result.get("state") in ("started", "already_running"):
        audit.log_event(
            "automation.pvc_cleanup_prune_start",
            current_user["username"],
            details={
                "controller": controller,
                "categories": result.get("categories"),
                "keep_builds": body.keep_builds,
                "ado": body.ado,
                "state": result.get("state"),
            },
            ip=request.client.host if request.client else None,
        )

        # Document the prune in a DMSC ticket (best-effort — never block the
        # prune on a Jira hiccup). Only for a freshly-started real run. Pointed 1,
        # added to the active sprint, and assigned to the triggering engineer.
        if result.get("state") == "started":
            engineer = current_user.get("display_name") or current_user.get("username", "")
            try:
                # Prefer the %used the UI already loaded; only fall back to a
                # (slow) Script Console call if the caller didn't send it.
                pct = body.pct if body.pct is not None else await asyncio.to_thread(_pvc_pct_for_ticket, controller)
                ticket = await asyncio.to_thread(
                    jira_service.create_dmsc_prune_ticket,
                    controller,
                    pct,
                    result.get("categories") or body.categories,
                    body.keep_builds,
                    body.ado,
                    engineer,
                )
                result["cldspt"] = ticket   # response key kept for UI compat; now a DMSC ticket

                # Assign the ticket to the engineer who triggered the prune.
                # Separate best-effort step: keep the audit ticket even if the
                # assign is rejected.
                assignee = current_user["username"]
                try:
                    await asyncio.to_thread(jira_service.assign_ticket, ticket["key"], assignee)
                    ticket["assignee"] = assignee
                except Exception as exc:  # noqa: BLE001 — assignment is non-fatal
                    logging.getLogger(__name__).warning(
                        "DMSC ticket %s created but assign to %s failed: %s",
                        ticket.get("key"), assignee, exc)
                    result["cldspt_assign_error"] = (
                        f"Ticket {ticket.get('key')} created but could not be assigned "
                        f"to {assignee}: {exc}")

                audit.log_event(
                    "automation.pvc_cleanup_ticket_created",
                    current_user["username"],
                    details={"controller": controller, "ticket": ticket.get("key"),
                             "assignee": ticket.get("assignee"), "sprint_id": ticket.get("sprint_id")},
                    ip=request.client.host if request.client else None,
                )
            except Exception as exc:  # noqa: BLE001 — ticketing is non-fatal
                logging.getLogger(__name__).warning("DMSC prune ticket creation failed: %s", exc)
                result["cldspt_error"] = f"Prune started, but ticket creation failed: {exc}"
    return result


def _pvc_pct_for_ticket(controller: str) -> float:
    """Best-effort current %used for the CLDSPT ticket (falls back to 0.0)."""
    try:
        usage = pvc_cleanup.controller_usage(controller)
        return usage.get("pct", 0.0) if not usage.get("error") else 0.0
    except Exception:  # noqa: BLE001
        return 0.0


class PruneCompleteRequest(BaseModel):
    """Record the outcome of a completed prune on its CLDSPT ticket."""
    ticket_key: str
    reclaimed_bytes: int = 0
    items: int = 0
    report: dict | None = None


@router.post("/pvc-cleanup/{controller}/prune-complete")
async def pvc_cleanup_prune_complete(
    controller: str,
    body: PruneCompleteRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """Append the freed-space outcome to the prune's CLDSPT ticket. Idempotency is
    the caller's responsibility (fire once when the run reaches 'done')."""
    gb = body.reclaimed_bytes / 1024 ** 3
    parts = ", ".join(f"{k}: {v.get('items', 0)}" for k, v in (body.report or {}).items() if isinstance(v, dict))
    engineer = current_user.get("display_name") or current_user.get("username", "")
    comment = (
        f"h4. Prune complete\n"
        f"* *Freed:* {gb:.1f} GB\n"
        f"* *Items removed:* {body.items}\n"
        + (f"* *Breakdown:* {parts}\n" if parts else "")
        + f"* *Completed by:* {engineer}"
    )
    try:
        await asyncio.to_thread(jira_service.comment_ticket, body.ticket_key, comment)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Could not comment on {body.ticket_key}: {exc}")

    # Auto-close the DMSC ticket with resolution Fixed now that the prune is done
    # (best-effort — the freed-space comment above is the important record).
    closed = None
    try:
        closed = await asyncio.to_thread(jira_service.close_prune_ticket, body.ticket_key)
    except Exception as exc:  # noqa: BLE001 — closing is non-fatal
        logging.getLogger(__name__).warning("Could not close prune ticket %s: %s", body.ticket_key, exc)

    audit.log_event(
        "automation.pvc_cleanup_ticket_completed",
        current_user["username"],
        details={"controller": controller, "ticket": body.ticket_key,
                 "reclaimed_bytes": body.reclaimed_bytes, "items": body.items,
                 "closed": bool(closed)},
        ip=request.client.host if request.client else None,
    )
    return {"ok": True, "ticket": body.ticket_key, "closed": bool(closed)}


@router.get("/pvc-cleanup/{controller}/prune-status")
async def pvc_cleanup_prune_status(
    controller: str,
    current_user: dict = Depends(get_current_user),
):
    """Poll the current prune status marker on a controller (read-only)."""
    result = await asyncio.to_thread(pvc_cleanup.prune_status, controller)
    if result.get("error"):
        raise HTTPException(status_code=502, detail=result["error"])
    return result


# ─── CBJ resource-waste ADO email ──────────────────────────────────────────

_CBJ_ENVS = ("prod-east", "gc-prod-west")
_CBJ_TARGETS = ("agents", "controllers")


def _validate_cbj(env: str, target: str) -> None:
    if env not in _CBJ_ENVS:
        raise HTTPException(status_code=404, detail=f"Unknown environment '{env}'")
    if target not in _CBJ_TARGETS:
        raise HTTPException(status_code=400, detail=f"Unknown target '{target}'")


class CbjWasteEmailRequest(BaseModel):
    extra_emails: list[str] = []


@router.get("/cbj-waste/{env}/teams")
async def cbj_waste_teams(
    env: str,
    target: str = "agents",
    current_user: dict = Depends(get_current_user),
):
    """Teams (namespaces) with at least one wasteful container, aggregated and
    sorted by total CPU wasted. Populates the email tile's team picker."""
    _validate_cbj(env, target)
    try:
        return await asyncio.to_thread(cbj_waste.teams_with_waste, env, target)
    except Exception as exc:
        logger.warning("cbj-waste teams failed for %s/%s: %s", env, target, exc)
        raise HTTPException(status_code=502, detail=f"Could not load CBJ waste data for {env}: {exc}")


@router.get("/cbj-waste/{env}/{namespace}/ados")
async def cbj_waste_ados(
    env: str,
    namespace: str,
    target: str = "agents",
    current_user: dict = Depends(get_current_user),
):
    """Resolve the owning ADOs for one team + the wasteful containers + a drafted
    message for review. gc-prod-west returns no auto-resolved ADOs (manual entry)."""
    _validate_cbj(env, target)
    engineer = current_user.get("display_name") or current_user.get("username", "")
    try:
        return await asyncio.to_thread(cbj_waste.team_ados, env, target, namespace, engineer)
    except Exception as exc:
        logger.warning("cbj-waste ados failed for %s/%s/%s: %s", env, target, namespace, exc)
        raise HTTPException(status_code=502, detail=f"Could not resolve ADOs for {namespace}: {exc}")


@router.post("/cbj-waste/{env}/{namespace}/email-ado")
async def cbj_waste_email_ado(
    env: str,
    namespace: str,
    request: Request,
    body: CbjWasteEmailRequest,
    target: str = "agents",
    current_user: dict = Depends(get_current_user),
):
    """Email the team's ADOs a right-sizing request for their wasteful containers
    via the CMS SMTP relay (cc: the DevOps distro)."""
    _validate_cbj(env, target)
    engineer = current_user.get("display_name") or current_user.get("username", "")
    result = await asyncio.to_thread(
        cbj_waste.email_team, env, target, namespace, engineer, body.extra_emails,
    )
    if not result.get("sent"):
        raise HTTPException(status_code=502, detail=result.get("error") or "Email failed to send.")
    audit.log_event(
        "automation.cbj_waste_email_ado",
        current_user["username"],
        details={"env": env, "target": target, "namespace": namespace,
                 "to": result.get("to"), "cc": result.get("cc")},
        ip=request.client.host if request.client else None,
    )
    return result


# ─── Controller user audit + cleanup ──────────────────────────────────────────

class ControllerUserDeleteRequest(BaseModel):
    ids: list[str]
    confirm: bool = False


@router.get("/controller-users/{env}/summary")
async def controller_users_summary(
    env: str,
    current_user: dict = Depends(get_current_user),
):
    """Cached list of controllers that have deactivated users (+ sweep state)."""
    if env not in controller_users.ENVS:
        raise HTTPException(status_code=404, detail=f"Unknown environment '{env}'")
    return await asyncio.to_thread(controller_users.summary, env)


@router.post("/controller-users/{env}/sweep")
async def controller_users_sweep(
    env: str,
    current_user: dict = Depends(get_current_user),
):
    """Kick off a background sweep of every controller in the env."""
    if env not in controller_users.ENVS:
        raise HTTPException(status_code=404, detail=f"Unknown environment '{env}'")
    return await asyncio.to_thread(controller_users.start_background_sweep, env)


@router.get("/controller-users/{env}/sweep-status")
async def controller_users_sweep_status(
    env: str,
    current_user: dict = Depends(get_current_user),
):
    if env not in controller_users.ENVS:
        raise HTTPException(status_code=404, detail=f"Unknown environment '{env}'")
    return await asyncio.to_thread(controller_users.sweep_status, env)


@router.get("/controller-users/{env}/{controller}/audit")
async def controller_users_audit(
    env: str,
    controller: str,
    current_user: dict = Depends(get_current_user),
):
    """List a controller's users annotated with AD status (disabled = leaver)."""
    if env not in controller_users.ENVS:
        raise HTTPException(status_code=404, detail=f"Unknown environment '{env}'")
    result = await asyncio.to_thread(controller_users.audit_users, env, controller)
    if result.get("error"):
        raise HTTPException(status_code=502, detail=result["error"])
    return result


@router.post("/controller-users/{env}/{controller}/delete")
async def controller_users_delete(
    env: str,
    controller: str,
    body: ControllerUserDeleteRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """Delete AD-deactivated users from a controller. Only confirmed-disabled ids
    are removed; active/unknown ids are refused server-side."""
    if env not in controller_users.ENVS:
        raise HTTPException(status_code=404, detail=f"Unknown environment '{env}'")
    if not body.confirm:
        raise HTTPException(status_code=400, detail="Deletion must be confirmed.")
    result = await asyncio.to_thread(
        controller_users.delete_users, env, controller, body.ids, True,
    )
    if result.get("error"):
        raise HTTPException(status_code=502, detail=result["error"])
    audit.log_event(
        "automation.controller_users_delete",
        current_user["username"],
        details={"env": env, "controller": controller,
                 "deleted": result.get("deleted"), "refused": result.get("refused"),
                 "failed": result.get("failed")},
        ip=request.client.host if request.client else None,
    )
    return result


# ─── Artifactory user audit + cleanup ─────────────────────────────────────────

class ArtifactoryUserDeleteRequest(BaseModel):
    ids: list[str]
    confirm: bool = False


@router.get("/artifactory-users/{env}/summary")
async def artifactory_users_summary(
    env: str,
    current_user: dict = Depends(get_current_user),
):
    """Cached list of Artifactory projects that have deactivated members."""
    if env not in artifactory_users.ENVS:
        raise HTTPException(status_code=404, detail=f"Unknown environment '{env}'")
    return await asyncio.to_thread(artifactory_users.summary, env)


@router.post("/artifactory-users/{env}/sweep")
async def artifactory_users_sweep(
    env: str,
    current_user: dict = Depends(get_current_user),
):
    """Kick off a background sweep of every project in the env."""
    if env not in artifactory_users.ENVS:
        raise HTTPException(status_code=404, detail=f"Unknown environment '{env}'")
    return await asyncio.to_thread(artifactory_users.start_background_sweep, env)


@router.get("/artifactory-users/{env}/sweep-status")
async def artifactory_users_sweep_status(
    env: str,
    current_user: dict = Depends(get_current_user),
):
    if env not in artifactory_users.ENVS:
        raise HTTPException(status_code=404, detail=f"Unknown environment '{env}'")
    return await asyncio.to_thread(artifactory_users.sweep_status, env)


@router.get("/artifactory-users/{env}/{project}/audit")
async def artifactory_users_project_audit(
    env: str,
    project: str,
    current_user: dict = Depends(get_current_user),
):
    """List one project's members annotated with AD status (disabled = leaver)."""
    if env not in artifactory_users.ENVS:
        raise HTTPException(status_code=404, detail=f"Unknown environment '{env}'")
    result = await asyncio.to_thread(artifactory_users.audit_project, env, project)
    if result.get("error"):
        raise HTTPException(status_code=502, detail=result["error"])
    return result


@router.post("/artifactory-users/{env}/delete")
async def artifactory_users_delete(
    env: str,
    body: ArtifactoryUserDeleteRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """Delete AD-deactivated Artifactory users. Only confirmed-disabled ids are
    removed; active/unknown/system ids are refused server-side."""
    if env not in artifactory_users.ENVS:
        raise HTTPException(status_code=404, detail=f"Unknown environment '{env}'")
    if not body.confirm:
        raise HTTPException(status_code=400, detail="Deletion must be confirmed.")
    result = await asyncio.to_thread(artifactory_users.delete_users, env, body.ids, True)
    if result.get("error"):
        raise HTTPException(status_code=502, detail=result["error"])
    audit.log_event(
        "automation.artifactory_users_delete",
        current_user["username"],
        details={"env": env, "deleted": result.get("deleted"),
                 "refused": result.get("refused"), "failed": result.get("failed")},
        ip=request.client.host if request.client else None,
    )
    return result


# ─── CloudBees "Check User Access" (cached sweep + per-user lookup) ────────────

@router.post("/cloudbees-access/{env}", status_code=status.HTTP_200_OK)
async def cloudbees_access_lookup(
    env: str,
    body: UsernameRequest,
    current_user: dict = Depends(get_current_user),
):
    """Read-only: the user's CloudBees RBAC access across all controllers (from the
    daily sweep cache). env = prod-east | gc-prod-west."""
    if env not in cloudbees_access.ENVS:
        raise HTTPException(status_code=404, detail=f"Unknown environment '{env}'")
    result = await asyncio.to_thread(cloudbees_access.lookup, env, body.username)
    if result.get("error"):
        raise HTTPException(status_code=502, detail=result["error"])
    return result


@router.post("/cloudbees-access/{env}/sweep")
async def cloudbees_access_sweep(
    env: str,
    current_user: dict = Depends(get_current_user),
):
    """Kick off a background RBAC sweep of every controller in the env."""
    if env not in cloudbees_access.ENVS:
        raise HTTPException(status_code=404, detail=f"Unknown environment '{env}'")
    return await asyncio.to_thread(cloudbees_access.start_background_sweep, env)


@router.get("/cloudbees-access/{env}/sweep-status")
async def cloudbees_access_sweep_status(
    env: str,
    current_user: dict = Depends(get_current_user),
):
    if env not in cloudbees_access.ENVS:
        raise HTTPException(status_code=404, detail=f"Unknown environment '{env}'")
    return await asyncio.to_thread(cloudbees_access.sweep_status, env)


# ─── Artifactory "Check User Access" (live per-user lookup) ────────────────────

@router.post("/artifactory-access/{env}", status_code=status.HTTP_200_OK)
async def artifactory_access_lookup(
    env: str,
    body: UsernameRequest,
    current_user: dict = Depends(get_current_user),
):
    """Read-only: whether the user is provisioned in Artifactory + their groups,
    projects (with role), and permission targets. env = prod | dev."""
    if env not in artifactory_access.ENVS:
        raise HTTPException(status_code=404, detail=f"Unknown environment '{env}'")
    result = await asyncio.to_thread(artifactory_access.get_user_access, env, body.username)
    if result.get("error"):
        raise HTTPException(status_code=502, detail=result["error"])
    return result


# ─── CBJ pod-quota (fiftypods) audit + remediation ────────────────────────────

class QuotaIncreaseRequest(BaseModel):
    new_limit: int
    confirm: bool = False


class BuildAbortRequest(BaseModel):
    job: str
    number: int
    confirm: bool = False


class AbortAllRequest(BaseModel):
    confirm: bool = False
    older_than_days: int = 0   # 0 = abort all running builds


@router.get("/pod-quota/{env}/audit")
async def pod_quota_audit(env: str, current_user: dict = Depends(get_current_user)):
    """fiftypods used/hard for every controller in the env (worst-first)."""
    if env not in pod_quota.ENVS:
        raise HTTPException(status_code=404, detail=f"Unknown environment '{env}'")
    result = await asyncio.to_thread(pod_quota.audit, env)
    if result.get("error"):
        raise HTTPException(status_code=502, detail=result["error"])
    return result


@router.get("/pod-quota/{env}/{controller}/running-builds")
async def pod_quota_running_builds(env: str, controller: str, current_user: dict = Depends(get_current_user)):
    """Running builds on a controller, longest-running first (kill candidates)."""
    if env not in pod_quota.ENVS:
        raise HTTPException(status_code=404, detail=f"Unknown environment '{env}'")
    result = await asyncio.to_thread(pod_quota.running_builds, env, controller)
    if result.get("error"):
        raise HTTPException(status_code=502, detail=result["error"])
    return result


@router.post("/pod-quota/{env}/{controller}/increase")
async def pod_quota_increase(
    env: str, controller: str, body: QuotaIncreaseRequest,
    request: Request, current_user: dict = Depends(get_current_user),
):
    """Raise the fiftypods pod limit (bounded, confirmed, audit-logged)."""
    if env not in pod_quota.ENVS:
        raise HTTPException(status_code=404, detail=f"Unknown environment '{env}'")
    if not body.confirm:
        raise HTTPException(status_code=400, detail="Increase must be confirmed.")
    result = await asyncio.to_thread(pod_quota.increase, env, controller, body.new_limit)
    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])
    audit.log_event(
        "automation.pod_quota_increase", current_user["username"],
        details={"env": env, "controller": controller,
                 "previous_hard": result.get("previous_hard"), "new_hard": result.get("hard")},
        ip=request.client.host if request.client else None,
    )
    return result


@router.post("/pod-quota/{env}/{controller}/abort-all-builds")
async def pod_quota_abort_all_builds(
    env: str, controller: str, body: AbortAllRequest,
    request: Request, current_user: dict = Depends(get_current_user),
):
    """Abort running builds in bulk (all, or older than N days). Confirmed + audit-logged."""
    if env not in pod_quota.ENVS:
        raise HTTPException(status_code=404, detail=f"Unknown environment '{env}'")
    if not body.confirm:
        raise HTTPException(status_code=400, detail="Abort-all must be confirmed.")
    result = await asyncio.to_thread(pod_quota.abort_all_builds, env, controller, body.older_than_days)
    if result.get("error"):
        raise HTTPException(status_code=502, detail=result["error"])
    audit.log_event(
        "automation.pod_quota_abort_all_builds", current_user["username"],
        details={"env": env, "controller": controller, "older_than_days": result.get("older_than_days"),
                 "aborted": result.get("aborted"), "failed": result.get("failed")},
        ip=request.client.host if request.client else None,
    )
    return result


@router.post("/pod-quota/{env}/{controller}/abort-build")
async def pod_quota_abort_build(
    env: str, controller: str, body: BuildAbortRequest,
    request: Request, current_user: dict = Depends(get_current_user),
):
    """Abort a running build to free its agent pod(s) (confirmed, audit-logged)."""
    if env not in pod_quota.ENVS:
        raise HTTPException(status_code=404, detail=f"Unknown environment '{env}'")
    if not body.confirm:
        raise HTTPException(status_code=400, detail="Abort must be confirmed.")
    result = await asyncio.to_thread(pod_quota.abort_build, env, controller, body.job, body.number)
    audit.log_event(
        "automation.pod_quota_abort_build", current_user["username"],
        details={"env": env, "controller": controller, "job": body.job,
                 "number": body.number, "aborted": result.get("aborted")},
        ip=request.client.host if request.client else None,
    )
    if result.get("error"):
        raise HTTPException(status_code=502, detail=result["error"])
    return result


class RegistryTokenRotateRequest(BaseModel):
    username: str
    password: str

    @field_validator("username", "password")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("username and password are required")
        return v.strip()


@router.get("/jfrog-registry-token/targets")
async def jfrog_registry_token_targets(current_user: dict = Depends(get_current_user)):
    """Environments whose JFrog entitlement secrets this tile can rotate."""
    return {"targets": jfrog_registry_token.targets()}


@router.get("/jfrog-registry-token/expiry")
async def jfrog_registry_token_expiry(current_user: dict = Depends(get_current_user)):
    """When the JFrog entitlement token stops working, for the reminder in the bell."""
    return jfrog_registry_token.expiry_status()


@router.post("/jfrog-registry-token/{env}/refresh", status_code=status.HTTP_200_OK)
async def jfrog_registry_token_auto_rotate(
    env: str,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """Request a new JFrog entitlement token with the stored refresh token, then
    rotate every secret that carries it for `env` and commit to the maintenance
    branch. The engineer supplies nothing."""
    if env not in jfrog_registry_token.ROTATE_TARGET:
        raise HTTPException(status_code=404, detail=f"Unknown environment '{env}'")

    settings = get_settings()
    if not settings.GITHUB_TOKEN:
        raise HTTPException(status_code=500, detail="GITHUB_TOKEN is not configured")

    try:
        result = await jfrog_registry_token.rotate_from_refresh_token(
            env, settings.GITHUB_TOKEN
        )
    except PermissionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    audit.log_event(
        "automation.jfrog_registry_token_refresh",
        current_user["username"],
        details={"env": env, "branch": result.get("branch"), "path": result.get("path"),
                 "refresh_token_rotated": result.get("refresh_token_rotated"),
                 "refresh_token_stored": result.get("refresh_token_stored")},
        ip=request.client.host if request.client else None,
    )
    return result


@router.post("/jfrog-registry-token/{env}", status_code=status.HTTP_200_OK)
async def jfrog_registry_token_rotate(
    env: str,
    body: RegistryTokenRotateRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """Verify the JFrog entitlement credential, re-encrypt every secret that carries
    it for `env`, and commit the result to the current maintenance branch."""
    if env not in jfrog_registry_token.ROTATE_TARGET:
        raise HTTPException(status_code=404, detail=f"Unknown environment '{env}'")

    settings = get_settings()
    if not settings.GITHUB_TOKEN:
        raise HTTPException(status_code=500, detail="GITHUB_TOKEN is not configured")

    try:
        result = await jfrog_registry_token.rotate(
            env, body.username, body.password, settings.GITHUB_TOKEN
        )
    except PermissionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    audit.log_event(
        "automation.jfrog_registry_token_rotate",
        current_user["username"],
        details={"env": env, "jfrog_user": body.username,
                 "branch": result.get("branch"), "path": result.get("path")},
        ip=request.client.host if request.client else None,
    )
    return result
