結論として、**FE は薄く、BE が AG-UI の event stream を返す構成**になります。新規で作るなら、最初は **`POST /agent` だけ**でよいです。assistant-ui の AG-UI quickstart でも、FE は `HttpAgent` を AG-UI endpoint に向けて `useAgUiRuntime` に渡す構成です。([assistant-ui][1])

全体像はこうです。

```text
React / assistant-ui
  MyRuntimeProvider
    └─ HttpAgent("http://localhost:8000/agent")
          ↓ POST
FastAPI /agent
  └─ RunAgentInput を受け取る
  └─ 自作 Agent を実行する
  └─ AG-UI Event を SSE で返す
```

AG-UI の Python SDK では、HTTP API の POST body は `RunAgentInput` で、`thread_id`、`run_id`、`messages`、`tools`、`state` などを持ちます。([AG-UI][2]) また、AG-UI は `RUN_STARTED`、`TEXT_MESSAGE_*`、`TOOL_CALL_*`、`STATE_*`、`RUN_FINISHED` などの event を stream する設計です。([AG-UI][3])

## FE 側

install はまずこれです。

```bash
pnpm add @assistant-ui/react @assistant-ui/react-ag-ui @ag-ui/client
```

`src/MyRuntimeProvider.tsx`

```tsx
import { useMemo } from "react";
import { AssistantRuntimeProvider } from "@assistant-ui/react";
import { useAgUiRuntime } from "@assistant-ui/react-ag-ui";
import { HttpAgent } from "@ag-ui/client";

type Props = {
  children: React.ReactNode;
};

export function MyRuntimeProvider({ children }: Props) {
  const agent = useMemo(() => {
    return new HttpAgent({
      url: "http://localhost:8000/agent",
    });
  }, []);

  const runtime = useAgUiRuntime({
    agent,
    onError: (error) => {
      console.error(error);
    },
  });

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      {children}
    </AssistantRuntimeProvider>
  );
}
```

`src/App.tsx`

```tsx
import { MyRuntimeProvider } from "./MyRuntimeProvider";
import { Thread } from "./components/assistant-ui/thread";

export default function App() {
  return (
    <MyRuntimeProvider>
      <div style={{ height: "100vh" }}>
        <Thread />
      </div>
    </MyRuntimeProvider>
  );
}
```

FE 側はこれくらいでよいです。`HttpAgent` が `/agent` に AG-UI request を投げ、`useAgUiRuntime` が返ってきた AG-UI events を assistant-ui の message / tool call / state に変換します。assistant-ui の docs でも、incoming events の `TEXT_MESSAGE_*`、`TOOL_CALL_*`、`STATE_SNAPSHOT` などを runtime が assistant-ui messages に parse すると説明されています。([assistant-ui][1])

## BE 側

install はこうです。

```bash
uv add fastapi uvicorn ag-ui-protocol litellm
```

まずは **LLM を呼ばずに固定文を streaming する最小実装**から作ると分かりやすいです。

`app/main.py`

