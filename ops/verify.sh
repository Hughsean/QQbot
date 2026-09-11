#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
PORT="${APP_LISTEN_PORT:-8000}"
deadline=$((SECONDS + ${VERIFY_TIMEOUT_SECONDS:-180}))
while (( SECONDS < deadline )); do
  if curl --fail --silent --show-error "http://127.0.0.1:${PORT}/health/ready" | grep -q '"status":"ready"'; then
    curl --fail --silent "http://127.0.0.1:${PORT}/metrics" >/dev/null
    echo "QQ Time Agent is ready on loopback port ${PORT}."
    exit 0
  fi
  sleep 2
done
echo "QQ Time Agent did not become ready within the verification window." >&2
exit 1
