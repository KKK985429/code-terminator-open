#!/usr/bin/env bash
set -eo pipefail

# Prefer the project-local virtualenv for backend development.
if [ -f ".venv/bin/activate" ]; then
  # shellcheck disable=SC1091
  source ".venv/bin/activate"
elif command -v conda >/dev/null 2>&1; then
  # Some conda deactivate hooks reference unset vars; avoid nounset here.
  eval "$(conda shell.bash hook)"
  if conda env list | awk '{print $1}' | grep -qx "code-terminator"; then
    conda activate code-terminator
  else
    echo "[dev-backend] conda env 'code-terminator' not found, falling back to 'base'."
    conda activate base
  fi
else
  echo "[dev-backend] no .venv or conda env found; using current shell environment."
fi

BACKEND_PORT="${BACKEND_PORT:-18000}"
uv run uvicorn src.api.app:app --reload --host 127.0.0.1 --port "$BACKEND_PORT"
