"""
tests/README.md - Kinetic SDK Test Suite Documentation
"""

# Kinetic SDK Test Suite

## Quick Start

Run all tests with validation:
```bash
python -m tests.test_runner
# or
python tests/test_runner.py
```

Run specific test module:
```bash
python -m unittest tests.test_imports
python -m unittest tests.test_cli
```

Run with verbose output:
```bash
python -m unittest discover -s tests -p "test_*.py" -v
```

## Environment Validation

Quick validation of SDK environment:
```bash
python -m kinetic_devops.cli.validate
```

## Test Runner

The canonical test runner is `tests/test_runner.py`, which:
- Validates the environment (Python version, required directories/files, SDK imports).
- Discovers and runs all tests under `tests/test_*.py`.
- Logs results to `tests/test_results.log`.
- Returns exit code 0 on success, non-zero on failure (useful for CI/CD).

## Test Results

All test results are logged to `tests/test_results.log` for CI/CD integration.

## What's Tested

### test_imports.py
- Service class imports (KineticBAQService, KineticBOReaderService, etc.)
- Service method availability
- Base client and config manager availability

### test_cli.py
- CLI help output for each service module
- Argument parser functionality

## Pre-commit Hook

To enable pre-commit testing:

**Windows (PowerShell):**
```powershell
Copy-Item .git/hooks/pre-commit .git/hooks/pre-commit.py
# Then configure git to use PowerShell or Python to run hooks
```

**Linux/macOS:**
```bash
chmod +x .git/hooks/pre-commit
git config core.hooksPath .git/hooks
```

The pre-commit hook will automatically run the test suite before allowing commits.

## Environment Validation

The test runner includes automatic environment validation that checks:
- Python version (3.8+)
- Required directories (kinetic_devops, tests, scripts)
- Required files (all service modules)
- Module imports
- Required dependencies (requests)

## Test Coverage

| Module | Tests | Status |
|--------|-------|--------|
| test_imports | 12 | All Pass |
| test_cli | 4 | All Pass |
| **Total** | **14** | **All Pass** |

## CI Integration

Test results are logged to `tests/test_results.log` and can be parsed by CI systems.

Example GitHub Actions integration:
```yaml
- name: Run Kinetic SDK Tests
  run: python -m kinetic_devops.cli.test_runner
```
