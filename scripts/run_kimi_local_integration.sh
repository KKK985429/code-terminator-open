#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")"/.. && pwd)"
cd "${ROOT_DIR}"

cmd="${1:-single}"
if [[ $# -gt 0 ]]; then
  shift
fi

case "${cmd}" in
  single)
    exec uv run --python python3.12 python scripts/run_kimi_local_integration.py "$@"
    ;;
  suite)
    exec uv run --python python3.12 python scripts/run_kimi_local_suite.py "$@"
    ;;
  worker-contract)
    exec uv run --python python3.12 python scripts/run_kimi_worker_contract_local.py "$@"
    ;;
  *)
    echo "Unknown command: ${cmd}" >&2
    echo "Usage: $0 [single|suite|worker-contract] [args...]" >&2
    exit 2
    ;;
esac
