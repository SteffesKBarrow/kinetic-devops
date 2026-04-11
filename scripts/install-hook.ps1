#Requires -Version 5.1
# ---------------------------------------------------------------------------
# Git Pre-Commit Hook Installer
#
# This script installs the project's pre-commit hook into your local
# .git/hooks folder. Run this once from within the repository to enable
# automated checks before you commit.
# ---------------------------------------------------------------------------

try {
    # Ensure we are running from within a git repository
    $repoRoot = git rev-parse --show-toplevel | Out-String -Stream
    if ($LASTEXITCODE -ne 0) {
        throw "This script must be run from within a git repository."
    }
}
catch {
    Write-Host "FATAL: $_" -ForegroundColor Red
    exit 1
}

# The content of the pre-commit hook script (uses 'sh' for cross-platform compatibility)
# Git for Windows includes a shell environment to run these hooks.
$hookContent = @'
#!/bin/sh
#
# This file is managed by scripts/install-hook.ps1. Do not edit directly.

echo "Running pre-commit checks..."

# Run the python check script (prefer uv when available)
if command -v uv >/dev/null 2>&1; then
    uv run python scripts/hooks/pre-commit
elif command -v python >/dev/null 2>&1; then
    python scripts/hooks/pre-commit
elif command -v py >/dev/null 2>&1; then
    py -3 scripts/hooks/pre-commit
else
    echo "Python runtime was not found in PATH. Aborting commit." >&2
    exit 1
fi

EXIT_CODE=$?

if [ $EXIT_CODE -ne 0 ]; then
    echo "Pre-commit checks failed. Aborting commit." >&2
    exit 1
fi

exit 0
'@

$hooksDir = Join-Path $repoRoot ".git\hooks"
$hookFile = Join-Path $hooksDir "pre-commit"

New-Item -ItemType Directory -Path $hooksDir -Force -ErrorAction SilentlyContinue | Out-Null
Set-Content -Path $hookFile -Value $hookContent -Encoding Ascii -Force

Write-Host "✅ Successfully installed pre-commit hook to: $hookFile" -ForegroundColor Green
Write-Host "This hook will now run automatically before each commit to prevent issues."