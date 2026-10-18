#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
PORT="${APP_LISTEN_PORT:-8000}"
deadline=$((SECONDS + ${VERIFY_TIMEOUT_SECONDS:-180}))
while (( SECONDS < deadline )); do
  if curl --fail --silent --show-error "http://127.0.0.1:${PORT}/health/ready" | grep -q '"status":"ready"'; then
    echo "Go foundation dependencies are ready on loopback port ${PORT}; see the migration status for business readiness."
    exit 0
  fi
  sleep 2
done
echo "QQ Time Agent did not become ready within the verification window." >&2
exit 1
