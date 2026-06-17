実装方針は、**`agent-core` は純粋な Python パッケージとして独立させ、FastAPI 側はそれを呼ぶだけの adapter にする**のが一番きれいです。

依存方向はこれです。

```txt
frontend / assistant-ui
        ↓ HTTP / SSE / WebSocket
FastAPI app
        ↓ Python import
agent-core
        ↓
LLM / tools / file handling / sandbox / config
```

逆向き、つまり **agent-core から FastAPI を import する構成は避けた方がいい**です。core が CLI、FastAPI、将来の MCP、バッチ実行などから再利用しづらくなります。

uv は workspace で複数パッケージをまとめる構成に対応しており、`pyproject.toml` に `[tool.uv.workspace]` を置いて workspace root を作る形が公式ドキュメントで説明されています。FastAPI 側は DI が使えるので、agent インスタンスを dependency として注入する形にすると結合が薄くなります。assistant-ui 側は custom backend / runtime を使って自前 backend API に接続する思想なので、この構成と相性がよいです。([Astral Docs][1])

構成例はこうです。

```txt
my-agent/
  pyproject.toml
  uv.lock

  packages/
    agent-core/
      pyproject.toml
      src/
        agent_core/
          __init__.py
          agent.py
          context.py
          events.py
          request.py
          response.py
          tools/
          llm/
          files/

  apps/
    api/
      pyproject.toml
      src/
        agent_api/
          __init__.py
          main.py
          deps.py
          schemas.py
          routes/
            chat.py
            threads.py
            health.py

    web/
      package.json
      src/
        ChatPage.tsx
```

root の `pyproject.toml` はこういうイメージです。

```toml
[project]
name = "my-agent"
version = "0.1.0"
requires-python = ">=3.14"

[tool.uv.workspace]
members = [
  "packages/agent-core",
  "apps/api",
]
```

`packages/agent-core/pyproject.toml` は core だけに必要な依存にします。

```toml
[project]
name = "agent-core"
version = "0.1.0"
requires-python = ">=3.14"
dependencies = [
  "pydantic",
  "litellm",
]
```

`apps/api/pyproject.toml` は FastAPI と `agent-core` に依存させます。

```toml
[project]
name = "agent-api"
version = "0.1.0"
requires-python = ">=3.14"
dependencies = [
  "agent-core",
  "fastapi",
  "uvicorn",
]

[tool.uv.sources]
agent-core = { workspace = true }
```

core 側は HTTP を知らない形にします。

```python
# packages/agent-core/src/agent_core/agent.py

from collections.abc import AsyncIterator
from agent_core.request import AgentRequest
from agent_core.response import AgentResponse
from agent_core.events import AgentEvent


class Agent:
    def __init__(self, *, model: str, config: dict):
        self.model = model
        self.config = config

    async def run(self, request: AgentRequest) -> AgentResponse:
        # LLM 呼び出し、tool call、file handling など
        ...

    async def stream(self, request: AgentRequest) -> AsyncIterator[AgentEvent]:
        # assistant-ui などに流すためのイベント列
        ...
```

Pydantic の request / response も core 側に置いてよいです。これは FastAPI 用ではなく、**agent-core の入出力契約**として置くイメージです。

```python
# packages/agent-core/src/agent_core/request.py

from pydantic import BaseModel


class ChatMessage(BaseModel):
    role: str
    content: str


class AgentRequest(BaseModel):
    thread_id: str | None = None
    messages: list[ChatMessage]
```

```python
# packages/agent-core/src/agent_core/response.py

from pydantic import BaseModel


class AgentResponse(BaseModel):
    content: str
    thread_id: str | None = None
```

FastAPI 側は adapter に徹します。

```python
# apps/api/src/agent_api/deps.py

from fastapi import Request
from agent_core.agent import Agent


def get_agent(request: Request) -> Agent:
    return request.app.state.agent
```

```python
# apps/api/src/agent_api/main.py

from contextlib import asynccontextmanager

from fastapi import FastAPI

from agent_core.agent import Agent
from agent_api.routes.chat import router as chat_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.agent = Agent(
        model="gpt-4.1-mini",
        config={},
    )
    yield


app = FastAPI(lifespan=lifespan)
app.include_router(chat_router, prefix="/api")
```

