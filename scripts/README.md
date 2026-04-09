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

## Branch Protection Automation (GitHub + Forgejo)

Use the config-driven automation script to apply branch protection across multiple hosts.

Config template:

```powershell
Copy-Item scripts\branch_protection.targets.example.json scripts\branch_protection.targets.json
```

Set your tokens in the current shell:

```powershell
$env:GITHUB_TOKEN = "<github-token>"
$env:FORGEJO_TOKEN = "<forgejo-token>"
```

Dry-run preview (default):

```powershell
python scripts/apply_branch_protection.py --config scripts/branch_protection.targets.json
```

Apply changes:

```powershell
python scripts/apply_branch_protection.py --config scripts/branch_protection.targets.json --apply
```

The script supports:
- GitHub branch protection via `https://api.github.com`
- Forgejo branch protection via a configured `forgejo_api_base` (for example `https://forgejo.example.com/api/v1`)
- Multiple repositories/hosts in one run

Auto-detection behavior:
- If `owner`/`repo` are omitted for a target, the script uses `git remote.origin.url` from the current repo.
- If `provider` is omitted, the script infers it from remote host (`github.com` -> `github`; otherwise `forgejo`).
- For inferred Forgejo targets, `forgejo_api_base` defaults to `<remote-host>/api/v1`.

CI workflow mirrors:
- GitHub Actions: `.github/workflows/ci-tests.yml`
- Forgejo Actions: `.forgejo/workflows/ci-tests.yml`

Use branch protection rules on both platforms to require only these blocking checks before merge:
- `Python Test Gate (required, py3.10)`
- `Python Test Gate (required, py3.12)`

Keep advisory checks non-required so merges can proceed while still flagging version compatibility issues.

### Full-Stack Forgejo Smoke (API)

You can validate the full lifecycle against a fresh Forgejo repository using API calls only.

Dry-run preview:

```powershell
$env:FORGEJO_URL = "https://forgejo.local"
$env:FORGEJO_OWNER = "my-org"
python scripts/forgejo_fullstack_smoke.py
```

Apply mode (creates repo, applies branch protection, verifies it, then deletes repo by default):

```powershell
$env:FORGEJO_TOKEN = "<forgejo-token>"
python scripts/forgejo_fullstack_smoke.py --apply
```

Keep the temporary repository for manual inspection:

```powershell
python scripts/forgejo_fullstack_smoke.py --apply --keep-repo
```

Common options:
- `--forgejo-url` (or `FORGEJO_URL`) - Forgejo base URL
- `--owner` (or `FORGEJO_OWNER`) - owner/org for repository creation
- `--owner-type org|user` - creation endpoint type
- `--repo` - explicit repository name (otherwise generated)
- `--required-check` - required status check context (default: `Python Test Gate`)

### Full-Stack GitHub Smoke (API)

You can validate the same lifecycle against a fresh GitHub repository using API calls only.

Dry-run preview:

```powershell
$env:GITHUB_OWNER = "my-org"
python scripts/github_fullstack_smoke.py
```

Apply mode (creates repo, applies branch protection, verifies it, then deletes repo by default):

```powershell
$env:GITHUB_TOKEN = "<github-token>"
python scripts/github_fullstack_smoke.py --apply
```

Keep the temporary repository for manual inspection:

```powershell
python scripts/github_fullstack_smoke.py --apply --keep-repo
```

Common options:
- `--owner` (or `GITHUB_OWNER`) - owner/org for repository creation
- `--owner-type org|user` - creation endpoint type
- `--repo` - explicit repository name (otherwise generated)
- `--required-check` - required status check context (default: `Python Test Gate`)

---

## Helper Scripts

Once environment is initialized, helper scripts can be invoked:

```powershell
# Validate environment (check Python version, imports, requests module)
python scripts/validate.py

# Pull tax configs for all companies and save to Data/tax_configs/
python scripts/pull_tax_configs.py [--env ENV] [--out-dir PATH] [--dry-run]

# Pull all discovered Kinetic Swagger/OData/method specs into projects/Kinetic-API-Store/
python scripts/pull_api_store.py [--env ENV] [--user USER] [--company COMPANY] [--out-dir PATH] [--format json|yaml|both] [--surface odata|methods|both]
python scripts/pull_api_store.py --surface methods --service <SERVICE>

# Run core layer import/delete operations from BO-call dump JSON exports
python -m kinetic_devops meta --env <ENV> --user <USER> layers "C:/Users/<you>/Downloads/dump (5).json" "C:/Users/<you>/Downloads/dump (6).json"
python -m kinetic_devops meta --env <ENV> --user <USER> layers dump5.json dump6.json --ops import
python -m kinetic_devops meta --env <ENV> --user <USER> layers dump5.json dump6.json --dry-run
```

### pull_tax_configs.py options:

