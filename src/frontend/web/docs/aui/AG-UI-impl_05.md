
## agent 側の stream対応

通常テキストだけ真のstreaming対応 にする実装案です。tool call / HITL は今の仕組みを維持します。

1. llm_message.py にstream eventを追加

# src/agent/core/model/llm_message.py

```python
from typing import Any, Literal

from pydantic import BaseModel, Field

from agent.core.model.tool_base import BaseTool
from agent.core.model.types import ContentItem, ToolCall


class Request(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    system_prompt: list[str] = Field(default_factory=list)
    contents: list[ContentItem] = Field(default_factory=list)
    tools: list[BaseTool] = Field(default_factory=list)
    tool_choice: str | None = None
    model_id: str | None = None

    def append_prompt(self, text: str) -> None:
        self.system_prompt.append(text)

    def get_system_prompt_msgs(self) -> list[dict[str, str]]:
        return [{"role": "system", "content": prompt} for prompt in self.system_prompt]


class Response(BaseModel):
    content: list[ContentItem] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    err_msg: str | None = None

    @property
    def tool_calls(self):
        return [tc for tc in self.content if isinstance(tc, ToolCall)]


class LLMTextDelta(BaseModel):
    type: Literal["text_delta"] = "text_delta"
    delta: str


class LLMResponseDone(BaseModel):
    type: Literal["done"] = "done"
    response: Response

LLMStreamEvent = LLMTextDelta | LLMResponseDone
```

2. Client に stream_llm() を追加

call_llm() のkwargs生成を共通化します。

# src/agent/core/llm_client.py
```python
from collections.abc import AsyncIterator
from json import JSONDecodeError

from .model.llm_message import LLMResponseDone, LLMStreamEvent, LLMTextDelta

def _build_kwargs(self, req: Request) -> dict[str, Any]:
    msgs = MessageHelper.build_msgs(req)
    tools = [tool.tool_def for tool in req.tools]

    kwargs = {
        "model": self.model,
        "messages": msgs,
        "tools": tools,
        **self.config,
    }

    if req.tool_choice is not None:
        kwargs["tool_choice"] = req.tool_choice

    return kwargs

# call_llm() はこう簡略化します。

async def call_llm(self, req: Request) -> Response:
    try:
        response = await acompletion(**self._build_kwargs(req))
        return self._parse_response(response)
    except Exception as error:
        return Response(err_msg=str(error))

# stream版を追加します。

async def stream_llm(self, req: Request) -> AsyncIterator[LLMStreamEvent]:
    try:
        kwargs = self._build_kwargs(req)
        kwargs["stream"] = True

        stream = await acompletion(**kwargs)

        text_parts: list[str] = []
        tool_buffers: dict[int, dict[str, str]] = {}

        async for chunk in stream:
            choice = chunk.choices[0]
            delta = choice.delta

            content = getattr(delta, "content", None)
            if content:
                text_parts.append(content)
                yield LLMTextDelta(delta=content)

            for item in getattr(delta, "tool_calls", None) or []:
                index = getattr(item, "index", 0) or 0
                buf = tool_buffers.setdefault(
                    index,
                    {"id": "", "name": "", "arguments": ""},
                )

                if getattr(item, "id", None):
                    buf["id"] = item.id

                fn = getattr(item, "function", None)
                if fn is not None:
                    if getattr(fn, "name", None):
                        buf["name"] += fn.name
                    if getattr(fn, "arguments", None):
                        buf["arguments"] += fn.arguments

        contents: list[Message | ToolCall | ToolResult] = []

        full_text = "".join(text_parts)
        if full_text:
            contents.append(Message(role="assistant", content=full_text))

        for index in sorted(tool_buffers):
            buf = tool_buffers[index]
            if not buf["name"]:
                continue

            try:
                args = json.loads(buf["arguments"] or "{}")
            except JSONDecodeError:
                args = {}

            contents.append(
                ToolCall(
                    tool_call_id=buf["id"] or f"call_{index}",
                    name=buf["name"],
                    args=args,
                )
            )

        yield LLMResponseDone(response=Response(content=contents))

    except Exception as error:
        yield LLMResponseDone(response=Response(err_msg=str(error)))

```

