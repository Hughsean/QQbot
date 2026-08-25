#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"
COMPOSE_FILES=(-f compose.yaml)
USE_GPU="${USE_GPU:-auto}"
gpu_available=0
if command -v nvidia-smi >/dev/null && nvidia-smi -L >/dev/null 2>&1; then gpu_available=1; fi
if [[ "$USE_GPU" == "1" || ( "$USE_GPU" == "auto" && "$gpu_available" == "1" ) ]]; then
  COMPOSE_FILES+=(-f compose.gpu.yaml)
  echo "Using NVIDIA GPU mode for Ollama."
else
  echo "Using CPU mode for Ollama. Set USE_GPU=1 to require NVIDIA GPU mode."
fi
[[ -f .env ]] || { echo "Missing .env; copy .env.example and provide secrets out of band." >&2; exit 2; }
command -v docker >/dev/null || { echo "Docker is required" >&2; exit 2; }
docker compose version >/dev/null || { echo "Docker Compose is required" >&2; exit 2; }
docker compose "${COMPOSE_FILES[@]}" config --quiet
if [[ -f SHA256SUMS ]]; then sha256sum --quiet -c SHA256SUMS; fi
if [[ -f images/images.tar ]]; then
  docker load < images/images.tar
else
  docker compose "${COMPOSE_FILES[@]}" build
fi
docker compose "${COMPOSE_FILES[@]}" up -d postgres
for _ in {1..60}; do
  if docker compose "${COMPOSE_FILES[@]}" exec -T postgres sh -c 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"' >/dev/null 2>&1; then break; fi
  sleep 2
done
docker compose "${COMPOSE_FILES[@]}" exec -T postgres sh -c 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"' >/dev/null
if [[ -f data/database.dump && ! -f .bundle-restored ]]; then
  initialized="$(docker compose "${COMPOSE_FILES[@]}" exec -T postgres sh -c "psql -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\" -Atqc \"SELECT to_regclass('public.alembic_version') IS NOT NULL\"" 2>/dev/null || true)"
  if [[ "$initialized" == *t* ]]; then
    echo "Database is already initialized; refusing automatic overwrite." >&2
    echo "Remove the new volume only after taking a backup, then retry." >&2
    exit 3
  fi
  echo "Restoring bundled PostgreSQL snapshot."
  docker compose "${COMPOSE_FILES[@]}" exec -T postgres sh -c 'dropdb --if-exists -U "$POSTGRES_USER" "$POSTGRES_DB" && createdb -U "$POSTGRES_USER" "$POSTGRES_DB"'
  docker compose "${COMPOSE_FILES[@]}" exec -T postgres sh -c 'pg_restore --no-owner -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < data/database.dump
  if [[ -f data/assets.tar ]]; then
    docker compose "${COMPOSE_FILES[@]}" run --rm --no-deps -T --entrypoint sh web -c 'tar -xf - -C /var/lib/qq-time-agent/assets' < data/assets.tar
  fi
  touch .bundle-restored
fi
if [[ -f data/ollama-model.tar && ! -f .ollama-restored ]]; then
  docker compose "${COMPOSE_FILES[@]}" run --rm --no-deps -T --entrypoint sh ollama -c 'tar -xf - -C /root/.ollama' < data/ollama-model.tar
  touch .ollama-restored
fi
docker compose "${COMPOSE_FILES[@]}" up -d ollama
docker compose "${COMPOSE_FILES[@]}" run --rm migrate
if [[ -f .bundle-restored ]]; then docker compose "${COMPOSE_FILES[@]}" run --rm replay-tombstones; fi
docker compose "${COMPOSE_FILES[@]}" up -d web worker qq
"$ROOT_DIR/ops/verify.sh"
