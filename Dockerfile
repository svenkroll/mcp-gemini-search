# Container image for the HTTP transport (ADR 0002, ADR 0010).
# Both base images are pinned by digest; update tag and digest together.

# uv, copied as a static binary from the pinned official image (same version as CI).
FROM ghcr.io/astral-sh/uv:0.13.7@sha256:96f40d3904aad8d0bd010539001d36c8e2188b981e1334471a90c4a1d93bb490 AS uv

FROM python:3.14-slim-trixie@sha256:9aaa474097d094040649f2162a627c0049b408f52138d980916788d80f04802f AS builder

COPY --from=uv /uv /usr/local/bin/uv

# Use the interpreter of the base image, install real copies (the virtual
# environment is copied into the final stage) and compile bytecode now, because
# the final image may run with a read-only root filesystem.
ENV UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_NO_CACHE=1

WORKDIR /app

# Dependencies first, so this layer is reused while only the sources change.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-dev --no-install-project

COPY src ./src
RUN uv sync --locked --no-dev --no-editable

FROM python:3.14-slim-trixie@sha256:9aaa474097d094040649f2162a627c0049b408f52138d980916788d80f04802f

# Install the Debian security updates published after the pinned base image was
# built, and remove pip: the server does not need it at run time, and its
# vendored libraries would be scanned as part of the image. The non-root user
# has a fixed numeric ID, so Kubernetes can verify runAsNonRoot.
RUN apt-get update \
    && apt-get upgrade --yes --no-install-recommends \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* \
    && python -m pip uninstall --yes pip \
    && groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --no-create-home --home-dir /nonexistent \
        --shell /usr/sbin/nologin app

COPY --from=builder /app/.venv /app/.venv

# No secrets here: GEMINI_API_KEY and MCP_BEARER_TOKEN are passed at run time.
# The process writes only to stdout and stderr and needs no writable path.
ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    MCP_TRANSPORT=http \
    MCP_HOST=0.0.0.0

USER 10001:10001

EXPOSE 8000

ENTRYPOINT ["gemini-search-mcp"]