3. context.py にAgent stream eventを追加

# src/agent/core/model/context.py

```python
@dataclass(frozen=True)
class AgentStreamTextStart:
    pass

@dataclass(frozen=True)
class AgentStreamTextDelta:
    delta: str

@dataclass(frozen=True)
class AgentStreamTextEnd:
    pass

@dataclass(frozen=True)
class AgentStreamResult:
    result: AgentResult

AgentStreamEvent = (
    AgentStreamTextStart
    | AgentStreamTextDelta
    | AgentStreamTextEnd
    | AgentStreamResult
)
```


4. Agent.stream() を追加

run() は残します。Web APIだけこちらを使います。

# src/agent/core/agent.py

```python
from collections.abc import AsyncIterator

from .model.llm_message import LLMResponseDone, LLMTextDelta
from .model.context import (
    AgentStreamEvent,
    AgentStreamResult,
    AgentStreamTextDelta,
    AgentStreamTextEnd,
    AgentStreamTextStart,
)

async def stream(
    self,
    prompt,
    ctx: ExecContext | None = None,
    session_id: str | None = None,
    confirm: list[ToolConfirm] | None = None,
    verbose: bool = False,
) -> AsyncIterator[AgentStreamEvent]:

    session = None
    if session_id and self.session_manager:
        session = await self.session_manager.get_or_create(session_id)

    if ctx is None:
        ctx = ExecContext(session=session, session_manager=self.session_manager, memory_manager=self.memory_manager)

        if session:
            ctx.events = list(session.events)
            ctx.state = dict(session.state)
    
    elif ctx.memory_manager is None:
        ctx.memory_manager = self.memory_manager

    # hitl
    if confirm:
        await self._process_confirm(ctx, confirm)

    if prompt:
        ctx.add_event(Event.new_msg(ctx.exec_id, USER, prompt))

    if self.is_code_exec and \
       ctx.code_env is None:
        await self._setup_code_env(ctx)

    try:
        while ctx.is_continue(self.max_step):
            req = await self._get_request(ctx)

            res: Response | None = None

            for callback in self.before_llm_cb:
                cb_result = callback(ctx, req)
                if inspect.isawaitable(cb_result):
                    cb_result = await cb_result

                if isinstance(cb_result, Response):
                    res = cb_result
                    break

            if res is None:
                text_started = False

                async for llm_event in self.client.stream_llm(req):
                    if isinstance(llm_event, LLMTextDelta):
                        if not text_started:
                            yield AgentStreamTextStart()
                            text_started = True

                        yield AgentStreamTextDelta(llm_event.delta)

                    elif isinstance(llm_event, LLMResponseDone):
                        res = llm_event.response

                if text_started:
                    yield AgentStreamTextEnd()

            if res is None:
                raise RuntimeError("LLM stream finished without response.")

            if res.err_msg:
                raise RuntimeError(res.err_msg)

            if verbose:
                self._log_response(res)

            res_event = Event.new(ctx.exec_id, self.role, res.content)
            ctx.add_event(res_event)

            tool_calls = [c for c in res.content if isinstance(c, ToolCall)]
            if tool_calls:
                result = await self.act(ctx, tool_calls)

                if result and result.status == "pending":
                    if session and self.session_manager:
                        session.events = list(ctx.events)
                        session.state = dict(ctx.state)
                        await self.session_manager.save(session)

                    yield AgentStreamResult(result)
                    return

            ctx.increment()

            event = ctx.last_event
            if event is not None and self._is_final_response(event):
                ctx.final_result = self._get_final_result(event)
                break
        
        # save memory
        if self.memory_manager:
            try:
                await self.memory_manager.save(ctx)
            except Exception as e:
                logger.warning(f"failed to save memory {e}")

        # save session
        if session and self.session_manager:
            session.events = list(ctx.events)
            session.state = dict(ctx.state)
            await self.session_manager.save(session)

        yield AgentStreamResult(AgentResult(output=ctx.final_result, ctx=ctx))

    finally:
        if ctx.code_env is not None:
            result = ctx.code_env.kill()
            if inspect.isawaitable(result):
                await result
```

