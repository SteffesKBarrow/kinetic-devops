"""Regression tests for scripts/forgejo_fullstack_smoke.py."""

import importlib.util
import io
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch


class TestForgejoFullstackSmoke(unittest.TestCase):
    """Verify argument handling and dry-run behavior for Forgejo smoke script."""

    @classmethod
    def setUpClass(cls):
        repo_root = Path(__file__).resolve().parents[1]
        script_path = repo_root / "scripts" / "forgejo_fullstack_smoke.py"

        spec = importlib.util.spec_from_file_location("forgejo_fullstack_smoke", script_path)
        if spec is None or spec.loader is None:
            raise RuntimeError("Unable to load forgejo_fullstack_smoke.py")

        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        cls.mod = module

    def test_normalize_api_base_appends_api_path(self):
        self.assertEqual(
            self.mod.normalize_api_base("https://forgejo.local"),
            "https://forgejo.local/api/v1",
        )
        self.assertEqual(
            self.mod.normalize_api_base("https://forgejo.local/api/v1"),
            "https://forgejo.local/api/v1",
        )

    def test_build_branch_protection_payload(self):
        payload = self.mod.build_branch_protection_payload("main", "Python Test Gate", 2)
        self.assertTrue(payload["enable_status_check"])
        self.assertEqual(payload["status_check_contexts"], ["Python Test Gate"])
        self.assertEqual(payload["required_approvals"], 2)

    def test_main_dry_run_passes_without_token(self):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with patch.dict("os.environ", {"FORGEJO_OWNER": "acme"}, clear=False):
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = self.mod.main([
                    "--forgejo-url",
                    "https://forgejo.local",
                ])

        self.assertEqual(code, 0)
        self.assertIn("Mode: dry-run", stdout.getvalue())
        self.assertIn("SMOKE RESULT: PASS", stdout.getvalue())

    def test_main_apply_requires_token(self):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with patch.dict("os.environ", {"FORGEJO_OWNER": "acme"}, clear=True):
            with patch("keyring.get_password", return_value=None):
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    code = self.mod.main([
                        "--forgejo-url",
                        "https://forgejo.local",
                        "--apply",
                    ])

        self.assertEqual(code, 1)
        self.assertIn("SMOKE RESULT: FAIL", stderr.getvalue())

    def test_main_apply_uses_keyring_token(self):
        with patch.dict("os.environ", {"FORGEJO_OWNER": "acme"}, clear=True):
            with patch("keyring.get_password", return_value="kr_token"):
                with patch.object(self.mod, "run_smoke") as run_smoke:
                    code = self.mod.main([
                        "--forgejo-url",
                        "https://forgejo.local",
                        "--apply",
                    ])

        self.assertEqual(code, 0)
        run_smoke.assert_called_once()


if __name__ == "__main__":
    unittest.main()
