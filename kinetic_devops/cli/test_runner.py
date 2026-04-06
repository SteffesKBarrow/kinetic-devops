"""
kinetic_devops/cli/test_runner.py - Test runner entry point for the Kinetic SDK.

Invokable as:
    uv run kinetic-test
    python -m kinetic_devops.cli.test_runner
    python kinetic_devops/cli/test_runner.py
"""
import sys
import os
import unittest
import logging
from pathlib import Path

# Resolve repository root: cli/ -> kinetic_devops/ -> repo root
_repo_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_repo_root))
os.chdir(str(_repo_root))

_log_file = _repo_root / "tests" / "test_results.log"
_log_file.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(_log_file, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)


def run_tests() -> int:
    """Discover and run all tests under tests/. Returns 0 on success, 1 on failure."""
    tests_dir = _repo_root / "tests"

    logger.info("=" * 70)
    logger.info("KINETIC SDK TEST SUITE")
    logger.info("=" * 70)

    loader = unittest.TestLoader()
    suite = loader.discover(str(tests_dir), pattern="test_*.py")

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    logger.info("=" * 70)
    logger.info(f"Tests run: {result.testsRun}")
    logger.info(f"Failures:  {len(result.failures)}")
    logger.info(f"Errors:    {len(result.errors)}")
    logger.info(f"Skipped:   {len(result.skipped)}")

    if result.wasSuccessful():
        logger.info("[PASS] ALL TESTS PASSED")
    else:
        logger.error("[FAIL] SOME TESTS FAILED")
    logger.info("=" * 70)

    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(run_tests())