```py
import asyncio
import uuid
from collections.abc import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from ag_ui.core import (
    EventType,
    RunAgentInput,
    RunStartedEvent,
    RunFinishedEvent,
    RunErrorEvent,
    TextMessageStartEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    StateSnapshotEvent,
)
from ag_ui.encoder import EventEncoder

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5555"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def last_user_text(input_: RunAgentInput) -> str:
    for message in reversed(input_.messages):
        if getattr(message, "role", None) != "user":
            continue

        content = getattr(message, "content", "")

        if isinstance(content, str):
            return content

        # multimodal content の場合
        texts = []
        for part in content:
            if getattr(part, "type", None) == "text":
                texts.append(part.text)
        return "\n".join(texts)

    return ""


async def run_agent(input_: RunAgentInput) -> AsyncIterator[object]:
    thread_id = input_.thread_id
    run_id = input_.run_id
    message_id = f"msg_{uuid.uuid4().hex}"

    yield RunStartedEvent(
        type=EventType.RUN_STARTED,
        thread_id=thread_id,
        run_id=run_id,
    )

    yield StateSnapshotEvent(
        type=EventType.STATE_SNAPSHOT,
        snapshot={
            "status": "running",
            "current_step": "answering",
        },
    )

    yield TextMessageStartEvent(
        type=EventType.TEXT_MESSAGE_START,
        message_id=message_id,
        role="assistant",
    )

    user_text = last_user_text(input_)
    response_text = f"受け取りました: {user_text}"

    for char in response_text:
        yield TextMessageContentEvent(
            type=EventType.TEXT_MESSAGE_CONTENT,
            message_id=message_id,
            delta=char,
        )
        await asyncio.sleep(0.01)

    yield TextMessageEndEvent(
        type=EventType.TEXT_MESSAGE_END,
        message_id=message_id,
    )

    yield StateSnapshotEvent(
        type=EventType.STATE_SNAPSHOT,
        snapshot={
            "status": "completed",
            "current_step": "done",
        },
    )

    yield RunFinishedEvent(
        type=EventType.RUN_FINISHED,
        thread_id=thread_id,
        run_id=run_id,
    )


@app.post("/agent")
async def agent_endpoint(request: Request):
    body = await request.json()
    input_ = RunAgentInput.model_validate(body)

    encoder = EventEncoder(
        accept=request.headers.get("accept"),
    )

    async def event_stream():
        try:
            async for event in run_agent(input_):
                yield encoder.encode(event)

        except Exception as e:
            error_event = RunErrorEvent(
                type=EventType.RUN_ERROR,
                message=str(e),
                code="agent_error",
            )
            yield encoder.encode(error_event)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
    )
```

起動はこれです。

```bash
uv run uvicorn app.main:app --reload --port 8000
```

`EventEncoder` は AG-UI event object を HTTP で送れる文字列に変換する役割で、現状の実装では SSE 形式に encode されます。公式例でも `TextMessageContentEvent` を encode すると `data: {...}\n\n` のような SSE 文字列になると説明されています。([AG-UI][4])

## LiteLLM をつなぐ場合

固定文の代わりに LiteLLM を streaming するなら、`run_agent()` の中で `acompletion(..., stream=True)` を読み、delta ごとに `TextMessageContentEvent` を出します。

```py
import os
from litellm import acompletion

async def run_agent(input_: RunAgentInput) -> AsyncIterator[object]:
    thread_id = input_.thread_id
    run_id = input_.run_id
    message_id = f"msg_{uuid.uuid4().hex}"

    yield RunStartedEvent(
        type=EventType.RUN_STARTED,
        thread_id=thread_id,
        run_id=run_id,
    )

    yield TextMessageStartEvent(
        type=EventType.TEXT_MESSAGE_START,
        message_id=message_id,
        role="assistant",
    )

    messages = [
        {
            "role": getattr(m, "role"),
            "content": getattr(m, "content", ""),
        }
        for m in input_.messages
        if getattr(m, "role", None) in {"system", "user", "assistant"}
    ]

    stream = await acompletion(
        model=os.environ.get("LLM_MODEL", "gpt-4o-mini"),
        messages=messages,
        stream=True,
    )

    async for chunk in stream:
        delta = chunk.choices[0].delta.content
        if not delta:
            continue

        yield TextMessageContentEvent(
            type=EventType.TEXT_MESSAGE_CONTENT,
            message_id=message_id,
            delta=delta,
        )

    yield TextMessageEndEvent(
        type=EventType.TEXT_MESSAGE_END,
        message_id=message_id,
    )

    yield RunFinishedEvent(
        type=EventType.RUN_FINISHED,
        thread_id=thread_id,
        run_id=run_id,
    )
```

## tool call を出す場合

tool call は `TOOL_CALL_START`、`TOOL_CALL_ARGS`、`TOOL_CALL_END`、`TOOL_CALL_RESULT` の流れになります。AG-UI の Python SDK でも tool call lifecycle event が用意されています。([AG-UI][3])

イメージはこうです。

