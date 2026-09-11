#!/bin/sh
# --- ARGUMENT PARSING ---
VENV_PATH="venv"
FORCE_RUN_FLAG="${ENV_INIT_FORCE_RUN}"

# POSIX-compliant flag and argument parsing
while [ "$#" -gt 0 ]; do
    case "$1" in
        --init-force) FORCE_RUN_FLAG="1" ;;
        --set-api-key) SET_API_FLAG="--set-api-key" ;;
        -*) echo "Unknown option: $1"; return 1 2>/dev/null || exit 1 ;;
        *) 
            # If we don't have an ENV_NAME yet, first positional is ENV
            if [ -z "$ENV_NAME" ]; then ENV_NAME="$1"
            else VENV_PATH="$1"; fi
            ;;
    esac
    shift
done

# --- SOURCING VALIDATION ---
if [ "$0" = "sh" ] || [ "$0" = "bash" ] || [ "$0" = "ash" ] || [ "$0" = "-sh" ]; then
    : # Likely sourced
elif [ -n "$FORCE_RUN_FLAG" ]; then
    echo "⚠️ WARNING: Running without sourcing as requested."
else
    if [ -f "$0" ] && [ "$(basename "$0")" = "env_init.sh" ]; then
        echo "🚨 ERROR: This script must be sourced."
        echo "Usage: . ./env_init.sh [env] [venv_path]"
        return 1 2>/dev/null || exit 1
    fi
fi

# venv Activation
if [ -d "$VENV_PATH" ]; then
    . "$VENV_PATH/bin/activate"
fi

# Execute Python, source generated export file, then clean it up
INIT_OUTPUT="$(python3 scripts/env_init.py "${ENV_NAME:-dev}" $SET_API_FLAG)" || return 1 2>/dev/null || exit 1
ENV_FILE="$(printf '%s\n' "$INIT_OUTPUT" | sed -n 's/^WRITTEN_SH: //p' | tail -n 1)"

if [ -z "$ENV_FILE" ] || [ ! -f "$ENV_FILE" ]; then
    echo "🚨 ERROR: Initialization file was not created."
    [ -n "$INIT_OUTPUT" ] && printf '%s\n' "$INIT_OUTPUT"
    return 1 2>/dev/null || exit 1
fi

cleanup_env_file() {
    rm -f "$ENV_FILE"
}

trap cleanup_env_file EXIT HUP INT TERM
. "$ENV_FILE"
SOURCE_STATUS=$?
trap - EXIT HUP INT TERM
cleanup_env_file

if [ "$SOURCE_STATUS" -ne 0 ]; then
    return "$SOURCE_STATUS" 2>/dev/null || exit "$SOURCE_STATUS"
fi

echo "✅ Environment initialized."