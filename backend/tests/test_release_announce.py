"""Regression coverage for not telling the team channel the same thing twice.

Run from backend/: python -m unittest discover -s tests -v

3.17.0 reached #cms-cloud-devops-internal twice, four minutes apart: the pod
announced it on the first start after the deploy, and a manual post followed
because whoever asked believed it was still waiting. Neither call could see
what the other had done, so the guard below is on the state file rather than on
anyone remembering which of the two had already run.
"""
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from app.config import get_settings
from app.services import release_announce


class AnnounceGuardTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.state = os.path.join(self.dir, "release_announced.json")
        os.environ["RELEASE_ANNOUNCE_STATE_FILE"] = self.state
        get_settings.cache_clear()
        self.sent: list[str] = []
        patcher = patch.multiple(
            release_announce.slack,
            send_message=lambda channel, text, blocks=None: (self.sent.append(text), True)[1],
            webhook_url_for=lambda channel: "https://hooks.example/stub",
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        os.environ.pop("RELEASE_ANNOUNCE_STATE_FILE", None)
        get_settings.cache_clear()

    def test_startup_announces_once_and_a_restart_stays_quiet(self):
        self.assertTrue(release_announce.announce()["posted"])
        self.assertFalse(release_announce.announce()["posted"])
        self.assertEqual(len(self.sent), 1)

    def test_a_manual_post_after_the_startup_one_is_refused(self):
        release_announce.announce()
        result = release_announce.announce(force=True, by="RWRW")
        self.assertFalse(result["posted"])
        self.assertTrue(result["duplicate_blocked"])
        self.assertEqual(len(self.sent), 1, "the channel was told twice")

    def test_a_second_copy_still_possible_when_actually_wanted(self):
        release_announce.announce()
        result = release_announce.announce(force=True, by="RWRW", allow_duplicate=True)
        self.assertTrue(result["posted"])
        self.assertEqual(len(self.sent), 2)

    def test_a_held_release_does_not_announce_itself_on_deploy(self):
        release_announce.hold(by="RWRW")
        result = release_announce.announce()
        self.assertFalse(result["posted"])
        self.assertEqual(result["reason"], "held, not announced")
        self.assertEqual(self.sent, [])

    def test_a_held_release_posts_when_asked_without_needing_a_duplicate_flag(self):
        # "Held" means not yet, not never: asking for it is the normal path and
        # must not be mistaken for a second copy.
        release_announce.hold(by="RWRW")
        self.assertTrue(release_announce.announce(force=True, by="RWRW")["posted"])
        self.assertEqual(len(self.sent), 1)

    def test_hold_is_recorded_as_held_rather_than_as_a_post(self):
        release_announce.hold(by="RWRW")
        with open(self.state) as f:
            saved = json.load(f)
        self.assertTrue(saved["held"])

    def test_a_rejected_send_leaves_the_release_unannounced(self):
        with patch.object(release_announce.slack, "send_message", return_value=False):
            self.assertFalse(release_announce.announce()["posted"])
        # Nothing recorded, so the next start tries again instead of going quiet.
        self.assertTrue(release_announce.announce()["posted"])
        self.assertEqual(len(self.sent), 1)

    def test_the_kill_switch_stops_everything(self):
        with patch.object(get_settings(), "RELEASE_ANNOUNCE_ENABLED", False):
            self.assertFalse(release_announce.announce()["posted"])
            self.assertFalse(release_announce.announce(force=True, allow_duplicate=True)["posted"])
        self.assertEqual(self.sent, [])


if __name__ == "__main__":
    unittest.main()
