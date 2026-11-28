# Container image of the Gemini Search MCP server (docs/adr/0011-container-and-ci.md,
# docs/adr/0010-configuration.md). Multi-stage: dependencies and the project are
# installed with uv in the builder stage; the runtime stage holds only the
# virtual environment. Configuration comes from environment variables at run
# time; the image contains no secrets.

# The Python base image of both stages, the single place of its version and digest.
# python 3.14-slim-trixie
ARG PYTHON_IMAGE=python:3.14-slim-trixie@sha256:f57c4c23b985d95deea5bc5249e2f9c8a512b4cc9d5d3fd31900cbd2f5f0a604

# The single source of uv: the builder stage copies it from here and the check job
# exports it with scripts/ci/export-uv.sh.
FROM ghcr.io/astral-sh/uv:0.13.10@sha256:a3ea1357342c1a4bf9a0c53a3deb1b55379aefa037338d8113d5771efa01774f AS uv

FROM ${PYTHON_IMAGE} AS builder

COPY --from=uv /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app

# Dependencies first: this layer is rebuilt only when pyproject.toml or uv.lock change.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

# README.md is the package readme that the build backend reads.
COPY README.md ./
COPY src ./src
RUN uv sync --locked --no-dev --no-editable

FROM ${PYTHON_IMAGE} AS runtime

RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid 10001 --no-create-home \
        --home-dir /nonexistent --shell /usr/sbin/nologin app

COPY --from=builder /app/.venv /app/.venv

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MCP_TRANSPORT=http \
    MCP_HOST=0.0.0.0

USER 10001:10001

EXPOSE 8000

CMD ["gemini-search-mcp"]
