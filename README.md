# my-ai-agent

LiteLLM を使った最小の AI エージェント実装です。  
`src/agent/main.py` から OpenAI 互換 API に接続して、通常応答とツール呼び出しを試せます。

## 設定

API キーは `.env` に保存します。このファイルは Git 管理しません。

```env
OPENAI_API_KEY=your-api-key
```

Ollama でローカル実行する場合、API キーは Ollama 側では使われませんが、このサンプル実装では `OPENAI_API_KEY` を必須チェックしているため、ダミー値を入れてください。

```env
OPENAI_API_KEY=ollama
```

モデル名や OpenAI 互換 API の URL は `src/agent/config/config.yml` に設定します。

```yaml
llm:
  model: "openai/your-model-name"
  base_url: "https://your-openai-compatible-endpoint/v1"
  temperature: 0.2

agent:
  name: "sample-agent"
  instructions: |
    あなたは簡潔に回答するAIアシスタントです。
    必要なら利用可能なツールを使ってください。
  max_steps: 5
```

Ollama の OpenAI 互換 API を使う場合は、`base_url` を `http://localhost:11434/v1` にします。  
`model` には `ollama list` で表示されるモデル名に `openai/` を付けます。

例:

```yaml
llm:
  model: "openai/llama3.2"
  base_url: "http://localhost:11434/v1"
  temperature: 0.2
```

`ollama list` で `qwen2.5:7b` が表示される場合は、次のように指定します。

```yaml
llm:
  model: "openai/qwen2.5:7b"
  base_url: "http://localhost:11434/v1"
  temperature: 0.2
```

## Ollama での動作テスト


```bash
ollama pull <model_name>
ollama list
ollama ps
```

`.env` を作成します。

```env
OPENAI_API_KEY=ollama
```

`src/agent/config/config.yml` を Ollama 向けに設定します。

```yaml
llm:
  model: "openai/llama3.2"
  base_url: "http://localhost:11434/v1"
  temperature: 0.2

agent:
  name: "sample-agent"
  instructions: |
    あなたは簡潔に回答するAIアシスタントです。
    必要なら利用可能なツールを使ってください。
  max_steps: 5
```

まずは Ollama の OpenAI 互換 API に直接疎通できるか確認します。

```bash
curl http://localhost:11434/v1/models
```

モデル一覧が JSON で返れば、Ollama 側の準備はできています。

## 実行

1 回だけ質問する場合:

```bash
uv run my-ai-agent "短く自己紹介して"
```

ツール呼び出しを試す場合:

```bash
uv run my-ai-agent "3 + 5 を計算して"
uv run my-ai-agent "今の時刻を教えて"
```

`3 + 5` のような計算では、モデルがツール呼び出しを選ぶと `add_numbers` が使われます。  
挙動を見たい場合は `--verbose` を付けます。

```bash
uv run my-ai-agent --verbose "3 + 5 を計算して"
```

引数なしで起動すると、簡易対話モードになります。

```bash
uv run my-ai-agent
```

終了する場合は空行を送るか、Ctrl-D を押します。

## オプション

```bash
uv run my-ai-agent --help
uv run my-ai-agent --config src/agent/config/config.yml --max-steps 8 "質問"
```

## API

FastAPI で agent を stream 形式で呼び出す場合:

```bash
uv run uvicorn api.main:app --reload
```

疎通確認:

```bash
curl http://127.0.0.1:8000/healthz
```

stream 呼び出し:

```bash
curl -N -X POST 'http://127.0.0.1:8000/api/v1/chat?session_id=test-session' \
  -H "content-type: application/json" \
  -d '{"prompt":"短く自己紹介して"}'
```

## トラブルシュート

`Missing required config value: llm.model` が出る場合:  
`src/agent/config/config.yml` の `llm.model` が空です。Ollama の場合は `openai/llama3.2` のように指定してください。

`Set OPENAI_API_KEY in .env or your shell environment.` が出る場合:  
`.env` に `OPENAI_API_KEY=ollama` を設定してください。

`Connection refused` や接続エラーが出る場合:  
Ollama サーバーが起動しているか確認してください。

```bash
ollama serve
curl http://localhost:11434/v1/models
```

`model not found` が出る場合:  
指定したモデルが Ollama に存在しません。`ollama list` でモデル名を確認するか、`ollama pull` で取得してください。
