"""Regression tests for sensitive data scanner exclusion behavior."""

import os
import re
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from kinetic_devops.find_sensitive_data import get_files_to_scan, scan_git_history


class _FakePopen:
    def __init__(self, lines):
        self.stdout = iter(lines)
        self.returncode = 0

    def wait(self):
        return 0


class TestSensitiveDataScanExclusions(unittest.TestCase):
    def setUp(self) -> None:
        self.td = tempfile.mkdtemp(prefix="scan_excl_test_")

    def tearDown(self) -> None:
        shutil.rmtree(self.td, ignore_errors=True)

    def test_get_files_to_scan_normalizes_dot_slash_exclude_paths(self):
        os.makedirs(os.path.join(self.td, "exports"), exist_ok=True)
        os.makedirs(os.path.join(self.td, "src"), exist_ok=True)

        excluded_file = os.path.join(self.td, "exports", "artifact.json")
        kept_file = os.path.join(self.td, "src", "ok.py")
        with open(excluded_file, "w", encoding="utf-8") as f:
            f.write("SECRET")
        with open(kept_file, "w", encoding="utf-8") as f:
            f.write("print('ok')")

        files = get_files_to_scan(
            self.td,
            use_gitignore=False,
            exclude_dirs={".\\exports"},
        )

        rel_files = {os.path.relpath(p, self.td).replace("\\", "/") for p in files}
        self.assertIn("src/ok.py", rel_files)
        self.assertNotIn("exports/artifact.json", rel_files)

    def test_get_files_to_scan_honors_explicit_ignored_subpath(self):
        subprocess.run(["git", "init"], cwd=self.td, check=True, capture_output=True)
        with open(os.path.join(self.td, ".gitignore"), "w", encoding="utf-8") as f:
            f.write("exports/\n")

        os.makedirs(os.path.join(self.td, "exports"), exist_ok=True)
        explicit_file = os.path.join(self.td, "exports", "artifact.json")
        with open(explicit_file, "w", encoding="utf-8") as f:
            f.write("explicit-target")

        files = get_files_to_scan(
            os.path.join(self.td, "exports"),
            use_gitignore=True,
            exclude_dirs={"exports"},
        )

        rel_files = {os.path.relpath(p, self.td).replace("\\", "/") for p in files}
        self.assertIn("exports/artifact.json", rel_files)

    def test_scan_git_history_respects_excluded_paths(self):
        patterns = {"PRIVATE_KEY_BLOCK": re.compile(r"PRIVATE KEY")}
        fake_log = [
            "commit deadbeef\n",
            "diff --git a/exports/secret.txt b/exports/secret.txt\n",
            "+PRIVATE KEY SHOULD BE EXCLUDED\n",
            "diff --git a/src/app.py b/src/app.py\n",
            "+PRIVATE KEY SHOULD BE FOUND\n",
        ]

        with patch("kinetic_devops.find_sensitive_data.subprocess.Popen", return_value=_FakePopen(fake_log)):
            findings = scan_git_history(self.td, patterns, exclude_dirs={"exports", ".\\exports"})

        self.assertEqual(len(findings), 1)
        location, _, pattern_name, match = findings[0]
        self.assertIn("src/app.py", location)
        self.assertEqual(pattern_name, "PRIVATE_KEY_BLOCK")
        self.assertIn("FOUND", match)

    def test_scan_git_history_honors_explicit_include_path(self):
        patterns = {"PRIVATE_KEY_BLOCK": re.compile(r"PRIVATE KEY")}
        fake_log = [
            "commit deadbeef\n",
            "diff --git a/kinetic_devops/find_sensitive_data.py b/kinetic_devops/find_sensitive_data.py\n",
            "+PRIVATE KEY OUTSIDE SCOPE\n",
            "diff --git a/exports/inside.txt b/exports/inside.txt\n",
            "+PRIVATE KEY INSIDE SCOPE\n",
        ]

        with patch("kinetic_devops.find_sensitive_data.subprocess.Popen", return_value=_FakePopen(fake_log)):
            findings = scan_git_history(self.td, patterns, exclude_dirs=set(), include_path="./exports")

        self.assertEqual(len(findings), 1)
        location, _, pattern_name, match = findings[0]
        self.assertIn("exports/inside.txt", location)
        self.assertEqual(pattern_name, "PRIVATE_KEY_BLOCK")
        self.assertIn("INSIDE", match)


if __name__ == "__main__":
    unittest.main()
