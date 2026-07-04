
• Proposed Plan


# 実装一式

以下をそのまま追加・変更してください。未コミットの frontend 変更は触らない前提です。

## 1. compose.yml 追加

services:
  backend:
    build:
      context: .
      dockerfile: infra/docker/backend.Dockerfile
    ports:
      - "8000:8000"
    environment:
      OPENAI_API_KEY: ${OPENAI_API_KEY:?Set OPENAI_API_KEY}
      MY_AI_AGENT_CONFIG: /app/src/agent/config/config.yml
      LLM_MODEL: ${LLM_MODEL:?Set LLM_MODEL}
      LLM_BASE_URL: ${LLM_BASE_URL:?Set LLM_BASE_URL}
      LLM_TEMPERATURE: ${LLM_TEMPERATURE:-}
      AGENT_CODE_EXEC: ${AGENT_CODE_EXEC:-true}
      AGENT_CODE_EXEC_IMAGE: ${AGENT_CODE_EXEC_IMAGE:-ai-agent-python:local}
      AGENT_SKILLS_DIR: ${AGENT_SKILLS_DIR:-resources/skills}
      PRELOAD_SANDBOX_IMAGE: ${PRELOAD_SANDBOX_IMAGE:-true}
    privileged: true
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - microsandbox-data:/root/.local/share/microsandbox
      - microsandbox-cache:/root/.cache/microsandbox
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz').read()"]
      interval: 10s
      timeout: 5s
      retries: 12

  frontend:
    build:
      context: .
      dockerfile: infra/docker/frontend.Dockerfile
      args:
        VITE_AG_UI_URL: /agent
    ports:
      - "5173:80"
    depends_on:
      backend:
        condition: service_healthy

volumes:
  microsandbox-data:
  microsandbox-cache:

## 2. infra/docker/backend.Dockerfile 追加

FROM ghcr.io/astral-sh/uv:python3.14-trixie-slim@sha256:bebc7d6de6dd015a483903461eaedea12805728be6f9a044ca7106a2f7e11ddf

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    PATH="/app/.venv/bin:$PATH"

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates docker.io \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY resources ./resources
COPY infra ./infra

RUN uv sync --frozen --no-dev
RUN chmod +x /app/infra/docker/backend-entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/app/infra/docker/backend-entrypoint.sh"]

## 3. infra/docker/backend-entrypoint.sh 追加

#!/usr/bin/env sh
set -eu

log() {
  printf '%s\n' "$*" >&2
}

is_true() {
  case "${1:-}" in
    1|true|TRUE|yes|YES|on|ON) return 0 ;;
    *) return 1 ;;
  esac
}

preload_sandbox_image() {
  image="${AGENT_CODE_EXEC_IMAGE:-ai-agent-python:local}"
  tar_path="${SANDBOX_IMAGE_TAR:-/tmp/ai-agent-python.tar}"

  if ! command -v docker >/dev/null 2>&1; then
    log "warn: docker CLI not found; skip microsandbox image preload"
    return 0
  fi

  if [ ! -S /var/run/docker.sock ]; then
    log "warn: /var/run/docker.sock not mounted; skip microsandbox image preload"
    return 0
  fi

  if ! command -v msb >/dev/null 2>&1; then
    log "warn: msb CLI not found; skip microsandbox image preload"
    return 0
  fi

  log "preloading microsandbox image: ${image}"

  if docker build -t "${image}" -f infra/sandbox/Dockerfile . \
    && docker save "${image}" -o "${tar_path}" \
    && msb image load -i "${tar_path}" -t "${image}"; then
    log "microsandbox image preloaded: ${image}"
  else
    log "warn: microsandbox image preload failed; backend will continue"
  fi
}

if is_true "${AGENT_CODE_EXEC:-true}" && is_true "${PRELOAD_SANDBOX_IMAGE:-true}"; then
  preload_sandbox_image
fi

exec uvicorn api.main:app --host 0.0.0.0 --port 8000

## 4. infra/docker/frontend.Dockerfile 追加

FROM node:22-bookworm-slim AS build

WORKDIR /app

ARG VITE_AG_UI_URL=/agent
ENV VITE_AG_UI_URL=${VITE_AG_UI_URL}

COPY src/frontend/web/package*.json ./
RUN npm ci

COPY src/frontend/web/ ./
RUN npm run build

FROM nginx:1.27-alpine

COPY infra/docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

## 5. infra/docker/nginx.conf 追加

server {
  listen 80;
  server_name _;

  root /usr/share/nginx/html;
  index index.html;

  location /agent {
    proxy_pass http://backend:8000/agent;
    proxy_http_version 1.1;

    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header Connection "";

    proxy_buffering off;
    proxy_cache off;
    proxy_read_timeout 3600s;
    proxy_send_timeout 3600s;
  }

  location / {
    try_files $uri $uri/ /index.html;
  }
}

## 6. .dockerignore 追加

.git
.codex
.agents

.env
.env.*
*.local

