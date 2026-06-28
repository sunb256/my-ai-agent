
backend に /agent を実装

## Step 1: 固定文を返す AG UI endpoint を作る

まず LLM や既存 agent にはつながず、/agent が AG UI event stream を返すことだけ確認します。

必要な Python package:

```bash
cd <repo-root>
uv add ag-ui-protocol
```

backend に /agent を追加

src/api/main.py
```python
from fastapi import Request
from fastapi.responses import StreamingResponse

from ag_ui.core import (
    EventType,
    RunAgentInput,
    RunStartedEvent,
    RunFinishedEvent,
    TextMessageStartEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
)
from ag_ui.encoder import EventEncoder

# :

@app.post("/agent")
async def agent_endpoint(req: Request):
    body = await req.json()
    input_ = RunAgentInput.model_validate(body)

    enc = EventEncoder(accept=req.headers.get("accept"))

    async def event_stream():
        tid = input_.thread_id
        rid = input_.run_id
        mid = "msg_test" 

        yield enc.encode(RunStartedEvent(type=EventType.RUN_STARTED, thread_id=tid, run_id=rid))
        yield enc.encode(TextMessageStartEvent(type=EventType.TEXT_MESSAGE_START, message_id=mid, role="assistant"))

        for char in "AG UI backend connected":
            yield enc.encode(TextMessageContentEvent(type=EventType.TEXT_MESSAGE_CONTENT, message_id=mid, delta=char))

        yield enc.encode(TextMessageEndEvent(type=EventType.TEXT_MESSAGE_END, message_id=mid))
        yield enc.encode(RunFinishedEvent(type=EventType.RUN_FINISHED, thread_id=tid, run_id=rid))
    
    return StreamingResponse(event_stream(), media_type="text/event-stream")
```

これで frontend から送信したときに、まず固定文が表示される

## Step 2: 既存 Agent と接続する

固定文が出た後に、今の AgentApiService 相当を AG UI event に変換します。

```
AgentResult output
  -> TEXT_MESSAGE_START
  -> TEXT_MESSAGE_CONTENT
  -> TEXT_MESSAGE_END
  -> RUN_FINISHED

AgentResult pending
  -> TOOL_CALL_START / TOOL_CALL_ARGS / interrupt 系イベント
  -> HITL UI
  -> resume
```

HITL は少し慎重に設計した方がよいので、まずは 固定文の /agent が 
frontend に表示されるか を確認するのが次の最短ステップです。

今やること

1. uv add ag-ui-protocol
2. src/api/main.py に /agent の固定応答 endpoint を追加
3. backend 起動

uv run uvicorn api.main:app --reload

4. frontend 起動

cd src/frontend/web
npm run dev

5. assistant-ui から送信して、AG UI backend connected が表示されるか確認

これが通れば、frontend と backend の AG UI 接続は成立しています。