# my-ai-agent

LiteLLM を使った最小の AI エージェント実装です。`src/main.py` から OpenAI 互換 API に接続して、通常応答とツール呼び出しを試せます。

## 設定

API キーは `.env` に保存します。このファイルは Git 管理しません。

```env
OPENAI_API_KEY=your-api-key
```

モデル名や OpenAI 互換 API の URL は `src/config.yml` に設定します。

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

## 実行

1 回だけ質問する場合:

```bash
uv run src/main.py "短く自己紹介して"
```

ツール呼び出しを試す場合:

```bash
uv run src/main.py "3 + 5 を計算して"
uv run src/main.py "今の時刻を教えて"
```

引数なしで起動すると、簡易対話モードになります。

```bash
uv run src/main.py
```

## オプション

```bash
uv run src/main.py --help
uv run src/main.py --config src/config.yml --max-steps 8 "質問"
```
