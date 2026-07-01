
## Step 2: 既存 Agent と接続する

src/api/service.py に実装を描く形にすればいいです。実装はこちらでします。詳細を書いて

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

service.py の責務

RunAgentInput
  -> 通常実行 or resume 実行を判定
  -> Agent.run() を呼ぶ
  -> AgentResult を AG UI event stream に変換


```python
import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

from ag_ui.core import (
    EventType,
    Interrupt,
    RunAgentInput,
    RunErrorEvent,
    RunFinishedEvent,
    RunFinishedInterruptOutcome,
    RunFinishedSuccessOutcome,
    RunStartedEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    TextMessageStartEvent,
)
from ag_ui.encoder import EventEncoder

from agent.core.agent import Agent
from agent.core.model.context import AgentResult, PendingToolCall, ToolConfirm


class AgentApiService:
    def __init__(self, agent: Agent):
        self._agent = agent

    async def stream_agent(
        self,
        input_: RunAgentInput,
        accept: str | None,
    ) -> AsyncIterator[str]:
        encoder = EventEncoder(accept=accept)

        yield encoder.encode(
            RunStartedEvent(
                type=EventType.RUN_STARTED,
                thread_id=input_.thread_id,
                run_id=input_.run_id,
            )
        )

        try:
            result = await self._run_agent(input_)

            async for chunk in self._agent_result_to_events(
                encoder=encoder,
                input_=input_,
                result=result,
            ):
                yield chunk

        except Exception as error:
            yield encoder.encode(
                RunErrorEvent(
                    type=EventType.RUN_ERROR,
                    message=str(error),
                    code="agent_error",
                )
            )

            yield encoder.encode(
                RunFinishedEvent(
                    type=EventType.RUN_FINISHED,
                    thread_id=input_.thread_id,
                    run_id=input_.run_id,
                )
            )

    async def _run_agent(self, input_: RunAgentInput) -> AgentResult:
        if input_.resume:
            confirms = self._resume_to_confirms(input_.resume)
            return await self._agent.run(
                prompt="",
                session_id=input_.thread_id,
                confirm=confirms,
            )

        prompt = self._last_user_text(input_)
        if not prompt:
            raise ValueError("No user message found.")

        return await self._agent.run(
            prompt=prompt,
            session_id=input_.thread_id,
        )
  ```

  AgentResult から AG UI event への変換

```python
      async def _agent_result_to_events(
          self,
          encoder: EventEncoder,
          input_: RunAgentInput,
          result: AgentResult,
      ) -> AsyncIterator[str]:
          if result.status == "pending":
              interrupts = self._pending_to_interrupts(
                  pending_tc=result.pending_tc,
                  session_id=input_.thread_id,
                  agent_run_id=result.ctx.exec_id,
              )

              yield encoder.encode(
                  RunFinishedEvent(
                      type=EventType.RUN_FINISHED,
                      thread_id=input_.thread_id,
                      run_id=input_.run_id,
                      outcome=RunFinishedInterruptOutcome(
                          interrupts=interrupts,
                      ),
                  )
              )
              return

          if result.output is not None:
              text = self._output_text(result.output)

              async for chunk in self._text_events(
                  encoder=encoder,
                  text=text,
              ):
                  yield chunk

              yield encoder.encode(
                  RunFinishedEvent(
                      type=EventType.RUN_FINISHED,
                      thread_id=input_.thread_id,
                      run_id=input_.run_id,
                      outcome=RunFinishedSuccessOutcome(),
                  )
              )
              return

          raise RuntimeError("Agent finished without output.")
```

## text event helper

最初は token streaming ではなく、Agent 完了後に文字単位で流せば十分です。
```python

      async def _text_events(
          self,
          encoder: EventEncoder,
          text: str,
      ) -> AsyncIterator[str]:
          message_id = f"msg_{uuid.uuid4().hex}"

          yield encoder.encode(
              TextMessageStartEvent(
                  type=EventType.TEXT_MESSAGE_START,
                  message_id=message_id,
                  role="assistant",
              )
          )

          for char in text:
              yield encoder.encode(
                  TextMessageContentEvent(
                      type=EventType.TEXT_MESSAGE_CONTENT,
                      message_id=message_id,
                      delta=char,
                  )
              )

          yield encoder.encode(
              TextMessageEndEvent(
                  type=EventType.TEXT_MESSAGE_END,
                  message_id=message_id,
              )
          )
```

## HITL pending -> AG UI interrupt

  ここが重要です。AgentResult.pending_tc は PendingToolCall の list です。
```python
    def _pending_to_interrupts(
        self,
        pending_tc: list[PendingToolCall],
        session_id: str,
        agent_run_id: str,
    ) -> list[Interrupt]:
        interrupts: list[Interrupt] = []

        for pending in pending_tc:
            tool_call = pending.tool_call

            interrupts.append(
                Interrupt(
                    id=self._interrupt_id(tool_call.tool_call_id),
                    reason="confirmation",
                    message=pending.confirm,
                    tool_call_id=tool_call.tool_call_id,
                    metadata={
                        "tool_name": tool_call.name,
                        "args": tool_call.args,
                        "session_id": session_id,
                        "agent_run_id": agent_run_id,
                    },
                )
            )

        return interrupts
```


