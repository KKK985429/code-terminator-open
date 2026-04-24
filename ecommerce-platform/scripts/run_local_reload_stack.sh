#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_DIR="$ROOT/.runtime/local-stack"
PID_DIR="$RUNTIME_DIR/pids"
LOG_DIR="$RUNTIME_DIR/logs"
PORTS_FILE="$RUNTIME_DIR/ports.env"
DB_FILE="${DB_FILE:-$ROOT/.runtime/ecommerce.db}"
APP_LOG_FILE="${LOG_FILE:-$ROOT/logs/ecommerce-debug.jsonl}"

mkdir -p "$PID_DIR" "$LOG_DIR" "$(dirname "$DB_FILE")" "$(dirname "$APP_LOG_FILE")"

if [[ -x "$ROOT/.venv/bin/python" ]]; then
  PYTHON_BIN="$ROOT/.venv/bin/python"
else
  PYTHON_BIN="${PYTHON_BIN:-python3}"
fi

if [[ -f "$ROOT/.env" ]]; then
  # shellcheck disable=SC1091
  source "$ROOT/.env"
fi

pick_port() {
  local preferred="$1"
  shift
  "$PYTHON_BIN" - "$preferred" "$@" <<'PY'
import socket
import sys

preferred = int(sys.argv[1])
candidates = [preferred, *[int(value) for value in sys.argv[2:]]]

def available(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return sock.connect_ex(("127.0.0.1", port)) != 0

for port in candidates:
    if available(port):
        print(port)
        raise SystemExit(0)

with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
    sock.bind(("127.0.0.1", 0))
    print(sock.getsockname()[1])
PY
}

wait_for_http() {
  local url="$1"
  local name="$2"
  for _ in $(seq 1 80); do
    if "$PYTHON_BIN" - "$url" <<'PY'
import sys
import urllib.request

url = sys.argv[1]
try:
    with urllib.request.urlopen(url, timeout=1.5) as resp:
        if resp.status < 500:
            raise SystemExit(0)
except Exception:
    pass
raise SystemExit(1)
PY
    then
      return 0
    fi
    sleep 0.5
  done
  echo "Timed out waiting for $name at $url" >&2
  return 1
}

start_service() {
  local name="$1"
  local module="$2"
  local port="$3"
  local service_name="$4"
  shift 4
  local extra_env=("$@")
  local logfile="$LOG_DIR/$name.log"
  local pidfile="$PID_DIR/$name.pid"
  if [[ -f "$pidfile" ]] && kill -0 "$(cat "$pidfile")" 2>/dev/null; then
    echo "$name already running on PID $(cat "$pidfile")"
    return 0
  fi

  local env_prefix=""
  for kv in "${extra_env[@]}"; do
    env_prefix+="export ${kv}; "
  done
  nohup bash -lc "
    cd '$ROOT'
    export PYTHONPATH='$ROOT'
    export DATABASE_URL='sqlite:///$DB_FILE'
    export REDIS_URL='${REDIS_URL:-redis://127.0.0.1:6379/0}'
    export SYNC_TASKS='true'
    export LOG_FILE='$APP_LOG_FILE'
    export SERVICE_NAME='$service_name'
    ${env_prefix}
    exec '$PYTHON_BIN' -m uvicorn '$module' \
      --host 127.0.0.1 \
      --port '$port' \
      --reload \
      --reload-dir '$ROOT/services' \
      --reload-dir '$ROOT/scripts'
  " >"$logfile" 2>&1 </dev/null &
  echo $! >"$pidfile"
}

ORDER_PORT="$(pick_port 58001 58011 58101)"
INVENTORY_PORT="$(pick_port 58002 58012 58102)"
PAYMENT_PORT="$(pick_port 58003 58013 58103)"
USER_PORT="$(pick_port 58004 58014 58104)"
GATEWAY_PORT="$(pick_port 58080 58081 58180)"

cat >"$PORTS_FILE" <<EOF
ORDER_PORT=$ORDER_PORT
INVENTORY_PORT=$INVENTORY_PORT
PAYMENT_PORT=$PAYMENT_PORT
USER_PORT=$USER_PORT
GATEWAY_PORT=$GATEWAY_PORT
DB_FILE=$DB_FILE
LOG_FILE=$APP_LOG_FILE
EOF

(
  cd "$ROOT"
  export PYTHONPATH="$ROOT"
  export DATABASE_URL="sqlite:///$DB_FILE"
  export SYNC_TASKS="true"
  "$PYTHON_BIN" scripts/init_db.py
) >"$LOG_DIR/init-db.log" 2>&1

start_service order services.order.main:app "$ORDER_PORT" order-service
start_service inventory services.inventory.main:app "$INVENTORY_PORT" inventory-service
start_service payment services.payment.main:app "$PAYMENT_PORT" payment-service
start_service user services.user.main:app "$USER_PORT" user-service

wait_for_http "http://127.0.0.1:$ORDER_PORT/health" "order-service"
wait_for_http "http://127.0.0.1:$INVENTORY_PORT/health" "inventory-service"
wait_for_http "http://127.0.0.1:$PAYMENT_PORT/health" "payment-service"
wait_for_http "http://127.0.0.1:$USER_PORT/health" "user-service"

start_service gateway scripts.local_gateway:app "$GATEWAY_PORT" local-gateway \
  ORDER_BASE_URL="http://127.0.0.1:$ORDER_PORT" \
  INVENTORY_BASE_URL="http://127.0.0.1:$INVENTORY_PORT" \
  PAYMENT_BASE_URL="http://127.0.0.1:$PAYMENT_PORT" \
  USER_BASE_URL="http://127.0.0.1:$USER_PORT" \
  SIMULATOR_STATUS_FILE="$ROOT/.runtime/traffic-simulator-$GATEWAY_PORT.json"

wait_for_http "http://127.0.0.1:$GATEWAY_PORT/health" "local-gateway"

echo "Local reload stack is running."
echo "Gateway: http://127.0.0.1:$GATEWAY_PORT"
echo "Monitor: http://127.0.0.1:$GATEWAY_PORT/monitor"
echo "Ports file: $PORTS_FILE"
echo "Unified log: $APP_LOG_FILE"
echo "PID dir: $PID_DIR"
