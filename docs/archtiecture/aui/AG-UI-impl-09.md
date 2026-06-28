
## tool call 見える化

今の状態

  今のbackendは、tool callが起きても frontend にはこれしか出していません。

  RUN_FINISHED outcome=interrupt

  なので、frontendには「承認が必要」という状態は伝わりますが、tool call の経過カードは出ません。

  追加する方向

  Agent側に tool event を追加します。

  AgentStreamToolCallStart
  AgentStreamToolCallArgs
  AgentStreamToolCallEnd
  AgentStreamToolCallResult

  API側でAG UIへ変換します。

  AgentStreamToolCallStart
    -> TOOL_CALL_START

  AgentStreamToolCallArgs
    -> TOOL_CALL_ARGS

  AgentStreamToolCallEnd
    -> TOOL_CALL_END

  AgentStreamToolCallResult
    -> TOOL_CALL_RESULT

  Python SDKにはイベントクラスがあります。

  ToolCallStartEvent
  ToolCallArgsEvent
  ToolCallEndEvent
  ToolCallResultEvent

  最初にやるならこの範囲

  まずは act() の中で、tool実行前後を見える化するのがよいです。

  1. tool callを検知
  2. TOOL_CALL_START を流す
  3. args JSON を TOOL_CALL_ARGS で流す
  4. TOOL_CALL_END を流す
  5. need_confirm=True なら interrupt
  6. 承認後、tool実行結果を TOOL_CALL_RESULT で流す

  HITL時はこう見えるのが理想です。

  assistant:
    delete_file
    args: { filepath: "/tmp/agui-hitl-test.txt" }
    Tool confirmation
    [Deny] [Approve]

  難しくなる範囲

  これは後回しでよいです。

  toolの実行中ログを逐次表示
  進捗率を表示
  長時間toolの途中状態をstream
  LLMがtool argsを生成している途中を逐次表示

  ここまでやるには、tool自体が progress event を返せる設計にする必要があります。これは少し大きい変更です。

  おすすめの段階

  1. まず TOOL_CALL_START / ARGS / END だけ出す
     tool名とargsが会話内に見えるようになる

  2. 次に TOOL_CALL_RESULT を出す
     承認後や通常tool実行後の結果が見えるようになる

  3. 最後に必要なら tool進捗イベントを設計する

  なので、最初の「tool call が何をしようとしているか見える化」はそこまで難しくありません。
  既存の ToolFallback UIを使えるので、主な変更は backend の AgentStreamEvent と api/event_factory.py / api/service.py です。


--------------------------------------

実装は3層に小さく追加する形です。

agent/core/model/context.py
  AgentStreamTool* イベント型を追加

agent/core/agent.py
  tool call検知時に AgentStreamTool* を yield

api/event_factory.py
  AG UIの TOOL_CALL_* event を作るメソッド追加

api/service.py
  AgentStreamTool* -> AG UI TOOL_CALL_* に変換

まずは「tool名とargsを会話内に出す」までを入れるのがよいです。

1. context.py にイベント追加

```python
from agent.core.model.types import Event, ToolCall, ToolResult

@dataclass(frozen=True)
class AgentStreamToolCallStart:
    tool_call: ToolCall

@dataclass(frozen=True)
class AgentStreamToolCallArgs:
    tool_call: ToolCall

@dataclass(frozen=True)
class AgentStreamToolCallEnd:
    tool_call: ToolCall

@dataclass(frozen=True)
class AgentStreamToolCallResult:
    tool_result: ToolResult

AgentStreamEvent = (
    AgentStreamTextStart
    | AgentStreamTextDelta
    | AgentStreamTextEnd
    | AgentStreamToolCallStart
    | AgentStreamToolCallArgs
    | AgentStreamToolCallEnd
    | AgentStreamToolCallResult
    | AgentStreamResult
)
```

2. agent.py で tool event を yield

_step_loop() で res が確定した後、今はこうです。

```python
result = await self._apply_llm_response(ctx, res, verbose=verbose)
yield _StepComplete(result)

# ここを、tool callイベントを出せる形にします。
# まず _apply_llm_response() は「LLM responseをctxに記録するだけ」に寄せるのがきれいです。

async def _apply_llm_response(
    self,
    ctx: ExecContext,
    res: Response,
    verbose: bool,
) -> list[ToolCall]:

    if res.err_msg:
        raise RuntimeError(res.err_msg)

    if verbose:
        self._log_response(res)

    res_event = Event.new(ctx.exec_id, self.role, res.content)
    ctx.add_event(res_event)

    return [c for c in res.content if isinstance(c, ToolCall)]

# _step_loop() 側でtoolを処理します。

        tool_calls = await self._apply_llm_response(ctx, res, verbose=verbose)

        if tool_calls:
            for tool_call in tool_calls:
                yield AgentStreamToolCallStart(tool_call)
                yield AgentStreamToolCallArgs(tool_call)
                yield AgentStreamToolCallEnd(tool_call)

            before_event_cnt = len(ctx.events)
            result = await self.act(ctx, tool_calls)

            for tool_result in self._tool_results_since(ctx, before_event_cnt):
                yield AgentStreamToolCallResult(tool_result)

            if result and result.status == "pending":
                yield _StepComplete(result)
                return

            ctx.increment()
            yield _StepComplete(None)
            return

        ctx.increment()
        yield _StepComplete(None)

補助メソッドです。

    def _tool_results_since(self, ctx: ExecContext, event_count: int) -> list[ToolResult]:
        
        results: list[ToolResult] = []

        for event in ctx.events[event_count:]:
            for item in event.content:
                if isinstance(item, ToolResult):
                    results.append(item)

        return results
```

