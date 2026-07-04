FROM docker:27-cli AS docker-cli

FROM ghcr.io/astral-sh/uv:python3.14-trixie-slim@sha256:bebc7d6de6dd015a483903461eaedea12805728be6f9a044ca7106a2f7e11ddf

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    PATH="/app/.venv/bin:$PATH"

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=docker-cli /usr/local/bin/docker /usr/local/bin/docker

COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY resources ./resources
COPY infra ./infra

RUN uv sync --frozen --no-dev
RUN chmod +x /app/infra/docker/backend-entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/app/infra/docker/backend-entrypoint.sh"]
