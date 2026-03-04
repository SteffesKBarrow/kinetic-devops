# env_init.ps1 -- PowerShell wrapper for Kinetic environment initialization
#
# Usage (dot-source):
#   . .\scripts\env_init.ps1 [env-name] [venv-path]
#
# This script:
# 1. Activates a Python venv (if provided)
# 2. Calls scripts/env_init.py to resolve stored Kinetic configuration
# 3. Generates and dot-sources env_vars_tmp.ps1 to set environment variables
# 4. Sets PYTHONPATH so helper scripts can import the kinetic_devops package
#
param(
    [string]$EnvName = "",
    [string]$VenvPath = "venv",
    [string]$TaxConfigDb = ""
)

$ErrorActionPreference = "Stop"

# 1. Resolve repo root
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$rootDir = Split-Path -Parent $scriptDir

# 2. Activate venv if it exists
if (Test-Path "$VenvPath\Scripts\Activate.ps1") {
    Write-Host "Python venv: $VenvPath"
    & "$VenvPath\Scripts\Activate.ps1"
} else {
    Write-Host "No venv at '$VenvPath', using system Python."
}

# 3. Set PYTHONPATH so the helper scripts can import kinetic_devops
$env:PYTHONPATH = $rootDir


# 4. Call env_init.py to generate env variables
Write-Host "Kinetic environment initialization..."
$taxConfigArg = ""
if ($TaxConfigDb) {
    $taxConfigArg = "--taxconfig-db `"$TaxConfigDb`""
    Write-Host "[env-init] Overriding KINETIC_TAXCONFIG_DB: $TaxConfigDb"
}
if ($EnvName) {
    python "$scriptDir\env_init.py" $EnvName $taxConfigArg
} else {
    python "$scriptDir\env_init.py" dev $taxConfigArg
}

# 5. Dot-source the generated PowerShell env file if it exists
$psEnvFile = "$rootDir\env_vars_tmp.ps1"
if (Test-Path $psEnvFile) {
    Write-Host "Loading environment variables from $psEnvFile"
    . $psEnvFile
} else {
    Write-Host "WARNING: env_vars_tmp.ps1 not found. Environment variables may not be set."
}

# 6. Clean up the temporary file (after sourcing)
if (Test-Path $psEnvFile) {
    Remove-Item -Force $psEnvFile -ErrorAction SilentlyContinue | Out-Null
}

Write-Host "Environment initialized with PYTHONPATH set to $rootDir"
