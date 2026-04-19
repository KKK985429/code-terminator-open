#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DOCKER_DIR="${ROOT_DIR}/.docker"
SOCK_PATH="${DOCKER_DIR}/docker.sock"
PID_PATH="${DOCKER_DIR}/dockerd.pid"
LOG_PATH="${DOCKER_DIR}/dockerd.log"
CONFIG_PATH="${DOCKER_DIR}/daemon.json"
DATA_ROOT="${DOCKER_DIR}/data"
EXEC_ROOT="${DOCKER_DIR}/exec"

mkdir -p "${DATA_ROOT}" "${EXEC_ROOT}"

if [[ -S "${SOCK_PATH}" ]]; then
  if docker --host "unix://${SOCK_PATH}" info >/dev/null 2>&1; then
    echo "docker socket already exists at ${SOCK_PATH}"
    exit 0
  fi
  rm -f "${SOCK_PATH}" "${PID_PATH}"
fi

exec dockerd \
  --host "unix://${SOCK_PATH}" \
  --data-root "${DATA_ROOT}" \
  --exec-root "${EXEC_ROOT}" \
  --pidfile "${PID_PATH}" \
  --config-file "${CONFIG_PATH}"
