"""Regression coverage for reusing encrypted personal Jenkins tokens.

Run from backend/: python -m unittest discover -s tests -v
External LDAP/Jenkins calls are mocked; profile, vault, JWT and audit handling
use real application code with temporary storage and synthetic credentials.
"""
import json
import os
import tempfile
import unittest
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import jwt
from app.auth.ldap import AccessGroupError
from app.config import get_settings
from app.routers import auth, automation, maintenance, profile
from app.services import copy_controller, jenkins_auth, user_secrets


class DashboardJenkinsTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.stack.enter_context(patch.dict(os.environ, {
            "DEV_MODE": "false",
            "JWT_SECRET": "test-only-signing-key-not-a-real-secret",
            "PROFILES_DIR": str(root / "profiles"),
            "ROLES_FILE": str(root / "roles.json"),
            "AUDIT_DIR": str(root / "audit"),
            "ADMIN_USERS": "engineer",
            "ITC_AUTHORIZED_USERS": "engineer",
            "JENKINS_USER": "configured-prod-user",
            "JENKINS_TOKEN": "configured-default-token",
            "SONARQUBE_JENKINS_TOKEN": "configured-sonarqube-token",
            "JENKINS_DEV_USER": "configured-dev-user",
            "JENKINS_EAST_DEV_TOKEN": "configured-dev-token",
            "JENKINS_EAST_PROD_TOKEN": "configured-prod-east-token",
            "JENKINS_GOV_DEV_TOKEN": "configured-gov-dev-token",
            "JENKINS_GOV_PROD_TOKEN": "configured-gov-prod-token",
            "CLOUDBEES_EAST_DEV_URL": "https://jenkins-dev-east.cloud.cms.gov/cjoc",
            "CLOUDBEES_EAST_PROD_URL": "https://jenkins-east.cloud.cms.gov/cjoc",
            "CLOUDBEES_GOV_DEV_URL": "https://jenkins-gc-dev-west.cloud.cms.gov/cjoc",
            "CLOUDBEES_GOV_PROD_URL": "https://jenkins-gc-west.cloud.cms.gov/cjoc",
        }, clear=True))
        get_settings.cache_clear()
        self.stack.callback(get_settings.cache_clear)
        self.settings = get_settings()
        self.stack.enter_context(patch.dict(user_secrets._session_keys, {}, clear=True))
        async def fake_generate(cjoc_url, username, password, token_name):
            return {"token_value": f"secret-{token_name}", "token_uuid": f"uuid-{token_name}",
                    "token_name": token_name}
        self.generate_token = self.stack.enter_context(patch.object(
            jenkins_auth, "generate_jenkins_token", new_callable=AsyncMock,
            side_effect=fake_generate,
        ))
        self.stack.enter_context(patch.object(
            jenkins_auth, "_jenkins_token_is_valid", new_callable=AsyncMock, return_value=True,
        ))
        self.ldap = self.stack.enter_context(patch.object(auth, "authenticate_user", return_value={
            "username": "engineer", "display_name": "Test Engineer",
            "email": "engineer@example.invalid", "groups": ["DevOps"],
        }))
        # Any outgoing HTTP is a regression during auth tests, even if the
        # application swallows an exception as a best-effort token operation.
        self.sync_http = self.stack.enter_context(patch(
            "httpx.HTTPTransport.handle_request", side_effect=AssertionError("Unexpected HTTP")))
        self.async_http = self.stack.enter_context(patch(
            "httpx.AsyncHTTPTransport.handle_async_request", side_effect=AssertionError("Unexpected HTTP")))
        app = FastAPI()
        for router in (auth.router, maintenance.router, automation.router):
            app.include_router(router, prefix="/api")
        self.client = self.stack.enter_context(TestClient(app, base_url="https://testserver"))

    def login(self):
        return self.client.post("/api/auth/login", data={
            "username": "engineer", "password": "test-only-password",
        })

    def assert_no_http(self):
        self.sync_http.assert_not_called()
        self.async_http.assert_not_called()

    def legacy_session(self):
        claims = {
            "sub": "engineer", "display_name": "Test Engineer",
            "email": "engineer@example.invalid", "groups": ["DevOps"], "role": "admin",
            "jenkins_token": "legacy-prod-token", "jenkins_token_uuid": "legacy-prod-uuid",
            "jenkins_dev_token": "legacy-dev-token", "jenkins_dev_token_uuid": "legacy-dev-uuid",
        }
        self.client.cookies.clear()
        self.client.cookies.set("access_token", jwt.create_token(claims))
        return claims

    def audit_events(self):
        return [json.loads(line) for p in Path(self.settings.AUDIT_DIR).glob("*.jsonl")
                for line in p.read_text().splitlines()]

    def test_repeated_logins_reuse_encrypted_tokens_instead_of_creating_more(self):
        self.assertFalse(self.settings.DEV_MODE)
        for _ in range(3):
            response = self.login()
            self.assertEqual(response.status_code, 200)
            claims = jwt.verify_token(self.client.cookies.get("access_token"))
            self.assertEqual(claims["sub"], "engineer")
            self.assertEqual(claims["jenkins_token"], "secret-dashboard-prod-east")
            self.assertEqual(claims["jenkins_dev_token"], "secret-dashboard-dev-east")
            self.assertEqual(set(claims["jenkins_persistent_envs"]), {"prod-east", "dev-east"})
        self.assertEqual(self.ldap.call_count, 3)
        self.assertEqual(self.generate_token.await_count, 2)
        self.assertEqual(self.generate_token.await_args_list[0].kwargs["token_name"], "dashboard-prod-east")
        self.assertEqual(self.generate_token.await_args_list[1].kwargs["token_name"], "dashboard-dev-east")
        saved = json.dumps(profile.load_profile("engineer"))
        self.assertNotIn("secret-dashboard-prod-east", saved)
        self.assertNotIn("secret-dashboard-dev-east", saved)
        self.assert_no_http()

    def test_revoked_cached_token_is_replaced_and_saved_for_the_next_login(self):
        self.assertEqual(self.login().status_code, 200)
        self.assertEqual(self.generate_token.await_count, 2)
        with patch.object(jenkins_auth, "_jenkins_token_is_valid", new_callable=AsyncMock, return_value=False):
            self.assertEqual(self.login().status_code, 200)
        self.assertEqual(self.generate_token.await_count, 4)
        self.assertEqual(self.login().status_code, 200)
        self.assertEqual(self.generate_token.await_count, 4)
        self.assert_no_http()

    def test_token_creation_failure_keeps_login_and_configured_jenkins_fallback(self):
        self.generate_token.side_effect = None
        self.generate_token.return_value = None
        response = self.login()
        self.assertEqual(response.status_code, 200)
        claims = jwt.verify_token(self.client.cookies.get("access_token"))
        self.assertNotIn("jenkins_token", claims)
        self.assertNotIn("jenkins_dev_token", claims)
        with patch.object(maintenance, "get_job_params", return_value=[]) as params:
            self.assertEqual(self.client.get("/api/maintenance/sonarqube-params").status_code, 200)
        params.assert_called_once_with(self.settings.SONARQUBE_JOB_URL,
                                       auth=("configured-prod-user", "configured-sonarqube-token"))
        with patch.object(copy_controller, "check_controller_exists_on_dev", return_value={"exists": False}), \
                patch.object(copy_controller, "trigger_job", return_value={"status": "queued"}) as trigger:
            result = self.client.post("/api/automation/copy-controller/run", json={"controller_name": "new"})
        self.assertEqual(result.status_code, 201)
        self.assertEqual(trigger.call_args.kwargs["auth"], ("configured-dev-user", "configured-dev-token"))
        self.assert_no_http()

    def test_login_token_reuse_keeps_all_four_environment_credential_mappings(self):
        from app.services.cloudbees_ldap import _resolve_env

        expected = {
            "dev-east": ("https://jenkins-dev-east.cloud.cms.gov/cjoc",
                         ("configured-dev-user", "configured-dev-token")),
            "prod-east": ("https://jenkins-east.cloud.cms.gov/cjoc",
                          ("dso-jenkins-prod-a", "configured-prod-east-token")),
            "gc-dev-west": ("https://jenkins-gc-dev-west.cloud.cms.gov/cjoc",
                            ("configured-dev-user", "configured-gov-dev-token")),
            "gc-prod-west": ("https://jenkins-gc-west.cloud.cms.gov/cjoc",
                             ("dso-jenkins-prod-a", "configured-gov-prod-token")),
        }
        for env, configured in expected.items():
            self.assertEqual(_resolve_env(env), configured)

        response = self.login()
        self.assertEqual(response.status_code, 200)
        claims = jwt.verify_token(self.client.cookies.get("access_token"))
        self.assertEqual(claims["jenkins_token"], "secret-dashboard-prod-east")
        self.assertEqual(claims["jenkins_dev_token"], "secret-dashboard-dev-east")
        self.assertEqual(self.generate_token.await_count, 2)
        self.assert_no_http()

    def test_login_preserves_cookie_profile_role_vault_and_audit_behavior(self):
        profile.save_profile("engineer", {"display_name": "Saved Name", "team": "Cloud"})
        response = self.login()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["display_name"], "Saved Name")
        self.assertEqual(response.json()["team"], "Cloud")
        self.assertEqual(response.json()["role"], "admin")
        self.assertTrue(response.json()["jira_authorized"])
        cookie = response.headers["set-cookie"].lower()
        for flag in ("httponly", "secure", "samesite=lax", "max-age=28800"):
            self.assertIn(flag, cookie)
        key = user_secrets.get_session_key("engineer")
        ciphertext = user_secrets.encrypt(key, "test-github-pat")
        self.assertEqual(user_secrets.decrypt(key, ciphertext), "test-github-pat")
        me = self.client.get("/api/auth/me")
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json()["display_name"], "Saved Name")
        self.assertFalse(any(key.startswith("jenkins_") for key in me.json()))
        self.assertEqual(self.audit_events()[-1]["event"], "auth.login")
        self.assert_no_http()

    def test_failed_ldap_login_still_returns_401_without_cookie_or_jenkins_calls(self):
        self.ldap.return_value = None
        response = self.login()
        self.assertEqual(response.status_code, 401)
        self.assertNotIn("set-cookie", response.headers)
        self.assertFalse(user_secrets.session_unlocked("engineer"))
        self.assert_no_http()

    def test_access_group_rejection_still_returns_403(self):
        self.ldap.side_effect = AccessGroupError()
        response = self.login()
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"], "You are not part of the Access group.")
        self.assert_no_http()

    def test_new_session_logout_clears_cookie_and_vault_without_jenkins_calls(self):
        self.login()
        with patch.object(jenkins_auth, "revoke_jenkins_token", new_callable=AsyncMock) as revoke:
            response = self.client.post("/api/auth/logout")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Max-Age=0", response.headers["set-cookie"])
        self.assertFalse(user_secrets.session_unlocked("engineer"))
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)
        self.assertEqual(self.audit_events()[-1]["event"], "auth.logout")
        revoke.assert_not_awaited()
        self.assertTrue(profile.load_profile("engineer").get("jenkins_api_tokens"))
        self.assert_no_http()

    def test_legacy_logout_attempts_cleanup_for_both_environments(self):
        self.legacy_session()
        with patch.object(jenkins_auth, "revoke_jenkins_token", new_callable=AsyncMock, return_value=True) as revoke:
            response = self.client.post("/api/auth/logout")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(revoke.await_count, 2)
        revoke.assert_any_await(self.settings.JENKINS_CJOC_URL, "engineer", "legacy-prod-token", "legacy-prod-uuid")
        revoke.assert_any_await(self.settings.JENKINS_DEV_EAST_CJOC_URL, "engineer", "legacy-dev-token", "legacy-dev-uuid")
        self.assert_no_http()

    def test_legacy_revoke_failure_does_not_break_logout(self):
        self.legacy_session()
        with patch.object(jenkins_auth, "revoke_jenkins_token", new_callable=AsyncMock, return_value=False) as revoke:
            response = self.client.post("/api/auth/logout")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(revoke.await_count, 2)
        self.assertIn("Max-Age=0", response.headers["set-cookie"])
        self.assert_no_http()

    def test_login_after_expired_session_reuses_or_creates_tokens_without_requiring_old_session(self):
        old = datetime.now(timezone.utc) - timedelta(hours=9)
        with patch.object(jwt, "datetime") as clock:
            clock.now.return_value = old
            self.legacy_session()
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)
        self.client.cookies.clear()
        self.assertEqual(self.login().status_code, 200)
        claims = jwt.verify_token(self.client.cookies.get("access_token"))
        self.assertIn("jenkins_token", claims)
        self.assertEqual(len(claims["jenkins_persistent_envs"]), 2)
        self.assert_no_http()

    def test_sonarqube_params_and_deploy_use_existing_configured_credentials(self):
        self.login()
        with patch.object(maintenance, "get_job_params", return_value=[{"name": "VERSION"}]) as params:
            response = self.client.get("/api/maintenance/sonarqube-params")
        self.assertEqual(response.status_code, 200)
        params.assert_called_once_with(self.settings.SONARQUBE_JOB_URL,
                                       auth=("engineer", "secret-dashboard-prod-east"))
        with patch.object(maintenance, "trigger_job", return_value={"status": "queued"}) as trigger:
            response = self.client.post("/api/maintenance/sonarqube-dev", json={"params": {"VERSION": "test"}})
        self.assertEqual(response.status_code, 200)
        trigger.assert_called_once_with(job_url=self.settings.SONARQUBE_JOB_URL,
                                        params={"VERSION": "test"},
                                        auth=("engineer", "secret-dashboard-prod-east"))
        event = self.audit_events()[-1]
        self.assertEqual((event["event"], event["username"]), ("maintenance.sonarqube_deploy", "engineer"))
        self.assert_no_http()

    def test_copy_controller_preserves_dev_credentials_params_and_audit(self):
        self.login()
        with patch.object(copy_controller, "check_controller_exists_on_dev", return_value={"exists": False}), \
                patch.object(copy_controller, "trigger_job", return_value={"status": "queued"}) as trigger:
            response = self.client.post("/api/automation/copy-controller/run", json={
                "controller_name": "test-team", "aws_roles": ["role1"],
                "network_ranges": ["10.0.0.0/24"], "admins": ["engineer"],
                "cldspt_ticket": "CLDSPT-123", "fisma_id": "test-fisma",
            })
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["status"], "queued")
        args, kwargs = trigger.call_args
        self.assertEqual(args[0], f"{self.settings.JENKINS_DEV_EAST_TOOLING_URL}/{self.settings.CBC_ONBOARDING_JOB_PATH}")
        self.assertEqual(args[1], {"TEAM_NAME": "test-team", "CLDSPT_TICKET": "CLDSPT-123",
                                   "AWS_ROLES": "role1", "NETWORK_RANGES": "10.0.0.0/24",
                                   "ADMINS": "engineer", "FISMAID": "test-fisma"})
        self.assertEqual(kwargs["auth"], ("engineer", "secret-dashboard-dev-east"))
        event = self.audit_events()[-1]
        self.assertEqual((event["event"], event["username"]), ("automation.copy_controller", "engineer"))
        self.assert_no_http()

    def test_copy_controller_keeps_existing_controller_idempotency(self):
        self.login()
        with patch.object(copy_controller, "check_controller_exists_on_dev", return_value={"exists": True}), \
                patch.object(copy_controller, "trigger_job") as trigger:
            response = self.client.post("/api/automation/copy-controller/run", json={"controller_name": "existing"})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["status"], "skipped_already_exists")
        trigger.assert_not_called()
        self.assert_no_http()

    def test_copy_controller_keeps_existing_default_token_fallback(self):
        self.settings.JENKINS_EAST_DEV_TOKEN = ""
        claims = self.legacy_session()
        claims.pop("jenkins_dev_token")
        claims.pop("jenkins_dev_token_uuid")
        self.client.cookies.set("access_token", jwt.create_token(claims))
        with patch.object(copy_controller, "check_controller_exists_on_dev", return_value={"exists": False}), \
                patch.object(copy_controller, "trigger_job", return_value={"status": "queued"}) as trigger:
            response = self.client.post("/api/automation/copy-controller/run", json={"controller_name": "new"})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(trigger.call_args.kwargs["auth"], ("configured-dev-user", "configured-default-token"))
        self.assert_no_http()

    def test_pre_upgrade_sessions_keep_their_existing_job_credentials(self):
        self.legacy_session()
        with patch.object(maintenance, "get_job_params", return_value=[]) as params:
            self.assertEqual(self.client.get("/api/maintenance/sonarqube-params").status_code, 200)
        self.assertEqual(params.call_args.kwargs["auth"], ("engineer", "legacy-prod-token"))
        with patch.object(automation, "run_copy_controller", return_value={"status": "queued"}) as run:
            response = self.client.post("/api/automation/copy-controller/run", json={"controller_name": "new"})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(run.call_args.kwargs["auth"], ("engineer", "legacy-dev-token"))
        self.assert_no_http()

    def test_jenkins_actions_still_require_dashboard_authentication(self):
        self.assertEqual(self.client.get("/api/maintenance/sonarqube-params").status_code, 401)
        self.assertEqual(self.client.post("/api/maintenance/sonarqube-dev", json={"params": {}}).status_code, 401)
        self.assertEqual(self.client.post("/api/automation/copy-controller/run", json={"controller_name": "new"}).status_code, 401)
        self.assert_no_http()


if __name__ == "__main__":
    unittest.main()
