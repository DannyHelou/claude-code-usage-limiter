import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock

import limiter


class LimiterTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.env = dict(os.environ, CODING_LIMITER_HOME=directory.name)
        self.configure("70")

    def run_cli(self, *args, data=None):
        return subprocess.run(
            [sys.executable, str(Path(__file__).with_name("limiter.py")), *args],
            env=self.env, input=data, text=True, capture_output=True, timeout=10,
        )

    def configure(self, percent):
        result = self.run_cli("configure", percent, "--windows", "five_hour")
        self.assertEqual(result.returncode, 0, result.stderr)

    def record(self, percent, reset=None):
        reset = reset if reset is not None else int(time.time()) + 3600
        result = self.run_cli("record", "five_hour", str(percent), str(reset))
        self.assertEqual(result.returncode, 0, result.stderr)

    def hook(self, event, **payload):
        return self.run_cli("hook", data=json.dumps({"hook_event_name": event, **payload}))

    def choose(self, prompt, session_id="first"):
        result = self.hook("UserPromptSubmit", prompt=prompt, session_id=session_id)
        response = json.loads(result.stdout)
        self.assertEqual(response["decision"], "block")
        return response["reason"]

    def test_new_store_is_enabled_at_ninety_percent(self):
        result = self.run_cli("--store", str(self.root / "new"), "state")
        state = json.loads(result.stdout)
        self.assertTrue(state["enabled"])
        self.assertEqual(state["cutoff"], 90)

    def test_disable_finishes_after_first_step_and_stops_enforcement(self):
        self.record(95)
        self.assertIn("Step 1", self.choose("/limiter"))
        self.assertIn("disabled", self.choose("/limiter Disable"))
        self.assertEqual(self.hook("UserPromptSubmit", prompt="What changed?", session_id="first").returncode, 0)
        self.assertEqual(self.run_cli("check").returncode, 0)

    def test_enable_requires_valid_percentage_in_same_session(self):
        self.choose("/limiter")
        self.choose("/limiter disable")
        self.choose("/limiter")
        self.assertIn("Step 2", self.choose("/limiter enable"))
        self.assertIn("Step 2", self.choose("/limiter 101"))
        self.assertIn("open the settings", self.choose("/limiter 83", session_id="other"))
        self.assertIn("83%", self.choose("/limiter 83%"))
        self.record(83)
        self.assertEqual(self.run_cli("check").returncode, 2)

    def test_missing_usage_blocks_prompt(self):
        self.assertEqual(self.hook("UserPromptSubmit").returncode, 2)

    def test_exact_threshold_and_change(self):
        self.record(70)
        self.assertEqual(self.hook("UserPromptSubmit").returncode, 2)
        self.configure("71")
        self.assertEqual(self.hook("UserPromptSubmit").returncode, 0)

    def test_usage_from_status_line_stops_agent_loop(self):
        self.record(20)
        payload = {"rate_limits": {"five_hour": {
            "used_percentage": 72,
            "resets_at": int(time.time()) + 3600,
        }}}
        self.assertEqual(self.run_cli("statusline", data=json.dumps(payload)).returncode, 0)
        result = self.hook("PreToolUse")
        self.assertFalse(json.loads(result.stdout)["continue"])
        self.assertEqual(json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_old_window_cannot_replace_current_window(self):
        now = int(time.time())
        self.record(80, now + 3600)
        self.record(10, now - 1)
        self.assertEqual(self.run_cli("check").returncode, 2)

    def test_expired_window_requires_fresh_reading(self):
        self.record(20, int(time.time()) - 1)
        self.assertEqual(self.run_cli("check").returncode, 2)

    def test_settings_have_enforcement_hooks(self):
        settings = json.loads((self.root / "claude-settings.json").read_text())
        self.assertIn("UserPromptSubmit", settings["hooks"])
        self.assertIn("statusLine", settings)

    def test_change_cutoff_without_regenerating_settings(self):
        self.record(65)
        settings = self.root / "claude-settings.json"
        timestamp = settings.stat().st_mtime_ns
        self.assertEqual(self.run_cli("set-cutoff", "65").returncode, 0)
        self.assertEqual(settings.stat().st_mtime_ns, timestamp)
        self.assertEqual(self.hook("UserPromptSubmit").returncode, 2)

    def test_running_cli_is_stopped_after_new_usage_crosses_cutoff(self):
        self.record(20)
        child = Mock(pid=123, returncode=1)

        def wait_for_update(timeout=None):
            if timeout is None:
                return 1
            self.record(71)
            raise subprocess.TimeoutExpired("claude", timeout)

        child.wait.side_effect = wait_for_update
        with limiter.open_database(self.root) as db:
            self.assertEqual(limiter.monitor(child, db), 2)
        child.terminate_tree.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
