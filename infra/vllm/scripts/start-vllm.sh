#!/usr/bin/env bash
set -Eeuo pipefail

log() {
  printf '[vllm-start] %s\n' "$*"
}

is_true() {
  case "${1,,}" in
    1|true|yes|on) return 0 ;;
    *) return 1 ;;
  esac
}

append_value_arg() {
  local flag="$1"
  local value="${2:-}"

  if [[ -n "$value" ]]; then
    VLLM_ARGS+=("$flag" "$value")
  fi
}

: "${VLLM_MODEL:?VLLM_MODEL is required}"
: "${VLLM_SERVED_MODEL_NAME:?VLLM_SERVED_MODEL_NAME is required}"

VLLM_ARGS=(
  serve "$VLLM_MODEL"
  --host 0.0.0.0
  --port 8000
  --served-model-name "$VLLM_SERVED_MODEL_NAME"
  --dtype "${VLLM_DTYPE:-auto}"
  --kv-cache-dtype "${VLLM_KV_CACHE_DTYPE:-auto}"
  --gpu-memory-utilization "${VLLM_GPU_MEMORY_UTILIZATION:-0.90}"
  --tensor-parallel-size "${VLLM_TENSOR_PARALLEL_SIZE:-1}"
  --disable-access-log-for-endpoints "${VLLM_DISABLE_ACCESS_LOG_FOR_ENDPOINTS:-/health,/metrics,/ping}"
)

append_value_arg --api-key "${VLLM_API_KEY:-}"
append_value_arg --device-ids "${VLLM_DEVICE_IDS:-}"
append_value_arg --max-model-len "${VLLM_MAX_MODEL_LEN:-}"
append_value_arg --max-num-seqs "${VLLM_MAX_NUM_SEQS:-}"
append_value_arg --max-num-batched-tokens "${VLLM_MAX_NUM_BATCHED_TOKENS:-}"
append_value_arg --quantization "${VLLM_QUANTIZATION:-}"

if [[ -n "${VLLM_CPU_OFFLOAD_GB:-}" && "${VLLM_CPU_OFFLOAD_GB}" != "0" ]]; then
  append_value_arg --cpu-offload-gb "$VLLM_CPU_OFFLOAD_GB"
fi

if is_true "${VLLM_ENABLE_PREFIX_CACHING:-true}"; then
  VLLM_ARGS+=(--enable-prefix-caching)
else
  VLLM_ARGS+=(--no-enable-prefix-caching)
fi

if is_true "${VLLM_TRUST_REMOTE_CODE:-false}"; then
  VLLM_ARGS+=(--trust-remote-code)
fi

if [[ -n "${VLLM_EXTRA_ARGS:-}" ]]; then
  # 引用符を含む複雑な値には対応しません。単純な空白区切りの追加引数用です。
  read -r -a EXTRA_ARGS <<< "$VLLM_EXTRA_ARGS"
  VLLM_ARGS+=("${EXTRA_ARGS[@]}")
fi

log "model=${VLLM_MODEL}"
log "served_model_name=${VLLM_SERVED_MODEL_NAME}"
log "tensor_parallel_size=${VLLM_TENSOR_PARALLEL_SIZE:-1}"
log "prefix_caching=${VLLM_ENABLE_PREFIX_CACHING:-true}"

exec vllm "${VLLM_ARGS[@]}"
