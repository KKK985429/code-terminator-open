#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${1:-http://localhost}"

for path in \
  "/health" \
  "/api/v1/orders/user/1" \
  "/api/v1/inventory/1" \
  "/api/v1/payments/calculate?total=99.99&vip_level=1" \
  "/api/v1/users/1" \
  "/api/agent/health"
do
  echo "checking ${BASE_URL}${path}"
  curl -fsS "${BASE_URL}${path}" || true
  echo
done
