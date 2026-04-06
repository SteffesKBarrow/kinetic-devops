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

# Execute Python and evaluate exports
eval "$(python3 scripts/env_init.py ${ENV_NAME:-dev} $SET_API_FLAG)"

echo "✅ Environment initialized."