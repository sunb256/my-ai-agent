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

  if docker build -t "${image}" -f infra/sandbox/Dockerfile infra/sandbox \
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
