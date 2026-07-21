vLLM＋PrometheusをDocker Composeで起動できる構成を作成しました。

[一式をダウンロード](sandbox:/mnt/data/vllm-prometheus-compose.zip)

個別ファイル:

* [compose.yaml](sandbox:/mnt/data/vllm-prometheus-compose/compose.yaml)
* [.env.example](sandbox:/mnt/data/vllm-prometheus-compose/.env.example)
* [README.md](sandbox:/mnt/data/vllm-prometheus-compose/README.md)
* [prometheus.yml](sandbox:/mnt/data/vllm-prometheus-compose/prometheus/prometheus.yml)
* [vLLM起動スクリプト](sandbox:/mnt/data/vllm-prometheus-compose/scripts/start-vllm.sh)

## 構成

```text
FastAPI / Agent
    │ OpenAI互換API
    ▼
vLLM :8000
    │ /metrics
    ▼
Prometheus :9090
```

vLLMは公式の`vllm/vllm-openai`イメージを使用し、`/metrics`は追加のExporterなしでPrometheus形式のメトリクスを公開します。([vLLM][1])

現在のバージョンとして、以下を固定しています。

```dotenv
VLLM_IMAGE=vllm/vllm-openai:v0.25.0
PROMETHEUS_IMAGE=prom/prometheus:v3.13.1
```

vLLM 0.25.0は2026年7月11日、Prometheus 3.13.1は2026年7月10日のリリースです。([GitHub][2])

## 起動方法

```bash
unzip vllm-prometheus-compose.zip
cd vllm-prometheus-compose

cp .env.example .env
```

`.env`のAPIキーを変更します。

```dotenv
VLLM_API_KEY=十分に長いランダム文字列
```

起動します。

```bash
docker compose up -d
docker compose logs -f vllm
```

初回はモデルのダウンロードとGPUへのロードが行われます。

```bash
docker compose ps

curl -f http://127.0.0.1:8000/health
curl -s http://127.0.0.1:8000/metrics | grep '^vllm:' | head
```

Prometheusは次で確認できます。

```text
http://127.0.0.1:9090/targets
```

`vllm`が`UP`なら、メトリクスを取得できています。

## 主な設定

ほぼすべてのvLLM設定を`.env`にまとめています。

```dotenv
VLLM_MODEL=Qwen/Qwen3-0.6B
VLLM_SERVED_MODEL_NAME=local-model

VLLM_DEVICE_IDS=0
VLLM_TENSOR_PARALLEL_SIZE=1
VLLM_GPU_MEMORY_UTILIZATION=0.90

VLLM_MAX_MODEL_LEN=8192
VLLM_MAX_NUM_SEQS=
VLLM_MAX_NUM_BATCHED_TOKENS=

VLLM_ENABLE_PREFIX_CACHING=true
VLLM_KV_CACHE_DTYPE=auto
VLLM_QUANTIZATION=
```

`VLLM_MAX_NUM_SEQS`と`VLLM_MAX_NUM_BATCHED_TOKENS`は、最初は空欄にしてvLLMの設定に任せます。負荷試験後に必要な場合だけ調整する方針です。これらの設定とPrefix Cache、GPUメモリ使用率は現在の`vllm serve`で正式にサポートされています。([vLLM][3])

複数GPUの場合は次のようにします。

```dotenv
VLLM_DEVICE_IDS=0,1
VLLM_TENSOR_PARALLEL_SIZE=2
```

Docker Composeの`gpus: all`を使用しているため、Docker Compose 2.30以降が必要です。([Docker Documentation][4])

## Prometheusの保持設定

```dotenv
PROMETHEUS_RETENTION_TIME=15d
PROMETHEUS_RETENTION_SIZE=10GB
```

Prometheusの取得間隔は、現在は`prometheus/prometheus.yml`で5秒に設定しています。

```yaml
global:
  scrape_interval: 5s
  scrape_timeout: 4s
```

Prometheusは`static_configs`でDockerネットワーク内の`vllm:8000`を取得します。([Prometheus][5])

## Prefix Cacheヒット率

Prometheus画面に次を入力します。

```promql
sum(rate(vllm:prefix_cache_hits[5m]))
/
clamp_min(sum(rate(vllm:prefix_cache_queries[5m])), 1)
```

KV Cache使用率:

```promql
vllm:kv_cache_usage_perc
```

待機リクエスト数:

```promql
vllm:num_requests_waiting
```

vLLMは、実行中リクエスト、KV Cache使用率、Prefix Cache照会数・ヒット数、TTFT、キュー時間などを標準メトリクスとして公開しています。([vLLM][6])

YAMLとシェルスクリプトの構文検証、ZIPの整合性確認までは実施済みです。この実行環境にはDockerとGPUがないため、実際のモデルロードまでは実行していません。

[1]: https://docs.vllm.ai/en/stable/deployment/docker/?utm_source=chatgpt.com "Using Docker"
[2]: https://github.com/vllm-project/vllm/releases?utm_source=chatgpt.com "Releases · vllm-project/vllm"
[3]: https://docs.vllm.ai/en/stable/cli/serve/ "vllm serve - vLLM"
[4]: https://docs.docker.com/reference/compose-file/services/?utm_source=chatgpt.com "Define services in Docker Compose | Docker Docs"
[5]: https://prometheus.io/docs/prometheus/latest/configuration/configuration/?utm_source=chatgpt.com "Configuration"
[6]: https://docs.vllm.ai/en/stable/design/metrics/ "Metrics - vLLM"
