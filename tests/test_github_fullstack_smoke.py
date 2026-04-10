"""Regression tests for scripts/github_fullstack_smoke.py."""

import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from tests.script_test_loader import load_script_module


class TestGitHubFullstackSmoke(unittest.TestCase):
    """Verify argument handling and dry-run behavior for GitHub smoke script."""

    @classmethod
    def setUpClass(cls):
        cls.mod = load_script_module("github_fullstack_smoke.py", "github_fullstack_smoke")

    def test_build_branch_protection_payload(self):
        payload = self.mod.build_branch_protection_payload("Python Test Gate", 2)
        self.assertTrue(payload["required_status_checks"]["strict"])
        self.assertEqual(payload["required_status_checks"]["contexts"], ["Python Test Gate"])
        self.assertEqual(payload["required_pull_request_reviews"]["required_approving_review_count"], 2)

    def test_main_dry_run_passes_without_token(self):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with patch.dict("os.environ", {"GITHUB_OWNER": "acme"}, clear=False):
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = self.mod.main([])

        self.assertEqual(code, 0)
        self.assertIn("Mode: dry-run", stdout.getvalue())
        self.assertIn("SMOKE RESULT: PASS", stdout.getvalue())

    def test_main_apply_requires_token(self):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with patch.dict("os.environ", {"GITHUB_OWNER": "acme"}, clear=True):
            with patch("keyring.get_password", return_value=None):
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    code = self.mod.main(["--apply"])

        self.assertEqual(code, 1)
        self.assertIn("SMOKE RESULT: FAIL", stderr.getvalue())

    def test_main_apply_uses_keyring_token(self):
        with patch.dict("os.environ", {"GITHUB_OWNER": "acme"}, clear=True):
            with patch("keyring.get_password", return_value="kr_token"):
                with patch.object(self.mod, "run_smoke") as run_smoke:
                    code = self.mod.main(["--apply"])

        self.assertEqual(code, 0)
        run_smoke.assert_called_once()

    def test_main_dry_run_infers_owner_from_github_remote(self):
        with patch.dict("os.environ", {}, clear=True):
            with patch.object(
                self.mod.repo_context,
                "detect_from_git",
                return_value={
                    "provider": "github",
                    "host": "github.com",
                    "owner": "acme",
                    "repo": "project",
                    "scheme": "https",
                },
            ):
                with patch.object(self.mod, "run_smoke") as run_smoke:
                    code = self.mod.main([])

        self.assertEqual(code, 0)
        cfg = run_smoke.call_args.args[0]
        self.assertEqual(cfg.owner, "acme")

    def test_main_without_explicit_owner_fails_on_non_github_remote(self):
        stderr = io.StringIO()
        with patch.dict("os.environ", {}, clear=True):
            with patch.object(
                self.mod.repo_context,
                "detect_from_git",
                return_value={
                    "provider": "forgejo",
                    "host": "forgejo.local",
                    "owner": "acme",
                    "repo": "project",
                    "scheme": "https",
                },
            ):
                with redirect_stderr(stderr):
                    code = self.mod.main([])

        self.assertEqual(code, 1)
        self.assertIn("does not appear to be GitHub", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