5. API側を Agent.stream() に差し替え

# src/api/service.py

```python
from agent.core.model.context import (
    AgentStreamResult,
    AgentStreamTextDelta,
    AgentStreamTextEnd,
    AgentStreamTextStart,
)

stream_agent() をこういう形にします。

async def stream_agent(
    self,
    input_: RunAgentInput,
    accept: str | None,
) -> AsyncIterator[str]:

    enc = EventEncoder(accept=accept)
    ev = EventFactory(input_)

    yield enc.encode(ev.run_started())

    message_id: str | None = None
    streamed_text = False

    try:
        async for event in self._stream_agent_events(input_):
            if isinstance(event, AgentStreamTextStart):
                message_id = f"msg_{uuid.uuid4().hex}"
                yield enc.encode(ev.text_start(message_id))
                continue

            if isinstance(event, AgentStreamTextDelta):
                if message_id is None:
                    message_id = f"msg_{uuid.uuid4().hex}"
                    yield enc.encode(ev.text_start(message_id))

                streamed_text = True
                yield enc.encode(ev.text_content(message_id, event.delta))
                continue

            if isinstance(event, AgentStreamTextEnd):
                if message_id is not None:
                    yield enc.encode(ev.text_end(message_id))
                    message_id = None
                continue

            if isinstance(event, AgentStreamResult):
                if message_id is not None:
                    yield enc.encode(ev.text_end(message_id))
                    message_id = None

                ret = event.result

                if ret.status == "pending":
                    interrupts = self._pending(
                        pending_tc=ret.pending_tc,
                        session_id=ev.thread_id,
                        agent_run_id=ret.ctx.exec_id,
                    )
                    yield enc.encode(ev.run_interrupt(interrupts))
                    return

                if streamed_text:
                    yield enc.encode(ev.run_success())
                    return

                async for chunk in self._to_events(enc=enc, ev=ev, ret=ret):
                    yield chunk
                return

    except Exception as error:
        if message_id is not None:
            yield enc.encode(ev.text_end(message_id))

        async for chunk in self._text_events(
            enc=enc,
            ev=ev,
            text=f"error occurred: {error}",
        ):
            yield chunk

        yield enc.encode(ev.run_success())


# 追加メソッドです。


async def _stream_agent_events(self, input_: RunAgentInput):
    if input_.resume:
        confirms = self._resume(input_.resume)

        async for event in self._agent.stream(
            prompt="",
            session_id=input_.thread_id,
            confirm=confirms,
        ):
            yield event

        return

    prompt = self._last_user_text(input_)
    if not prompt:
        raise ValueError("No user message found.")

    async for event in self._agent.stream(
        prompt=prompt,
        session_id=input_.thread_id,
    ):
        yield event
```


これで通常会話はこうなります。

LLM token
  -> Client.stream_llm()
  -> Agent.stream()
  -> API TEXT_MESSAGE_CONTENT
  -> assistant-uiに逐次表示

HITLは今まで通りです。

LLM tool_call確定
  -> Agent.act()
  -> need_confirm=True
  -> pending
  -> API interrupt
  -> frontend Approve/Deny

確認はこの順番でよいです。

uv run python -m py_compile src/agent/core/llm_client.py src/agent/core/agent.py src/api/service.py
uv run ruff check src/agent/core/llm_client.py src/agent/core/agent.py src/api/service.py

その後、Webから長めの回答を要求します。

日本の四季について500文字で説明して

これで少しずつ表示されれば成功です。



---------------------------------------


方針は run() と stream() を薄い入口にして、実体は _run_loop() に寄せる です。


3. agent.py の共通ループ実装


from collections.abc import AsyncIterator
from dataclasses import dataclass

llm_message import をこうします。

from .model.llm_message import (
    LLMResponseDone,
    LLMTextDelta,
    Request,
    Response,
)