これで通常toolは、実行前にtool cardが出て、実行後にresultも入ります。
HITLの場合は act() がpendingで止まるので、まずtool cardとargsが出て、その後interrupt確認カードが出ます。


3. confirm後のtool resultも流したい場合

_process_confirm() は今 ToolResult をctxへ追加するだけです。承認後の結果も同じtool cardに入れたいなら、戻り値を list[ToolResult] にします。

```python
async def _process_confirm(
    self,
    ctx: ExecContext,
    confirms: list[ToolConfirm],
) -> list[ToolResult]:
    ...
    if results:
        event = Event.new(ctx.exec_id, self.role, results)
        ctx.add_event(event)

    return results

_run_loop() の confirm 処理をこうします。

if confirm:
    conf_rets = await self._process_confirm(ctx, confirm)

    if stream_llm:
        for tool_result in conf_rets:
            yield AgentStreamToolCallResult(tool_result)

      # :
      # :

            if ctx.final_result is None and conf_rets:
                ctx.final_result = self._tool_rets_output(conf_rets)

            # save memory
            if self.memory_manager:
                try:
                    await self.memory_manager.save(ctx)
                except Exception as e:
                    logger.warning(f"failed to save memory {e}")

    
    def _tool_rets_output(self, results: list[ToolResult]) -> str:
        
        lines: list[str] = []

        for result in results:
            content = result.content[0] if result.content else ""

            if content:
                lines.append(str(content))
            elif result.status == STR_SUCCESS:
                lines.append(f"{result.name} completed.")
            else:
                lines.append(f"{result.name} failed.")

        return "\n".join(lines)
```

これでApprove後の結果もtool cardへ反映できます。

4. event_factory.py にAG UI tool event追加

import追加:

```python
import json

from ag_ui.core import (
    ...
    ToolCallArgsEvent,
    ToolCallEndEvent,
    ToolCallResultEvent,
    ToolCallStartEvent,
)

# メソッド追加:

def tool_call_start(self, tool_call_id: str, tool_name: str) -> ToolCallStartEvent:
    return ToolCallStartEvent(
        type=EventType.TOOL_CALL_START,
        tool_call_id=tool_call_id,
        tool_call_name=tool_name,
    )

def tool_call_args(self, tool_call_id: str, args: dict) -> ToolCallArgsEvent:
    return ToolCallArgsEvent(
        type=EventType.TOOL_CALL_ARGS,
        tool_call_id=tool_call_id,
        delta=json.dumps(args, ensure_ascii=False),
    )

def tool_call_end(self, tool_call_id: str) -> ToolCallEndEvent:
    return ToolCallEndEvent(
        type=EventType.TOOL_CALL_END,
        tool_call_id=tool_call_id,
    )

def tool_call_result(
    self,
    message_id: str,
    tool_call_id: str,
    content: str,
) -> ToolCallResultEvent:
    return ToolCallResultEvent(
        type=EventType.TOOL_CALL_RESULT,
        message_id=message_id,
        tool_call_id=tool_call_id,
        content=content,
        role="tool",
    )
```

5. service.py で変換追加

import追加:

```python
AgentStreamToolCallArgs,
AgentStreamToolCallEnd,
AgentStreamToolCallResult,
AgentStreamToolCallStart,

# _emit_event() に追加:

if isinstance(event, AgentStreamToolCallStart):
    tool_call = event.tool_call
    yield enc.encode(
        ev.tool_call_start(
            tool_call_id=tool_call.tool_call_id,
            tool_name=tool_call.name,
        )
    )
    return

if isinstance(event, AgentStreamToolCallArgs):
    tool_call = event.tool_call
    yield enc.encode(
        ev.tool_call_args(
            tool_call_id=tool_call.tool_call_id,
            args=tool_call.args,
        )
    )
    return

if isinstance(event, AgentStreamToolCallEnd):
    yield enc.encode(ev.tool_call_end(event.tool_call.tool_call_id))
    return

if isinstance(event, AgentStreamToolCallResult):
    tool_result = event.tool_result
    yield enc.encode(
        ev.tool_call_result(
            message_id=f"tool_{uuid.uuid4().hex}",
            tool_call_id=tool_result.tool_call_id,
            content=json.dumps(tool_result.content, ensure_ascii=False, default=str),
        )
    )
    return
```

```python
    async def _emit_error(self, enc: EventEncoder, ev: EventFactory, state: StreamState, error: Exception) -> AsyncIterator[str]:
        
        async for chunk in self._close_text(enc, ev, state):
            yield chunk

        yield enc.encode(ev.run_error(message=str(error)))
        state.finished = True
```

見えるようになるもの

これでWeb上では、既存の ToolFallback が効いて、会話内にtool call cardが出ます。

delete_file
args: { filepath: "/tmp/agui-hitl-test.txt" }
Tool confirmation
[Deny] [Approve]

Approve後に _process_confirm() の戻り値対応まで入れれば、結果も同じ流れで表示できます。

おすすめの実装順

1. TOOL_CALL_START / ARGS / END だけ入れる
2. HITL確認カードと並んで自然に見えるか確認
3. 問題なければ TOOL_CALL_RESULT も入れる
4. 最後に承認後 result の紐付きを確認

最初からtool実行中ログや進捗率まで入れる必要はありません。まずは「どのtoolをどのargsで呼ぼうとしているか」を会話内に出すのが一番効果があります。
