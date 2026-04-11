# Kinetic DevOps

**Status: ⚠️ ALPHA** — Early development. API and features may change significantly.

**Kinetic DevOps** is a Python SDK and automation framework designed to bring modern DevOps practices to the Epicor Kinetic ecosystem. It provides a secure, extensible, and consistent foundation for environment management, CI/CD pipelines, and complex data migration workflows.

## Features

- 🔐 **Secure credential management** — OS keyring-backed encryption, no plaintext secrets
- 🔄 **Multi-environment support** — Seamlessly switch between Dev/Test/Prod
- 🛠️ **Ready-to-use Service Clients** — High-level clients for BAQ, BOReader, Reports, Tax, and more, built on a robust base client with wire logging and data redaction.
- 🚀 **Extensible Project Templates** — A "batteries-included" project structure with auto-discovery for creating your own reusable functions, layers, and scheduled jobs.
- 🤖 **CI/CD Ready** — Designed for automation with environment variable support, programmatic APIs, and pre-commit hooks for local validation.
- 📜 **Powerful CLI Tools** — Includes helper scripts for environment initialization, health validation, and common administrative tasks like configuration syncing.
- 🧩 **Layer Lifecycle Operations** — Native MetaFX support for core layer import/delete operations (`ImportLayers` / `BulkDeleteLayers`) with structured error reports.
- 🤖 **CI/CD ready** — Environment variables, programmatic API, pre-commit hooks
- 📦 **Modular architecture** — Extend with custom project submodules

## Quick Start

### Windows PowerShell
```powershell
.\scripts\env_init.ps1
python -m kinetic_devops.auth store
python scripts/validate.py
```

### Linux/macOS
```bash
python scripts/env_init.py
python -m kinetic_devops.auth store
python scripts/validate.py
```

## Usage

```python
from kinetic_devops.auth import KineticConfigManager
from kinetic_devops.baq import BAQClient

# Initialize authentication
config = KineticConfigManager()

# Create BAQ client (handles session, headers, requests)
baq_client = BAQClient(config)

# Execute a BAQ
results = baq_client.execute_baq(
    baq_id='CUST_List',
    args={'Company': 'ABC', 'MaxResults': 100}
)

# Process results
for customer in results['value']:
    print(f"{customer['CustomerID']}: {customer['CustomerName']}")
```

### MetaFX Layer DevOps Flow

```powershell
# Dry-run: parse dump files and resolve layer operations without sending requests
python -m kinetic_devops meta --env <ENV> --user <USER> layers "C:/path/dump (5).json" "C:/path/dump (6).json" --dry-run

# Execute: run import/delete operations and capture status + correlation IDs in a report
python -m kinetic_devops meta --env <ENV> --user <USER> layers "C:/path/dump (5).json" "C:/path/dump (6).json" --report temp/layer_ops_report.json
```

Default behavior for `layers` is deployment mode (`--ops import`):
- Executes delete operations first (when present)
- Then executes import operations

This flow is designed to support layer deployment and rollback as part of the DevOps cycle.

### ExportAllTheThings Full Export Flow

Export everything currently exposed by your ExportAllTheThings library:

```powershell
# Export all discovered Export* functions and write a manifest
python -m kinetic_devops export --env <ENV> --user <USER> --library ExportAllTheThings --out-dir exports/ExportAllTheThings

# List discovered export functions only
python -m kinetic_devops export --env <ENV> --user <USER> --list

# Run one export function
python -m kinetic_devops export --env <ENV> --user <USER> --function ExportAllCustomBAQs
```

The export command:
- Discovers export-capable functions from the EFx library (FunctionID starts with Export)
- Executes one or all exports
- Saves each artifact file
- Writes an export manifest JSON with per-function success/failure details

Mode behavior:
- `--mode auto` (default): uses ExportAllTheThings when present, otherwise native endpoints
- `--mode eatt`: requires EFx export library behavior
- `--mode native`: no ExportAllTheThings dependency

Native examples (no ExportAllTheThings required):