- `--env ENV` — Only pull for a specific environment nickname (optional)
- `--out-dir PATH` — Output directory (default: `Data/tax_configs/`)
- `--dry-run` — Show summary without writing files

### pull_api_store.py options:

- `--env ENV` — Target environment nickname (optional)
- `--user USER` — Optional user session override
- `--company COMPANY` — Optional company context override for authentication
- `--out-dir PATH` — Output root directory (default: `projects/Kinetic-API-Store`)
- `--format json|yaml|both` — Which spec formats to download (default: `json`)
- `--surface odata|methods|both` — Pull only OData specs, only method specs, or both (default: `both`)
- `--service-type BO|Proc|Lib|Rpt|UD` — Filter to a service category
- `--service NAME` — Pull only an exact service name; may be repeated
- `--env-subdir` — Store files under an environment subdirectory instead of directly under the output root
- `--missing-only` — Skip files that already exist instead of checking for updates
- `--overwrite` — Re-download files even when they already exist
- `--connection-version VERSION` — Explicit connection version (for example `2025.2.14`) used to compute major version (`2025.2`)
- `--force-scan` — Bypass major-version gate and pull anyway
- `--timeout SECONDS` — HTTP timeout per request (default: `60`)
- `--show-discovery` — Print discovery endpoint statuses while scanning

`pull_api_store.py` discovers specs from both:
- old Rest Help pattern: `https://<host>/<instance>/api/help/v2/index.html`
- new Rest Help service listings: `https://<host>/<instance>/api/helppage/services?serviceType=BO|Proc|Lib|Rpt|UD`
- swagger endpoints: `https://<host>/<instance>/api/swagger/v2/odata/...` and `https://<host>/<instance>/api/swagger/v2/methods/...`

It stores files under surface folders to avoid collisions:
- `projects/Kinetic-API-Store/odata/`
- `projects/Kinetic-API-Store/methods/`

It writes:
- `manifest.json` with discovery status, pull filters, a best-effort Kinetic server version probe, and **redacted** request headers
- `_pulls/pull_<timestamp>.json` as a point-in-time pull record for version control history
- `connection-history.yaml` as a git-friendly text history keyed by connection version and major version

Privacy behavior for metadata files:
- raw URLs are not persisted in `manifest.json` or `connection-history.yaml`
- raw service IDs and tenant IDs are not persisted in metadata summaries
- connection identity is stored as a fingerprint, not as plain URL/env/user/company

The default pull mode is git-friendly sync:
- git is the history of record for spec changes
- existing files are fetched and only rewritten when content changes
- unchanged files are reported without creating noisy file updates
- if the major version (for example `2025.2`) is already recorded in `connection-history.yaml` for the environment, the pull is skipped by default
- use `--missing-only` when you want resume-only behavior and do not want to check existing files
- use `--force-scan` to run a pull even when the major-version gate would skip it
- if you cancel a run, the script writes a partial manifest instead of losing progress
- use `--overwrite` only when you want to force rewrite files already present

### `meta layers` options:

- `--ops import|delete|both` — Filter which layer operation types are executed (default: `import`)
- `--env ENV` — Target environment nickname
- `--user USER_ID` — Optional user session override
- `--company COMPANY` — Optional company override
- `--tenant-company T_ID` — Target tenant company ID used in company-scoped layer operations while keeping working company context
- `--plant PLANT` — Optional plant value used in `callSettings`
- `--dry-run` — Parse and resolve calls without sending HTTP requests
- `--report PATH` — Output JSON report path (default: `temp/layer_ops_report_<timestamp>.json`)

`json_helper.py build --deploy` operation control:
- default: delete then import (full deploy)
- `--delete-only` — perform delete only (useful for tenant-company cleanup)
- `--import-only` — perform import only
- `--skip-delete` — legacy alias behavior for import without delete

Example (delete-only against tenant company):
`python scripts/json_helper.py build <layer.jsonc> --deploy --delete-only --tenant-company <TENANT_ID> --env <ENV> --user <USER>`

Sensitive-value handling (preferred):
- use keyring-backed environment selection whenever possible
- use environment variables instead of CLI literals for sensitive runtime context:
	`KIN_ENV_NAME`, `KIN_USER` (or `KIN_USER_ID`), `KIN_COMPANY`, `KIN_TENANT_COMPANY`

The `meta layers` command extracts `ImportLayers` and `BulkDeleteLayers` calls from provided dump files,
executes them against the active environment, and captures status, correlation IDs, and
response bodies/errors in the report.

Default `--ops import` behavior is deployment mode: delete first, then import.

---

## Notes

- `PYTHONPATH` is set during environment initialization, enabling imports from the repository root.
- Temporary env files (`env_vars_tmp.bat`, `env_vars_tmp.ps1`) are securely wiped after use.
- The `pull_tax_configs.py` script uses stored Kinetic configuration from the keyring to authenticate.
