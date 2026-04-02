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
# or
python -m kinetic_devops.cli.test_runner
```

Run specific test module:
```bash
python -m unittest tests.test_imports
python -m unittest tests.test_cli
python -m unittest tests.test_redaction
python -m unittest tests.test_base_client_redaction
```

Run with verbose output:
```bash
python -m unittest discover -s tests -p "test_*.py" -v
```

## Environment Validation

Quick validation of SDK environment:
```bash
python scripts/validate.py
```

## Test Runner

The canonical test runner is `tests/test_runner.py`, which:
- Validates the environment (Python version, required directories/files, SDK imports).
- Discovers and runs all tests under `tests/test_*.py`.
- Logs results to `tests/test_results.log`.
- Returns exit code 0 on success, non-zero on failure (useful for CI/CD).

The CLI module `python -m kinetic_devops.cli.test_runner` runs the same test discovery and result reporting flow.

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

### test_redaction.py
- Heuristic redaction behavior for sensitive keys
- Escaped nested JSON redaction paths
- Whitespace and formatting variation handling

### test_base_client_redaction.py
- `KineticCore.log_wire()` zero-trust output redaction
- `KineticBaseClient.execute_request()` success and failure wire-log behavior
- Runtime identity and URL sanitization in error paths

### sdk_kinetic/test_basic.py
- Basic package smoke test for importability

## Pre-commit Hook

To enable pre-commit testing:

**Windows (PowerShell):**
```powershell
./scripts/install-hook.ps1
```

**Linux/macOS:**
```bash
chmod +x scripts/hooks/pre-commit
git config core.hooksPath scripts/hooks
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
| test_base_client_redaction | 3 | All Pass |
| test_imports | 8 | All Pass |
| test_cli | 3 | All Pass |
| test_redaction | 7 | All Pass |
| sdk_kinetic/test_basic | 1 | All Pass |
| **Total** | **22** | **All Pass** |

## CI Integration

Test results are logged to `tests/test_results.log` and can be parsed by CI systems.

Example GitHub Actions integration:
```yaml
- name: Run Kinetic SDK Tests
  run: python tests/test_runner.py
```