```py
import json

from ag_ui.core import (
    ToolCallStartEvent,
    ToolCallArgsEvent,
    ToolCallEndEvent,
    ToolCallResultEvent,
)

async def emit_tool_call_example(parent_message_id: str):
    tool_call_id = f"tool_{uuid.uuid4().hex}"
    tool_result_message_id = f"msg_{uuid.uuid4().hex}"

    yield ToolCallStartEvent(
        type=EventType.TOOL_CALL_START,
        tool_call_id=tool_call_id,
        tool_call_name="search_documents",
        parent_message_id=parent_message_id,
    )

    yield ToolCallArgsEvent(
        type=EventType.TOOL_CALL_ARGS,
        tool_call_id=tool_call_id,
        delta=json.dumps({"query": "品質不良 レポート"}, ensure_ascii=False),
    )

    yield ToolCallEndEvent(
        type=EventType.TOOL_CALL_END,
        tool_call_id=tool_call_id,
    )

    # ここで実際の tool を実行する
    result = "関連ドキュメントを3件見つけました。"

    yield ToolCallResultEvent(
        type=EventType.TOOL_CALL_RESULT,
        message_id=tool_result_message_id,
        tool_call_id=tool_call_id,
        content=result,
        role="tool",
    )
```

## 自作 Agent Core とつなぐ形

あなたの既存・予定の設計に合わせるなら、BE はこう分けるのがよいです。

```text
agent-core/
  context.py        # ExecutionContext
  events.py         # 自前 AgentEvent
  tools.py          # Tool / ToolCall / ToolResult
  runner.py         # AgentRunner

agent-api/
  main.py           # FastAPI
  agui_adapter.py   # RunAgentInput <-> 自前 Request, 自前 Event <-> AG-UI Event
```

`agent-core` は AG-UI に直接依存させない方がよいです。AG-UI 依存は `agent-api/agui_adapter.py` に閉じ込めます。

```py
# agent_api/agui_adapter.py

from ag_ui.core import (
    EventType,
    TextMessageStartEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    StateSnapshotEvent,
)

def convert_agent_event(event):
    if event.type == "text_start":
        return TextMessageStartEvent(
            type=EventType.TEXT_MESSAGE_START,
            message_id=event.message_id,
            role="assistant",
        )

    if event.type == "text_delta":
        return TextMessageContentEvent(
            type=EventType.TEXT_MESSAGE_CONTENT,
            message_id=event.message_id,
            delta=event.text,
        )

    if event.type == "text_end":
        return TextMessageEndEvent(
            type=EventType.TEXT_MESSAGE_END,
            message_id=event.message_id,
        )

    if event.type == "state":
        return StateSnapshotEvent(
            type=EventType.STATE_SNAPSHOT,
            snapshot=event.state,
        )

    raise ValueError(f"unsupported event type: {event.type}")
```

すると FastAPI 側はこうなります。

```py
async def run_agent(input_: RunAgentInput) -> AsyncIterator[object]:
    runner = AgentRunner()

    yield RunStartedEvent(
        type=EventType.RUN_STARTED,
        thread_id=input_.thread_id,
        run_id=input_.run_id,
    )

    async for agent_event in runner.run_stream(input_):
        yield convert_agent_event(agent_event)

    yield RunFinishedEvent(
        type=EventType.RUN_FINISHED,
        thread_id=input_.thread_id,
        run_id=input_.run_id,
    )
```

この形にしておくと、将来 AG-UI 以外の API を作る場合も `agent-core` はそのまま使えます。変わるのは外側の adapter だけです。

最初の実装単位としては、**FE は `HttpAgent + useAgUiRuntime`、BE は `POST /agent + StreamingResponse + EventEncoder`**。そのあとに LiteLLM、tool call、HITL、状態表示を足していく構成が一番見通しがよいです。

[1]: https://www.assistant-ui.com/docs/runtimes/ag-ui/quickstart "Quickstart — assistant-ui"
[2]: https://docs.ag-ui.com/sdk/python/core/types "Types - Agent User Interaction Protocol"
[3]: https://docs.ag-ui.com/sdk/python/core/events "Events - Agent User Interaction Protocol"
[4]: https://docs.ag-ui.com/sdk/python/encoder/overview "Overview - Agent User Interaction Protocol"
