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