```python
  interrupt.id は resume 時に tool_call_id に戻せる必要があります。

      def _interrupt_id(self, tool_call_id: str) -> str:
          return f"interrupt_{tool_call_id}"

      def _tool_call_id_from_interrupt(self, interrupt_id: str) -> str:
          return interrupt_id.removeprefix("interrupt_")
```

  AG UI resume -> ToolConfirm

  AG UI runtime では、frontend が interrupt に回答すると、次回 /agent request の input_.resume に入ります。

  ResumeEntry はだいたいこの形です。

```json
  {
    "interruptId": "interrupt_xxx",
    "status": "resolved",
    "payload": {
      "approved": true,
      "modified_args": null
    }
  }
```

  変換:

```python
      def _resume_to_confirms(self, resume: list[Any]) -> list[ToolConfirm]:
          confirms: list[ToolConfirm] = []

          for entry in resume:
              tool_call_id = self._tool_call_id_from_interrupt(entry.interrupt_id)

              if entry.status == "cancelled":
                  confirms.append(
                      ToolConfirm(
                          tool_call_id=tool_call_id,
                          approved=False,
                      )
                  )
                  continue

              payload = entry.payload
              if not isinstance(payload, dict):
                  payload = {}

              approved = bool(payload.get("approved", True))
              modified_args = payload.get("modified_args")

              confirms.append(
                  ToolConfirm(
                      tool_call_id=tool_call_id,
                      approved=approved,
                      modified_args=modified_args if isinstance(modified_args, dict) else None,
                  )
              )

          return confirms
```

  最後の user text 抽出

  AG UI の RunAgentInput.messages から最後の user message を取ります。

```python
      def _last_user_text(self, input_: RunAgentInput) -> str:
          for message in reversed(input_.messages):
              if getattr(message, "role", None) != "user":
                  continue

              content = getattr(message, "content", "")

              if isinstance(content, str):
                  return content.strip()

              if isinstance(content, list):
                  texts: list[str] = []

                  for part in content:
                      if getattr(part, "type", None) == "text":
                          text = getattr(part, "text", "")
                          if isinstance(text, str):
                              texts.append(text)

                  return "\n".join(texts).strip()

          return ""

#  output text 変換

      def _output_text(self, output: Any) -> str:
          if isinstance(output, str):
              return output

          if hasattr(output, "model_dump"):
              return json.dumps(output.model_dump(), ensure_ascii=False, default=str)

          return json.dumps(output, ensure_ascii=False, default=str)
```

##  main.py 側の呼び出し

```python
  from ag_ui.core import RunAgentInput

  @app.post("/agent")
  async def agent_endpoint(req: Request):
      body = await req.json()
      input_ = RunAgentInput.model_validate(body)

      return StreamingResponse(
          _get_service().stream_agent(
              input_=input_,
              accept=req.headers.get("accept"),
          ),
          media_type="text/event-stream",
          headers={
              "Cache-Control": "no-cache",
              "Connection": "keep-alive",
              "X-Accel-Buffering": "no",
          },
      )
```


## HITL のUI実装

次にやることは frontend に useAgUiInterrupts() で承認UIを出すことです。
最小ならこれを追加すれば確認できます。

src/frontend/web/src/components/AgUiInterruptPanel.tsx
```tsx
import { useAgUiInterrupts, useAgUiSubmitInterruptResponses } from "@assistant-ui/react-ag-ui";
import { Button } from "@/components/ui/button";

export function AgUiInterruptPanel() {
  const interrupts = useAgUiInterrupts();
  const submit = useAgUiSubmitInterruptResponses();

  if (interrupts.length === 0)
    return null;

  return (
    <div className="fixed right-4 bottom-4 z-50 w-96 rounded-lg border border-border bg-background p-4 text-foreground shadow-lg">
      <div className="mb-3 text-sm font-medium">Tool confirmation</div>

      {interrupts.map((interrupt) => (
        <div key={interrupt.id}>
          <div className="mb-3 text-sm">{interrupt.message}</div>

            <div className="flex justify-end gap-2">

              <Button
                onClick={() =>
                  submit([
                    {
                      interruptId: interrupt.id,
                      status: "resolved",
                      payload: { approved: true },
                    },
                  ])
                }
              >Approve</Button>

              <Button
                variant="outline"
                onClick={() =>
                  submit([
                    {
                      interruptId: interrupt.id,
                      status: "cancelled",
                    },
                  ])
                }
              >Deny</Button>

            </div>
          </div>

      ))}
    </div>
  );
}
```

App.tsx で Thread と一緒に出します。

```tsx
import { AgUiInterruptPanel } from "@/components/AgUiInterruptPanel";

<MyRuntimeProvider>
  <main className="h-dvh">
    <Thread />
    <AgUiInterruptPanel />
  </main>
</MyRuntimeProvider>
```

これで次は、承認/拒否ボタンが出て、押すと resume 付きの /agent が再送されるはずです。



確認順

```bash
まず import と health:

uv run python -c "from api.main import app; print(app.title)"

backend 起動:

uv run uvicorn api.main:app --reload

frontend から送信:

AG UI backend connected 相当ではなく、既存 Agent の回答が表示される

HITL 確認:

delete_file ツールで /tmp/test.txt を削除して
```

期待:

Agent が pending を返す
AG UI interrupt として frontend に承認待ちが出る
承認すると input_.resume が backend に送られる
ToolConfirm に変換されて Agent.run(confirm=...) で再開する