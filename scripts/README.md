# Scripts & Developer Tooling

## Environment Setup (PYTHONPATH & Kinetic Config)

Before running helper scripts, initialize the environment to set `PYTHONPATH` and Kinetic configuration variables.

### Windows (Command Prompt / batch):

```batch
scripts\env_init.bat [env-name]
```

This activates a Python venv (if present) and sets:
- `KIN_URL`, `KIN_COMPANY`, `KIN_ENV_NAME`, `KIN_API_KEY` (Kinetic connection vars)
- `PYTHONPATH` (points to repo root so scripts can import `kinetic_devops`)

The script generates and executes `env_vars_tmp.bat`, then securely erases it.

### Windows (PowerShell):

```powershell
. .\scripts\env_init.ps1 [env-name]
```

Same behavior as `.bat`, but for PowerShell. Dot-source the script to inherit environment variables in your session.

### Unix-like (bash/sh):

```bash
. ./scripts/env_init.sh [env-name]
```

Activates a Python venv and sets environment variables.

---

## Running Tests

After environment setup, run the canonical test runner:

```powershell
python -m tests.test_runner
# or
python tests/test_runner.py
```

- The test runner validates the environment, discovers tests under `tests/`, and writes results to `tests/test_results.log`.
- CI invokes the test runner via `python -m tests.test_runner`.

---

## Pre-commit Hooks

Install the repo-tracked pre-commit hook locally (PowerShell):

```powershell
Copy-Item scripts\hooks\pre-commit .git\hooks\pre-commit
# or configure Git to use the repo hooks directory
git config core.hooksPath scripts/hooks
```

The hook runs `python -m tests.test_runner` before each commit.

---

## Helper Scripts

Once environment is initialized, helper scripts can be invoked:

```powershell
# Validate environment (check Python version, imports, requests module)
python scripts/validate.py

# Pull tax configs for all companies and save to Data/tax_configs/
python scripts/pull_tax_configs.py [--env ENV] [--out-dir PATH] [--dry-run]
```

### pull_tax_configs.py options:

- `--env ENV` — Only pull for a specific environment nickname (optional)
- `--out-dir PATH` — Output directory (default: `Data/tax_configs/`)
- `--dry-run` — Show summary without writing files

---

## Notes

- `PYTHONPATH` is set during environment initialization, enabling imports from the repository root.
- Temporary env files (`env_vars_tmp.bat`, `env_vars_tmp.ps1`) are securely wiped after use.
- The `pull_tax_configs.py` script uses stored Kinetic configuration from the keyring to authenticate.