```powershell
# Run built-in native export plan for BAQs, directives, UD codes, MetaFX app list, etc.
python -m kinetic_devops export --mode native --env <ENV> --user <USER> --out-dir exports/native

# Pull one endpoint at a time
python -m kinetic_devops export --mode native --env <ENV> --user <USER> --native-endpoint "/api/v2/odata/{company}/Ice.BO.BAQDesignerSvc/GetList" --native-method POST --native-body '{"whereClause":"SystemFlag=false","pageSize":0,"absolutePage":0}' --native-name baq_list_single
```

### Solution Workbench Backup And Recreate

Solution migration is a different workflow from package build/install.

- `BuildSolution` and `InstallSolution` operate on a built package artifact
- `GetByID`, `GetNewExportPackage`, and `Update` operate on the solution definition dataset
- Recreating the solution in the target environment lets you build it there later

Typical operational sequence:
- `create` in Kinetic UI (author/edit your solution)
- `backup` in DevOps
- `build` in DevOps (when you need a package artifact)
- `install` in DevOps (when promoting by package)
- `recreate` in DevOps (when migrating editable solution definition state)

You can use package promotion (`build` + `install`) and definition migration (`recreate`) independently or together.

Examples:

```powershell
# Back up a solution definition and its tracked-item snapshots
python -m kinetic_devops solutions --env <SOURCE_ENV> --user <USER> backup MySolution --out-dir exports/solutions

# Recreate that solution definition in a target environment
python -m kinetic_devops solutions --env <TARGET_ENV> --user <USER> recreate exports/solutions/solution_backup_MySolution_20260331T000000Z.json

# Recreate under a new Solution ID, replacing an existing target solution if needed
python -m kinetic_devops solutions --env <TARGET_ENV> --user <USER> recreate exports/solutions/solution_backup_MySolution_20260331T000000Z.json --target-solution-id MySolution_Copy --overwrite

# Build a CAB package from a solution on the server
python -m kinetic_devops solutions --env <ENV> --user <USER> build MySolution

# Install a CAB package
python -m kinetic_devops solutions --env <ENV> --user <USER> install temp/MySolution.cab

# Install with automatic tenant-layer conflict cleanup and one retry
python -m kinetic_devops solutions --env <ENV> --user <USER> install temp/MySolution.cab --overwrite-duplicate-file --overwrite-duplicate-data --override-directives --auto-clear-layer-conflicts
```

Current recreate behavior is intentionally focused on the Solution Workbench definition:
- solution header and package rows
- solution detail membership rows
- backup capture of per-table dynamic/tracked snapshots for later analysis

`recreate` does not implicitly call `build` or `install`; those are explicit steps.

See [examples/complete_flow.py](examples/complete_flow.py) for a complete auth → BAQ → results example.

## Documentation

- [ARCHITECTURE.md](Documents/ARCHITECTURE.md) — Design principles, workflow examples
- [scripts/README.md](scripts/README.md) — Helper scripts reference
- [tests/README.md](tests/README.md) — Test suite documentation

## Known Limitations

- **Alpha stage** — Breaking changes may occur between versions
- **Redaction edge cases** — Heuristic-based sensitive data masking has known gaps
- **Windows-first** — Tested primarily on Windows; Linux/macOS support improving

## Project Structure

```
kinetic-devops/           # Core library (published)
├── kinetic_devops/       # Main package
├── scripts/              # Helper scripts
├── tests/                # Test suite
└── projects/             # (Optional) User project submodules
```

Users extend this core by adding private Git submodules for their custom implementations.

## Requirements

- Python 3.8+
- `keyring` — Secure credential storage
- `requests` — HTTP client

## Installation

Using `uv` (recommended):
```bash
uv pip install kinetic-devops
```

Or with pip:
```bash
pip install kinetic-devops
```

From source with `uv`:
```bash
git clone https://github.com/your-org/kinetic-devops.git
cd kinetic-devops
uv sync
uv pip install -e .
```

## License

See [LICENSE](LICENSE) file.
