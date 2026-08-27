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
# The application version is intentionally stable between source-only fixes. Do not reuse a
# cached wheel for this local package, otherwise Docker may ship an older source tree.
RUN uv sync --frozen --no-dev --no-editable --no-cache

FROM ghcr.io/astral-sh/uv@sha256:e5b65587bce7de595f299855d7385fe7fca39b8a74baa261ba1b7147afa78e58 AS runtime
ENV PYTHONUNBUFFERED=1 \
    TZ=Asia/Shanghai \
    PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH="/app/src"
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        libgl1 \
        libglib2.0-0 \
        libxcb1 \
        tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --create-home app
WORKDIR /app
COPY --from=build --chown=app:app /app/.venv /app/.venv
# Keep the current build-context source tree in the runtime image. The package version intentionally
# stays stable between source fixes, so relying on the installed local wheel alone can serve stale code.
COPY --chown=app:app src/ ./src/
COPY --chown=app:app alembic.ini alembic.ini
COPY --chown=app:app alembic/ alembic/
USER app
CMD ["qq-time-agent-web"]