```python
# apps/api/src/agent_api/routes/chat.py

from fastapi import APIRouter, Depends
from agent_core.agent import Agent
from agent_core.request import AgentRequest
from agent_core.response import AgentResponse
from agent_api.deps import get_agent

router = APIRouter()


@router.post("/chat", response_model=AgentResponse)
async def chat(
    request: AgentRequest,
    agent: Agent = Depends(get_agent),
) -> AgentResponse:
    return await agent.run(request)
```

assistant-ui と結合するなら、最初は通常の `/api/chat` で十分です。ただし本格的にチャット UI として使うなら、早めに **streaming endpoint** を用意した方がよいです。assistant-ui には自前 backend とつなぐ runtime があり、Data Stream Protocol では text、tool calls、conversation context、error、attachments などの streaming を扱えると説明されています。([assistant-ui][2])

SSE で返すなら FastAPI 側はこういう adapter になります。

```python
# apps/api/src/agent_api/routes/chat.py

import json

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from agent_core.agent import Agent
from agent_core.request import AgentRequest
from agent_api.deps import get_agent

router = APIRouter()


@router.post("/chat/stream")
async def chat_stream(
    request: AgentRequest,
    agent: Agent = Depends(get_agent),
) -> StreamingResponse:
    async def event_stream():
        async for event in agent.stream(request):
            payload = event.model_dump()
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
    )
```

このとき、core 側の `AgentEvent` は UI 非依存のイベントにしておくのがよいです。

```python
# packages/agent-core/src/agent_core/events.py

from typing import Literal
from pydantic import BaseModel


class AgentEvent(BaseModel):
    type: Literal["message_delta", "tool_call", "tool_result", "done", "error"]
    data: dict
```

そのうえで FastAPI 側で assistant-ui 用の形式に変換します。

```txt
agent-core event
  ↓
agent-api adapter
  ↓
assistant-ui compatible stream
```

この変換を core に入れない方がいいです。assistant-ui をやめて別 UI にしたとき、core を変えずに済みます。

実装上の境界は、だいたいこう分けるのがよいです。

```txt
agent-core が持つもの:
- Agent / ExecutionContext
- Event / Message / ToolCall / ToolResult
- LLM client
- tool registry
- file handling
- code execution
- config loading
- agent の終了判定
- response_format の処理

agent-api が持つもの:
- FastAPI app
- route
- auth
- CORS
- request/response adapter
- SSE / WebSocket
- HTTP error 変換
- app.state での agent 初期化
- frontend 用 schema 変換

web が持つもの:
- assistant-ui の画面
- thread 表示
- tool call 表示
- file upload UI
- API 呼び出し
```

個人的には、今の段階ではこの3層がよいです。

```txt
packages/agent-core     ← 本体
apps/api                ← HTTP adapter
apps/web                ← assistant-ui / React
```

CLI も作るならこう追加します。

```txt
apps/cli
  src/
    agent_cli/
      main.py
```

CLI も `agent-core` を直接呼びます。

```txt
CLI ───────┐
           ↓
        agent-core
           ↑
FastAPI ───┘
```

これで CLI と Web/API の挙動差が出にくくなります。

注意点として、`agent-core` の中に `Request`、`Response`、`Depends`、`APIRouter`、`StreamingResponse` など FastAPI の型を入れない方がいいです。逆に FastAPI 側に agent の step 実行ロジック、tool call ループ、final_result 判定などを置くのも避けた方がいいです。FastAPI はあくまで「外から来たリクエストを core の request に変換して、core の response/event を HTTP に変換する場所」にします。

最小実装の順番はこれがよいです。

```txt
1. agent-core を package 化する
2. apps/api から agent-core を workspace dependency として import する
3. /api/chat で非 streaming の結合を作る
4. /api/chat/stream を追加する
5. assistant-ui 側を stream endpoint に接続する
6. tool call / file upload / thread 管理を順に adapter 化する
```

最初から assistant-ui の都合に core を合わせすぎない方がよいです。core のイベントモデルを先に安定させて、FastAPI 側で UI 用に変換する形が、後から CLI、Web、MCP、バッチ実行に広げやすいです。

