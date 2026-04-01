# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0a1] - 2026-03-03

**Status: ⚠️ ALPHA** — Early development. API and features may change significantly.

### Added
- **Core Authentication** — Secure keyring-backed credential management with optional PBKDF2+AES-256 encryption
- **Multi-environment Support** — Switch seamlessly between Dev/Test/Prod environments
- **Service Clients**:
  - `KineticBAQService` — Execute Business Analysis Queries
  - `KineticBOReaderService` — Query Business Objects via BOReader
  - `KineticFileService` — Manage DMS storage configurations
  - `KineticReportService` — Upload and manage RDL reports
  - `KineticTaxService` — Manage tax configurations
  - `KineticMetafetcher` — Query system metadata
- **Base Infrastructure**:
  - `KineticBaseClient` — Session management and authenticated requests
  - `KineticConfigManager` — Credential storage and token lifecycle
  - `KineticCore` — Security, redaction, and wire logging
- **CLI Tools**:
  - `env_init.py` / `env_init.ps1` — Interactive environment setup
  - `validate.py` — Environment health checks
  - `pull_tax_configs.py` — Export tax configurations
  - `refresh_post_db.py` — Post-database refresh automation
  - `tax_clear.py` — Bulk tax record deletion
- **Security Features**:
  - Heuristic-based sensitive data redaction
  - Wire logging with request/response masking
  - Secure configuration hashing and integrity verification
- **Documentation**:
  - Architecture guide with design patterns
  - Helper script reference
  - Test suite documentation

### Known Issues
- **Redaction edge cases** — Heuristic regex has known gaps with escaped JSON and whitespace variations
- **Windows-first development** — Linux/macOS tested but less mature
- **Pre-commit hook** — May fail on slow systems during initial test run

### Security Notice
- **Never commit `.env` or keyring credentials** — Already excluded in `.gitignore`
- **Alpha APIs may change** — Especially around request/response signatures
- **Test environment only** — Not recommended for production yet

### Future (Post-Alpha)
- Enhanced redaction with configurable patterns
- Async service client support
- GraphQL support for complex BOReader queries
- Docker/container environment initialization
- GitHub Actions integration templates
