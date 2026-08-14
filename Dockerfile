# Build and runtime share the same uv + CPython 3.12 image so the copied
# .venv symlinks stay valid between stages.
# Base pinned from ghcr.io/astral-sh/uv:python3.12-bookworm-slim on 2026-08-13.
FROM ghcr.io/astral-sh/uv@sha256:e5b65587bce7de595f299855d7385fe7fca39b8a74baa261ba1b7147afa78e58 AS build
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy
COPY pyproject.toml uv.lock .python-version ./
COPY src/ ./src/
COPY docs/README.md ./docs/README.md
RUN uv sync --frozen --no-dev --no-editable

FROM ghcr.io/astral-sh/uv@sha256:e5b65587bce7de595f299855d7385fe7fca39b8a74baa261ba1b7147afa78e58 AS runtime
ENV PYTHONUNBUFFERED=1 \
    TZ=Asia/Shanghai \
    PATH="/app/.venv/bin:$PATH"
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --create-home app
WORKDIR /app
COPY --from=build --chown=app:app /app/.venv /app/.venv
COPY --chown=app:app alembic.ini alembic.ini
COPY --chown=app:app alembic/ alembic/
USER app
CMD ["qq-time-agent-web"]
