#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET="${1:-green}"
UPSTREAM_FILE="${ROOT_DIR}/nginx/conf.d/upstream.conf"

if [[ "${TARGET}" != "green" && "${TARGET}" != "blue" ]]; then
  echo "usage: $0 [green|blue]"
  exit 1
fi

python - "${UPSTREAM_FILE}" "${TARGET}" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
target = sys.argv[2]
text = path.read_text(encoding="utf-8")
if target == "green":
    text = text.replace("weight=10;", "weight=TEMP;")
    text = text.replace("weight=0;", "weight=10;")
    text = text.replace("weight=TEMP;", "weight=0;")
else:
    lines = []
    for line in text.splitlines():
        if "-a:" in line:
            lines.append(line.rsplit("weight=", 1)[0] + "weight=10;")
        elif "-b:" in line:
            lines.append(line.rsplit("weight=", 1)[0] + "weight=0;")
        else:
            lines.append(line)
    text = "\n".join(lines) + "\n"
path.write_text(text, encoding="utf-8")
PY

echo "switched upstream weights to ${TARGET}"
echo "reload nginx with: docker compose exec nginx nginx -s reload"
