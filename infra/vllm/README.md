# vLLM + Prometheus Docker Compose

vLLMのOpenAI互換APIと`/metrics`を起動し、Prometheusから5秒ごとに取得する構成です。

## 構成

```text
FastAPI / Agent
    |
    | OpenAI互換API
    v
vLLM :8000
    |
    | /metrics
    v
Prometheus :9090
```

vLLMとPrometheusは同じDockerネットワークに置かれます。既定ではホスト側のポートを
`127.0.0.1`にだけ公開します。

## 前提

- Linux、またはGPU対応済みのWSL2
- NVIDIAドライバー
- NVIDIA Container Toolkit
- Docker Engine
- Docker Compose 2.30以降

GPUをDockerから確認します。

```bash
nvidia-smi
docker run --rm --gpus all nvidia/cuda:12.9.0-base-ubuntu22.04 nvidia-smi
docker compose version
```

## 起動

```bash
cp .env.example .env
```

`.env`の最低限、次を変更します。

```dotenv
VLLM_MODEL=Qwen/Qwen3-0.6B
VLLM_SERVED_MODEL_NAME=local-model
VLLM_API_KEY=十分に長いランダム文字列
```

起動します。

```bash
docker compose up -d
docker compose logs -f vllm
```

初回はモデルのダウンロードとロードに時間がかかります。状態確認:

```bash
docker compose ps
curl -f http://127.0.0.1:8000/health
```

## OpenAI互換APIの確認

モデル一覧:

```bash
curl http://127.0.0.1:8000/v1/models   -H "Authorization: Bearer ${VLLM_API_KEY}"
```

Chat Completions:

```bash
curl http://127.0.0.1:8000/v1/chat/completions   -H "Authorization: Bearer ${VLLM_API_KEY}"   -H "Content-Type: application/json"   -d '{
    "model": "local-model",
    "messages": [
      {"role": "user", "content": "こんにちは。短く自己紹介してください。"}
    ],
    "temperature": 0.2,
    "max_tokens": 128
  }'
```

シェルで`.env`を読み込む場合:

```bash
set -a
source .env
set +a
```

## Prometheusの確認

vLLMの生メトリクス:

```bash
curl -s http://127.0.0.1:8000/metrics | grep '^vllm:' | head
```

Prometheus UI:

```text
http://127.0.0.1:9090
```

Targets画面:

```text
http://127.0.0.1:9090/targets
```

`vllm`ジョブが`UP`なら取得できています。

## 最初に見るPromQL

実行中リクエスト数:

```promql
vllm:num_requests_running
```

待機中リクエスト数:

```promql
vllm:num_requests_waiting
```

KV Cache使用率:

```promql
vllm:kv_cache_usage_perc
```

直近5分のPrefix Cacheヒット率:

```promql
sum(rate(vllm:prefix_cache_hits[5m]))
/
clamp_min(sum(rate(vllm:prefix_cache_queries[5m])), 1)
```

入力トークン処理速度:

```promql
sum(rate(vllm:prompt_tokens_total[5m]))
```

生成トークン速度:

```promql
sum(rate(vllm:generation_tokens_total[5m]))
```

P95 TTFT:

```promql
histogram_quantile(
  0.95,
  sum by (le) (
    rate(vllm:time_to_first_token_seconds_bucket[5m])
  )
)
```

P95キュー時間:

```promql
histogram_quantile(
  0.95,
  sum by (le) (
    rate(vllm:request_queue_time_seconds_bucket[5m])
  )
)
```

## 主要設定

### `VLLM_GPU_MEMORY_UTILIZATION`

モデルの重み、ワークスペース、KV Cacheを含むvLLMインスタンス全体のGPUメモリ使用割合です。
最初は`0.90`を推奨します。OOMが出る場合は`0.85`などへ下げます。

### `VLLM_MAX_MODEL_LEN`

最大コンテキスト長です。大きくすると1リクエストが使える履歴は増えますが、
KV Cache容量と同時実行余力が減ります。24GB GPUなら最初は`8192`程度から調整します。

### `VLLM_MAX_NUM_SEQS`

同時に処理する最大シーケンス数です。空欄ならvLLMの自動・既定設定を使います。
GPUメモリ不足や応答遅延を実測した後に設定してください。

### `VLLM_MAX_NUM_BATCHED_TOKENS`

1回のスケジューライテレーションで処理する最大トークン数です。
初期段階では空欄にして、TTFTとスループットを測定してから調整します。

### `VLLM_ENABLE_PREFIX_CACHING`

同じSystem Prompt、Tool定義、会話履歴Prefixの計算結果を再利用します。
会話内容の正しさを保証する保存領域ではないため、Agent側は毎回必要な履歴を送信します。

## 複数GPU

2GPUをTensor Parallelで使う例:

```dotenv
VLLM_DEVICE_IDS=0,1
VLLM_TENSOR_PARALLEL_SIZE=2
```

変更後:

```bash
docker compose up -d --force-recreate vllm
```

## モデル変更

```dotenv
VLLM_MODEL=組織名/モデル名
VLLM_SERVED_MODEL_NAME=アプリから指定するモデル名
VLLM_QUANTIZATION=
```

モデルを変更するとvLLMは再起動し、以前のKV Cacheは失われます。

## Prometheus保持期間

既定値:

```dotenv
PROMETHEUS_RETENTION_TIME=15d
PROMETHEUS_RETENTION_SIZE=10GB
```

期間またはサイズの上限に達した古いデータから削除されます。

## 停止・削除

コンテナを停止:

```bash
docker compose down
```

Prometheusの保存データも削除:

```bash
docker compose down -v
```

Hugging Faceモデルキャッシュは`HF_CACHE_DIR`に残ります。

## 公開範囲について

既定ではvLLMとPrometheusを`127.0.0.1`にだけ公開します。LANへ直接公開する場合でも、
vLLMの推論API、`/metrics`、`/health`などを無制限に外部公開せず、FastAPIまたは
リバースプロキシで認証・アクセス制限してください。