context import をこうします。

from .model.context import (
    AgentResult,
    AgentStreamEvent,
    AgentStreamResult,
    AgentStreamTextDelta,
    AgentStreamTextEnd,
    AgentStreamTextStart,
    ExecContext,
    PendingToolCall,
    ToolConfirm,
)

logger の下あたりに追加します。

@dataclass(frozen=True)
class _StepComplete:
    result: AgentResult | None

```python
# run() をこの薄い実装に差し替えます。

async def run(
    self,
    prompt,
    ctx: ExecContext | None = None,
    session_id: str | None = None,
    confirm: list[ToolConfirm] | None = None,
    verbose: bool = False,
) -> AgentResult:

    result: AgentResult | None = None

    async for event in self._run_loop(
        prompt=prompt,
        ctx=ctx,
        session_id=session_id,
        confirm=confirm,
        verbose=verbose,
        stream_llm=False,
    ):
        if isinstance(event, AgentStreamResult):
            result = event.result

    if result is None:
        raise RuntimeError("Agent finished without result.")

    return result

# stream() を追加します。

async def stream(
    self,
    prompt,
    ctx: ExecContext | None = None,
    session_id: str | None = None,
    confirm: list[ToolConfirm] | None = None,
    verbose: bool = False,
) -> AsyncIterator[AgentStreamEvent]:

    async for event in self._run_loop(
        prompt=prompt,
        ctx=ctx,
        session_id=session_id,
        confirm=confirm,
        verbose=verbose,
        stream_llm=True,
    ):
        yield event

# step() は薄くします。

async def step(self, ctx: ExecContext, verbose: bool = False) -> AgentResult | None:
    async for event in self._step_loop(ctx, stream_llm=False, verbose=verbose):
        if isinstance(event, _StepComplete):
            return event.result

    return None

# 以下を internal 付近に追加します。

async def _run_loop(
    self,
    prompt,
    ctx: ExecContext | None,
    session_id: str | None,
    confirm: list[ToolConfirm] | None,
    verbose: bool,
    stream_llm: bool,
) -> AsyncIterator[AgentStreamEvent]:

    session = None
    if session_id and self.session_manager:
        session = await self.session_manager.get_or_create(session_id)

    if ctx is None:
        ctx = ExecContext(
            session=session,
            session_manager=self.session_manager,
            memory_manager=self.memory_manager,
        )

        if session:
            ctx.events = list(session.events)
            ctx.state = dict(session.state)

    elif ctx.memory_manager is None:
        ctx.memory_manager = self.memory_manager

    if confirm:
        await self._process_confirm(ctx, confirm)

    if prompt:
        user_event = Event.new_msg(ctx.exec_id, USER, prompt)
        ctx.add_event(user_event)

    if self.is_code_exec and ctx.code_env is None:
        await self._setup_code_env(ctx)

    try:
        while ctx.is_continue(self.max_step):
            step_result: AgentResult | None = None

            async for event in self._step_loop(
                ctx,
                stream_llm=stream_llm,
                verbose=verbose,
            ):
                if isinstance(event, _StepComplete):
                    step_result = event.result
                else:
                    yield event

            if step_result and step_result.status == "pending":
                if session and self.session_manager:
                    session.events = list(ctx.events)
                    session.state = dict(ctx.state)
                    await self.session_manager.save(session)

                yield AgentStreamResult(step_result)
                return

            event = ctx.last_event
            if event is None:
                continue

            if self._is_final_response(event):
                ctx.final_result = self._get_final_result(event)
                break

        if self.memory_manager:
            try:
                await self.memory_manager.save(ctx)
            except Exception as e:
                logger.warning(f"failed to save memory {e}")

        if session and self.session_manager:
            session.events = list(ctx.events)
            session.state = dict(ctx.state)
            await self.session_manager.save(session)

        yield AgentStreamResult(AgentResult(output=ctx.final_result, ctx=ctx))

    finally:
        if ctx.code_env is not None:
            result = ctx.code_env.kill()
            if inspect.isawaitable(result):
                await result

# _step_loop() と補助メソッドを追加します。

async def _step_loop(
    self,
    ctx: ExecContext,
    stream_llm: bool,
    verbose: bool,
) -> AsyncIterator[AgentStreamEvent | _StepComplete]:

    req = await self._get_request(ctx)
    res = await self._run_before_llm_callbacks(ctx, req)

    if res is None:
        if stream_llm:
            res = None
            text_started = False

            async for llm_event in self.client.stream_llm(req):
                if isinstance(llm_event, LLMTextDelta):
                    if not text_started:
                        yield AgentStreamTextStart()
                        text_started = True

                    yield AgentStreamTextDelta(llm_event.delta)
                    continue

                if isinstance(llm_event, LLMResponseDone):
                    res = llm_event.response

            if text_started:
                yield AgentStreamTextEnd()

        else:
            res = await self.think(req)

    if res is None:
        raise RuntimeError("LLM finished without response.")

    result = await self._apply_llm_response(ctx, res, verbose=verbose)
    yield _StepComplete(result)


async def _run_before_llm_callbacks(
    self,
    ctx: ExecContext,
    req: Request,
) -> Response | None:

    for callback in self.before_llm_cb:
        cb_result = callback(ctx, req)
        if inspect.isawaitable(cb_result):
            cb_result = await cb_result

        if isinstance(cb_result, Response):
            return cb_result

    return None


async def _apply_llm_response(
    self,
    ctx: ExecContext,
    res: Response,
    verbose: bool,
) -> AgentResult | None:

    if res.err_msg:
        raise RuntimeError(res.err_msg)

    if verbose:
        self._log_response(res)

    res_event = Event.new(ctx.exec_id, self.role, res.content)
    ctx.add_event(res_event)

    tool_calls = [c for c in res.content if isinstance(c, ToolCall)]
    if tool_calls:
        result = await self.act(ctx, tool_calls)
        if result and result.status == "pending":
            return result

    ctx.increment()
    return None
```

