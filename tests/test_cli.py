"""
tests/test_cli.py - Test CLI help and argument parsing for all services.
"""
import subprocess
import sys
import unittest


class TestServiceCLI(unittest.TestCase):
    """Verify all services have working CLI interfaces."""
    
    def _test_cli_help(self, module_name):
        """Helper to test CLI --help for a module."""
        result = subprocess.run(
            [sys.executable, "-m", module_name, "--help"],
            capture_output=True,
            text=True,
            timeout=5
        )
        self.assertEqual(result.returncode, 0, f"{module_name} --help failed")
        self.assertIn("usage:", result.stdout, f"{module_name} help missing usage")
    
    def test_baq_cli_help(self):
        """Test kinetic_devops.baq --help."""
        result = subprocess.run(
            [sys.executable, "-m", "kinetic_devops.baq", "--help"],
            capture_output=True,
            text=True,
            timeout=5
        )
        self.assertEqual(result.returncode, 0, "kinetic_devops.baq --help failed")
        self.assertIn("usage:", result.stdout, "kinetic_devops.baq help missing usage")
        self.assertNotIn("RuntimeWarning", result.stderr)
    
    def test_boreader_cli_help(self):
        """Test kinetic_devops.boreader --help."""
        self._test_cli_help("kinetic_devops.boreader")
    
    def test_file_service_cli_help(self):
        """Test kinetic_devops.file_service --help."""
        self._test_cli_help("kinetic_devops.file_service")

    def test_export_all_cli_help(self):
        """Test kinetic_devops.export_all --help."""
        self._test_cli_help("kinetic_devops.export_all")

    def test_solutions_cli_help(self):
        """Test kinetic_devops.solutions --help."""
        self._test_cli_help("kinetic_devops.solutions")


if __name__ == '__main__':
    unittest.main()
