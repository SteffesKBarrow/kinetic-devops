"""Unit tests for kinetic_devops.repo_context smoke helpers."""

import unittest
from unittest.mock import patch

from kinetic_devops import repo_context


class TestRepoContextSmoke(unittest.TestCase):
    def test_detect_provider_from_git_returns_provider(self):
        with patch(
            "kinetic_devops.repo_context.detect_from_git",
            return_value={
                "provider": "forgejo",
                "host": "forgejo.local",
                "owner": "acme",
                "repo": "project",
                "scheme": "https",
            },
        ):
            self.assertEqual(repo_context.detect_provider_from_git(), "forgejo")

    def test_detect_provider_from_git_uses_passed_error_type(self):
        class CustomError(RuntimeError):
            pass

        with patch(
            "kinetic_devops.repo_context.detect_from_git",
            side_effect=CustomError("git detect failed"),
        ):
            with self.assertRaises(CustomError):
                repo_context.detect_provider_from_git(error_type=CustomError)


if __name__ == "__main__":
    unittest.main()
