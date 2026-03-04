@echo off
setlocal enabledelayedexpansion

:: 1. SET DEFAULTS
set "ENV_NAME=dev"
set "VENV_PATH=venv"
set "TAXCONFIG_DB="

:: 2. EVALUATE ARGUMENT 1
if not "%~1"=="" (
    if exist "%~1\" (
        set "VENV_PATH=%~1"
    ) else (
        set "ENV_NAME=%~1"
    )
)

:: 2b. EVALUATE ARGUMENT 3 for TAXCONFIG_DB override
if not "%~3"=="" (
    set "TAXCONFIG_DB=%~3"
)

:: 3. EVALUATE ARGUMENT 2
if not "%~2"=="" (
    if exist "%~2\" (
        set "VENV_PATH=%~2"
    ) else (
        :: Only set this as ENV_NAME if Arg 1 was used for VENV
        if exist "%~1\" set "ENV_NAME=%~2"
    )
)

:: 4. VENV ACTIVATION
if exist "!VENV_PATH!\Scripts\activate.bat" (
    echo 🐍 Venv: !VENV_PATH!
    call "!VENV_PATH!\Scripts\activate.bat"
) else (
    echo ℹ️ No venv at "!VENV_PATH!", using system Python.
)

:: 5. EXECUTION
echo 🔑 Target: !ENV_NAME!

:: Pass TAXCONFIG_DB override if set
set "TAXCONFIG_ARG="
if not "!TAXCONFIG_DB!"=="" set "TAXCONFIG_ARG=--taxconfig-db=!TAXCONFIG_DB!"

python scripts/env_init.py !ENV_NAME! !TAXCONFIG_ARG! %*

:: 6. THE HAND-OFF (The "Use" Phase)
:: This is where the variables move from the FILE to the CMD SESSION
if exist env_vars_tmp.bat (
    call env_vars_tmp.bat
) else (
    echo 🚨 ERROR: Initialization file was not created.
    exit /b 1
)

:: --- THREE-STAGE AUDIT CLEANUP ---

:: STAGE 1: Call Python for Secure Wipe (Per-pass jitter)
python scripts\env_init.py --cleanup-only

:: STAGE 2: Standard Delete Fallback
if exist env_vars_tmp.bat (
    del /f /q env_vars_tmp.bat >nul 2>&1
)

:: STAGE 2b: Clean up PowerShell env file
if exist env_vars_tmp.ps1 (
    del /f /q env_vars_tmp.ps1 >nul 2>&1
)

:: STAGE 3: Final Audit and Escalation
if exist env_vars_tmp.bat (
    echo.
    echo *******************************************************************
    echo 🚨 ERROR: SENSITIVE FILE PERSISTS AND COULD NOT BE DELETED.
    echo    Location: %CD%\env_vars_tmp.bat
    echo.
    echo    ADVICE: Manually delete this file immediately to protect 
    echo            your credentials.
    echo *******************************************************************
    pause
    exit /b 1
)

echo ✅ Environment initialized and sensitive data wiped.