この後、既存の長い step() の中身は不要です。上の薄い step() に置き換えます。

4. api/service.py をstream対応にする

```python
# import を追加します。

import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

from ag_ui.core import Interrupt, RunAgentInput
from ag_ui.encoder import EventEncoder

from agent.core.agent import Agent
from api.event_factory import EventFactory

from agent.core.model.context import (
    AgentResult,
    AgentStreamResult,
    AgentStreamTextDelta,
    AgentStreamTextEnd,
    AgentStreamTextStart,
    PendingToolCall,
    ToolConfirm,
)

# stream_agent() を差し替えます。

    async def stream_agent(self, input_: RunAgentInput, accept: str | None) -> AsyncIterator[str]:

        enc = EventEncoder(accept=accept)
        ev = EventFactory(input_)

        yield enc.encode(ev.run_started())

        mid: str | None = None
        s_text = False   # streamed_text

        try:
            async for event in self._stream_agent_events(input_):

                # start
                if isinstance(event, AgentStreamTextStart):
                    if mid is None:
                        mid = f"msg_{uuid.uuid4().hex}"
                        yield enc.encode(ev.text_start(mid))
                    continue
                
                # content
                if isinstance(event, AgentStreamTextDelta):
                    if mid is None:
                        mid = f"msg_{uuid.uuid4().hex}"
                        yield enc.encode(ev.text_start(mid))

                    s_text = True
                    yield enc.encode(ev.text_content(mid, event.delta))
                    continue

                # end
                if isinstance(event, AgentStreamTextEnd):
                    if mid is not None:
                        yield enc.encode(ev.text_end(mid))
                        mid = None
                    continue

                # result
                if isinstance(event, AgentStreamResult):
                    if mid is not None:
                        yield enc.encode(ev.text_end(mid))
                        mid = None

                    ret = event.result

                    if ret.status == "pending":
                        interrupts = self._pending(
                            pending_tc=ret.pending_tc,
                            session_id=ev.thread_id,
                            agent_run_id=ret.ctx.exec_id,
                        )
                        yield enc.encode(ev.run_interrupt(interrupts))
                        return

                    if s_text:
                        yield enc.encode(ev.run_success())
                        return

                    async for chunk in self._to_events(enc=enc, ev=ev, ret=ret):
                        yield chunk
                    return

            raise RuntimeError("Agent stream finished without result.")

        except Exception as error:
            if mid is not None:
                yield enc.encode(ev.text_end(mid))

            async for chunk in self._text_events(enc=enc, ev=ev, text=f"error occurred: {error}"):
                yield chunk

            yield enc.encode(ev.run_success())

# 追加メソッドです。

    async def _stream_agent_events(self, input_: RunAgentInput):
        sid = input_.thread_id

        if input_.resume:
            confirms = self._resume(input_.resume)

            async for event in self._agent.stream(prompt="", session_id=sid, confirm=confirms):
                yield event

            return

        prompt = self._last_user_text(input_)
        if not prompt:
            raise ValueError("No user message found.")

        async for event in self._agent.stream(prompt=prompt, session_id=sid):
            yield event
```

