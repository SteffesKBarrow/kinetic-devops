"""Regression tests for scripts/repo_fullstack_smoke.py."""

import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from tests.script_test_loader import load_script_module


class TestRepoFullstackSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_script_module("repo_fullstack_smoke.py", "repo_fullstack_smoke")

    def test_auto_provider_dispatches_to_github(self):
        with patch.object(self.mod, "_detect_provider", return_value="github"):
            with patch.object(self.mod.github_fullstack_smoke, "main", return_value=0) as gh_main:
                code = self.mod.main(["--provider", "auto"])

        self.assertEqual(code, 0)
        gh_main.assert_called_once()

    def test_auto_provider_dispatches_to_forgejo(self):
        with patch.object(self.mod, "_detect_provider", return_value="forgejo"):
            with patch.object(self.mod.forgejo_fullstack_smoke, "main", return_value=0) as fj_main:
                code = self.mod.main(["--provider", "auto"])

        self.assertEqual(code, 0)
        fj_main.assert_called_once()

    def test_forgejo_url_is_forwarded(self):
        with patch.object(self.mod.forgejo_fullstack_smoke, "main", return_value=0) as fj_main:
            code = self.mod.main([
                "--provider",
                "forgejo",
                "--forgejo-url",
                "https://forgejo.local",
            ])

        self.assertEqual(code, 0)
        argv = fj_main.call_args.args[0]
        self.assertIn("--forgejo-url", argv)
        self.assertIn("https://forgejo.local", argv)

    def test_bad_provider_returns_nonzero(self):
        stdout = io.StringIO()
        with patch.object(self.mod, "_detect_provider", side_effect=self.mod.RepoSmokeError("boom")):
            with redirect_stdout(stdout):
                code = self.mod.main(["--provider", "auto"])

        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