.venv
.uv-cache
.uv_cache
.pytest_cache
.mypy_cache
.ruff_cache
__pycache__
*.pyc

node_modules
dist
dist-ssr

.DS_Store

## 7. .env.example 追加

OPENAI_API_KEY=your-api-key
LLM_MODEL=openai/your-model
LLM_BASE_URL=https://your-openai-compatible-endpoint/v1
LLM_TEMPERATURE=0.2

AGENT_CODE_EXEC=true
AGENT_CODE_EXEC_IMAGE=ai-agent-python:local
AGENT_SKILLS_DIR=resources/skills
PRELOAD_SANDBOX_IMAGE=true

## 8. pyproject.toml 変更

dependencies に追加:

"uvicorn[standard]>=0.49.0",

その後:

uv lock

## 9. src/api/main.py 変更

先頭 import に追加:

import os

lifespan 内を変更:

@asynccontextmanager
async def lifespan(_: FastAPI):
    load_env()
    config_path = Path(os.environ.get("MY_AI_AGENT_CONFIG", str(DEFAULT_CONFIG)))
    config = load_config(config_path)
    client = get_client(config)
    session_manager = InMemorySessionManager()

## 10. src/agent/init.py 変更

load_config の return 前を変更:

    return apply_env_overrides(data)

parse_env_line の下あたりに追加:

def env_value(name: str) -> str | None:
    value = os.environ.get(name)
    if value is None:
        return None

    stripped = value.strip()
    return stripped or None


def ensure_config_section(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key)
    if value is None:
        section: dict[str, Any] = {}
        data[key] = section
        return section

    if isinstance(value, dict):
        return value

    raise ValueError(f"Config section must be an object: {key}")


def parse_bool(value: str, label: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False

    raise ValueError(f"{label} must be a boolean value.")


def apply_env_overrides(data: dict[str, Any]) -> dict[str, Any]:
    llm_model = env_value("LLM_MODEL")
    llm_base_url = env_value("LLM_BASE_URL")
    llm_temperature = env_value("LLM_TEMPERATURE")

    if llm_model or llm_base_url or llm_temperature:
        llm = ensure_config_section(data, "llm")

        if llm_model:
            llm["model"] = llm_model

        if llm_base_url:
            llm["base_url"] = llm_base_url

        if llm_temperature:
            try:
                llm["temperature"] = float(llm_temperature)
            except ValueError as error:
                raise ValueError("LLM_TEMPERATURE must be a number.") from error

    agent_code_exec = env_value("AGENT_CODE_EXEC")
    agent_code_exec_image = env_value("AGENT_CODE_EXEC_IMAGE")
    agent_skills_dir = env_value("AGENT_SKILLS_DIR")

    if agent_code_exec or agent_code_exec_image or agent_skills_dir:
        agent = ensure_config_section(data, "agent")

        if agent_code_exec:
            agent["code_exec"] = parse_bool(agent_code_exec, "AGENT_CODE_EXEC")

        if agent_code_exec_image:
            agent["code_exec_image"] = agent_code_exec_image

        if agent_skills_dir:
            agent["skills_dir"] = agent_skills_dir

    return data

## 11. infra/sandbox/Dockerfile 修正

markitdown \  の trailing space を消す。ついでに BuildKit 依存を避けるならこうする:

FROM ghcr.io/astral-sh/uv:python3.14-trixie-slim@sha256:bebc7d6de6dd015a483903461eaedea12805728be6f9a044ca7106a2f7e11ddf

RUN uv pip install --system \
    pandas \
    openpyxl \
    numpy \
    pymupdf \
    markitdown \
    pyyaml

CMD ["python"]

## 12. テスト追加

src/agent/tests/test_init.py の import に apply_env_overrides を追加:

from agent.init import apply_env_overrides, get_agent, get_client, parse_env_line, require_section  # noqa: E402

テスト追加:

def test_apply_env_overrides_updates_llm_and_agent(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LLM_MODEL", "openai/test-model")
    monkeypatch.setenv("LLM_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("LLM_TEMPERATURE", "0.1")
    monkeypatch.setenv("AGENT_CODE_EXEC", "false")
    monkeypatch.setenv("AGENT_CODE_EXEC_IMAGE", "ai-agent-python:local")
    monkeypatch.setenv("AGENT_SKILLS_DIR", "resources/skills")

    config = apply_env_overrides({"llm": {}, "agent": {}})

    assert config["llm"] == {
        "model": "openai/test-model",
        "base_url": "https://example.test/v1",
        "temperature": 0.1,
    }
    assert config["agent"]["code_exec"] is False
    assert config["agent"]["code_exec_image"] == "ai-agent-python:local"
    assert config["agent"]["skills_dir"] == "resources/skills"

## 13. 確認コマンド

uv run ruff check .
uv run mypy .
uv run pytest
npm --prefix src/frontend/web run build
docker compose config
docker compose up -d --build
docker compose ps
curl http://127.0.0.1:8000/healthz
curl http://127.0.0.1:5173/
