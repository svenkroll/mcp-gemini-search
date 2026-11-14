# Container image of the Gemini Search MCP server (docs/adr/0011-container-and-ci.md,
# docs/adr/0010-configuration.md). Multi-stage: dependencies and the project are
# installed with uv in the builder stage; the runtime stage holds only the
# virtual environment. Configuration comes from environment variables at run
# time; the image contains no secrets.

# ghcr.io/astral-sh/uv 0.13.7
FROM ghcr.io/astral-sh/uv:0.13.7@sha256:96f40d3904aad8d0bd010539001d36c8e2188b981e1334471a90c4a1d93bb490 AS uv

# python 3.14-slim-trixie
FROM python:3.14-slim-trixie@sha256:9aaa474097d094040649f2162a627c0049b408f52138d980916788d80f04802f AS builder

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

# python 3.14-slim-trixie
FROM python:3.14-slim-trixie@sha256:9aaa474097d094040649f2162a627c0049b408f52138d980916788d80f04802f AS runtime

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
