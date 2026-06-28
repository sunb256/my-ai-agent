
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