既存の _run_agent() は残しても動きますが、stream経路では使わなくなります。落ち着いたら削除でよいです。

確認コマンド

uv run python -m py_compile src/agent/core/model/llm_message.py src/agent/core/llm_client.py src/agent/core/agent.py src/api/service.py
uv run ruff check src/agent/core/model/llm_message.py src/agent/core/llm_client.py src/agent/core/agent.py src/api/service.py

Web確認は長めの通常応答で見てください。

日本の四季について800文字で説明して

期待値は、通常回答が少しずつ表示されることです。delete_file は今まで通り、tool call確定後に interrupt になります。


----


できていることは、Agentの実行途中のテキストをWeb UIへ逐次流せるようになった ということです。

  今まではこうでした。

  Agent.run()
    -> LLM応答が全部返るまで待つ
    -> AgentResult.output を作る
    -> APIが完成済みテキストを返す
    -> Webに一気に表示

  今はこうです。

  Agent.stream()
    -> LLMのstream chunkを受け取る
    -> AgentStreamTextDelta として逐次yield
    -> APIが TEXT_MESSAGE_CONTENT に変換
    -> assistant-ui が受け取るたびに画面更新

  つまり、src/agent が「完了結果だけ返す」だけでなく、「途中経過も返せる」ようになりました。

  なぜ可能になったかというと、3層がそれぞれstream対応したからです。

  1. LLM client層

  litellm.acompletion(..., stream=True) にすると、LLMの返答が完成後に1個返るのではなく、chunkとして少しずつ返ります。

  "こ"
  "ん"
  "に"
  "ち"
  "は"

  2. Agent層

  そのchunkを Agent.stream() で yield するようにしました。

  LLMTextDelta
   -> AgentStreamTextDelta

  これにより、Agentが終わる前にAPIへ途中経過を渡せます。

  3. API層

  APIは AgentStreamTextDelta をAG UIイベントへ変換します。

  AgentStreamTextDelta
   -> TEXT_MESSAGE_CONTENT

  FastAPIの StreamingResponse は、yield されたデータを接続中のブラウザへ順次送れるので、Web側で少しずつ表示できます。

  結果として、全体はこう動きます。

  LLM token stream
    -> Client.stream_llm()
    -> Agent.stream()
    -> src/api/service.py
    -> AG UI SSE
    -> assistant-ui
    -> 画面に逐次表示

  HITLも引き続き動きます。

  delete_file tool call
    -> Agentが need_confirm=True を検知
    -> AgentResult(status="pending")
    -> APIが AG UI interrupt に変換
    -> Webで Approve / Deny
    -> resume
    -> Agent.run/stream が再開

  今回重要なのは、APIだけをstreamingにしても不十分だった点です。APIがSSEを使っていても、Agentが最後まで完了してから結果を返すなら、Webには一気に表示されま
  す。

  今回 Agent.stream() を作ったことで、Agent内部のLLM応答中に外側へイベントを出せる ようになったため、本当のstream表示が可能になりました。