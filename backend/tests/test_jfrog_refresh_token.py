"""Coverage for minting a JFrog entitlement token from the stored refresh token.

Run from backend/: python -m unittest discover -s tests -v

No network and no real credentials: the pure helpers are exercised directly and
the refresh call is stubbed, because a real refresh spends the stored refresh
token and JFrog issues a replacement, which would break the next rotation.
"""
import base64
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from app.config import get_settings

from app.services import jfrog_registry_token as jrt


def _fake_jwt(subject: str) -> str:
    payload = base64.urlsafe_b64encode(
        json.dumps({"sub": subject}).encode()
    ).decode().rstrip("=")
    return f"header.{payload}.signature"


class OpaqueCredentialTests(unittest.TestCase):
    def test_reads_the_pair_from_the_opaque_document(self):
        manifest = jrt.build_manifest("dev", "1790364505532__someone@example.com", "token-value")
        user, password = jrt._opaque_credential(manifest)
        self.assertEqual(user, "1790364505532__someone@example.com")
        self.assertEqual(password, "token-value")

    def test_a_manifest_without_a_pair_is_an_error_not_a_silent_empty(self):
        with self.assertRaises(RuntimeError):
            jrt._opaque_credential("apiVersion: v1\nkind: Secret\nmetadata:\n  name: x\n")


class TokenSubjectTests(unittest.TestCase):
    def test_subject_comes_from_the_new_token(self):
        # A refreshed token can carry a different subject, and the registry wants
        # the token's own subject as the username.
        token = _fake_jwt("1790364505532__max@samtek.io")
        self.assertEqual(
            jrt._token_subject(token, "old@example.com"), "1790364505532__max@samtek.io"
        )

    def test_an_opaque_token_keeps_the_previous_username(self):
        self.assertEqual(jrt._token_subject("not-a-jwt", "old@example.com"), "old@example.com")

    def test_a_jwt_without_a_subject_keeps_the_previous_username(self):
        payload = base64.urlsafe_b64encode(json.dumps({"scope": "x"}).encode()).decode().rstrip("=")
        self.assertEqual(
            jrt._token_subject(f"h.{payload}.s", "old@example.com"), "old@example.com"
        )


class ExpiryReminderTests(unittest.TestCase):
    """The bell reminder that tells an engineer to click refresh."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        os.environ["JFROG_TOKEN_STATE_FILE"] = os.path.join(self.dir, "expiry.json")
        os.environ["JFROG_TOKEN_EXPIRES_AT"] = "2026-11-17"
        get_settings.cache_clear()

    def tearDown(self):
        os.environ.pop("JFROG_TOKEN_STATE_FILE", None)
        os.environ.pop("JFROG_TOKEN_EXPIRES_AT", None)
        get_settings.cache_clear()

    def _status_for(self, days_out: int) -> str:
        jrt.record_expiry(
            datetime.now(timezone.utc) + timedelta(days=days_out), source="test"
        )
        return jrt.expiry_status()["status"]

    def test_quiet_for_most_of_the_token_life(self):
        # A month-long token warned about three weeks early would sit in the
        # bell until it stopped being read as a reminder.
        self.assertEqual(self._status_for(30), "ok")
        self.assertEqual(self._status_for(15), "ok")

    def test_warns_two_weeks_out_and_escalates_near_the_end(self):
        self.assertEqual(self._status_for(14), "warning")
        self.assertEqual(self._status_for(6), "warning")
        self.assertEqual(self._status_for(5), "critical")
        self.assertEqual(self._status_for(1), "critical")

    def test_reports_expired_once_past(self):
        self.assertEqual(self._status_for(-1), "expired")

    def test_falls_back_to_the_configured_date_before_any_refresh(self):
        # The token issued by hand has no recorded expiry, and the reminder
        # still has to work for it.
        out = jrt.expiry_status()
        self.assertEqual(out["expires_at"], "2026-11-17")
        self.assertEqual(out["source"], "configured")

    def test_a_recorded_expiry_wins_over_the_configured_one(self):
        jrt.record_expiry(datetime.now(timezone.utc) + timedelta(days=9), source="refresh")
        out = jrt.expiry_status()
        self.assertEqual(out["source"], "refresh")
        self.assertEqual(out["days_remaining"], 9)

    def test_an_unparseable_date_is_unknown_rather_than_a_crash(self):
        os.environ["JFROG_TOKEN_EXPIRES_AT"] = "not-a-date"
        get_settings.cache_clear()
        self.assertEqual(jrt.expiry_status()["status"], "unknown")


class ApplyCommandTests(unittest.TestCase):
    def test_dev_and_prod_name_their_own_credentials_and_paths(self):
        dev = {c["step"]: c["command"] for c in jrt.apply_commands("dev")}
        prod = {c["step"]: c["command"] for c in jrt.apply_commands("prod")}
        apply_step = "Decrypt and apply the pull secrets"
        creds_step = "Load the credentials for that account"

        self.assertIn("envs/jfrog/dev/secret", dev[apply_step])
        self.assertIn("envs/jfrog/prod/secret", prod[apply_step])
        self.assertIn(".aws-dev-jfrog", dev[creds_step])
        self.assertIn(".aws-prod-jfrog", prod[creds_step])

    def test_the_apply_step_pipes_sops_into_kubectl(self):
        cmd = {c["step"]: c["command"] for c in jrt.apply_commands("dev")}[
            "Decrypt and apply the pull secrets"
        ]
        self.assertTrue(cmd.startswith("sops -d "), cmd)
        self.assertIn("| kubectl apply -f -", cmd)

    def test_every_step_has_a_command(self):
        for env in ("dev", "prod"):
            for c in jrt.apply_commands(env):
                self.assertTrue(c["step"] and c["command"], f"{env}: {c}")


if __name__ == "__main__":
    unittest.main()
