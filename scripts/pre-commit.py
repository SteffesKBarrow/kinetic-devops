#!/usr/bin/env python
"""
.git/hooks/pre-commit (Windows PowerShell compatible)

Pre-commit hook for Kinetic SDK:
- Runs test suite before allowing commit
- Prevents commits if tests fail

To install:
    cp scripts/pre-commit.py .git/hooks/pre-commit
"""
import subprocess
import sys
from pathlib import Path


def run_pre_commit_checks():
    """Run all pre-commit checks."""
    print("=" * 70)
    print("PRE-COMMIT: Running Kinetic SDK test suite...")
    print("=" * 70)
    
    # Get repo root
    repo_root = Path(__file__).parent.parent.parent
    test_runner = repo_root / "tests" / "run_tests.py"
    
    if not test_runner.exists():
        print(f"❌ Test runner not found at {test_runner}")
        return 1
    
    # Run tests
    result = subprocess.run(
        [sys.executable, str(test_runner)],
        cwd=str(repo_root),
        capture_output=False
    )
    
    if result.returncode == 0:
        print("\n" + "=" * 70)
        print("✅ PRE-COMMIT: All tests passed. Commit allowed.")
        print("=" * 70)
        return 0
    else:
        print("\n" + "=" * 70)
        print("❌ PRE-COMMIT: Tests failed. Commit blocked.")
        print("=" * 70)
        return 1


if __name__ == '__main__':
    sys.exit(run_pre_commit_checks())
