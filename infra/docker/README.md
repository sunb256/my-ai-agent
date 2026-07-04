


## 確認

```bash
PRELOAD_SANDBOX_IMAGE=false docker compose up -d --build
docker compose ps
curl -fsS http://127.0.0.1:8000/healthz
curl -fsS http://127.0.0.1:5173/ >/tmp/my-ai-agent-frontend.html
```

## Code execution

Docker compose では `AGENT_CODE_EXEC_RUNTIME=docker` をデフォルトにしている。
Docker Desktop for Mac のコンテナ内では microsandbox の VM 起動が失敗するため、backend コンテナから Docker socket 経由で `ai-agent-python:local` を起動して `exec_python` を実行する。

CLI では `AGENT_CODE_EXEC_RUNTIME` を指定しなければ従来通り `microsandbox` を使う。
