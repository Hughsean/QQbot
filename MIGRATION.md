# Ubuntu migration bundle

This bundle targets Ubuntu Server `linux/amd64` with Docker Compose. It contains the
source, a PostgreSQL custom-format snapshot, the source-asset archive, and the Ollama
model volume archive. It never contains the source `.env` or secret values.

## First start

1. Install Docker Engine, Docker Compose v2, `curl`, and (for GPU mode) the NVIDIA
   driver plus NVIDIA Container Toolkit.
2. Extract the archive and copy `.env.example` to `.env`.
3. Provide the same `CREDENTIAL_ENCRYPTION_KEY` used by the source host if existing
   encrypted mailbox credentials must remain usable. Also provide the other required
   secrets in `.env`; do not commit or transmit it with the bundle.
4. Make scripts executable and run `./start.sh`.

`start.sh` verifies `SHA256SUMS`, restores the database and assets only when the new
PostgreSQL volume has not been migrated yet, and restores the Ollama model volume once.
It then runs migrations, replays tombstones, starts the three application roles, and
checks readiness. It is safe to run again after `.bundle-restored` and
`.ollama-restored` exist.

## GPU

`start.sh` auto-detects `nvidia-smi` and adds `compose.gpu.yaml`. A GTX 1650 Ti may
offload only part of `qwen3-embedding:4b`; the readiness probe is the authority. Set
`USE_GPU=1` to require the NVIDIA runtime, or leave it unset for CPU fallback when
the driver is unavailable. Do not expose Ollama outside the Compose network.

## Network and security

Web and PostgreSQL publish only to `127.0.0.1`. Ollama has no host port. The host
needs outbound HTTPS to QQ, DeepSeek, Microsoft, and Docker registries; no inbound
public port is required. Keep the bundle, `.env`, database backup, and encryption key
under separate filesystem permissions and run a restore drill before real use.
