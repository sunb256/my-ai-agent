from dataclasses import dataclass
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

@dataclass
class StreamState:
    mid: str | None = None
    streamed_text: bool = False
    finished: bool = False


class AgentApiService:

    def __init__(self, agent: Agent):
        self._agent = agent
 
    async def stream_agent(self, input_: RunAgentInput, accept: str | None) -> AsyncIterator[str]:

        enc = EventEncoder(accept=accept)
        ev = EventFactory(input_)
        state = StreamState()

        yield enc.encode(ev.run_started())

        try:
            async for chunk in self._emit_stream(input_=input_, enc=enc, ev=ev, state=state):
                yield chunk

        except Exception as error:
            async for chunk in self._emit_error(enc=enc, ev=ev, state=state, error=error):
                yield chunk

    async def _emit_stream(self, input_: RunAgentInput, enc: EventEncoder, ev: EventFactory, state: StreamState) -> AsyncIterator[str]:
        
        async for event in self._get_stream_events(input_):

            async for chunk in self._emit_event(event=event, enc=enc, ev=ev, state=state):
                yield chunk

            if state.finished:
                return

        raise RuntimeError("Agent stream finished without result.")

    async def _get_stream_events(self, input_: RunAgentInput):
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

    def _last_user_text(self, input_: RunAgentInput) -> str:
        for message in reversed(input_.messages):
            if getattr(message, "role", None) != "user":
                continue

            return self._content_to_text(getattr(message, "content", ""))

        return ""

    def _content_to_text(self, content: Any) -> str:
        if isinstance(content, str):
            return content.strip()

        if not isinstance(content, list):
            return ""

        texts: list[str] = []

        for part in content:
            if getattr(part, "type", None) != "text":
                continue

            text = getattr(part, "text", "")
            if isinstance(text, str):
                texts.append(text)

        return "\n".join(texts).strip()

    async def _emit_event(self, event, enc: EventEncoder, ev: EventFactory, state: StreamState) -> AsyncIterator[str]:
        
        # start
        if isinstance(event, AgentStreamTextStart):
            if state.mid is None:
                state.mid = f"msg_{uuid.uuid4().hex}"
                yield enc.encode(ev.text_start(state.mid))
            return

        # delta
        if isinstance(event, AgentStreamTextDelta):
            if state.mid is None:
                state.mid = f"msg_{uuid.uuid4().hex}"
                yield enc.encode(ev.text_start(state.mid))

            state.streamed_text = True
            yield enc.encode(ev.text_content(state.mid, event.delta))
            return

        # end
        if isinstance(event, AgentStreamTextEnd):
            async for chunk in self._close_text(enc, ev, state):
                yield chunk
            return

        # result
        if isinstance(event, AgentStreamResult):
            async for chunk in self._emit_result(ret=event.result, enc=enc, ev=ev, state=state):
                yield chunk
            return

        raise TypeError(f"Unsupported agent stream event: {type(event).__name__}")


    async def _close_text(self, enc: EventEncoder, ev: EventFactory, state: StreamState) -> AsyncIterator[str]:
        
        if state.mid is None:
            return

        yield enc.encode(ev.text_end(state.mid))
        state.mid = None

    async def _emit_result(self, ret: AgentResult, enc: EventEncoder, ev: EventFactory, state: StreamState) -> AsyncIterator[str]:
        
        async for chunk in self._close_text(enc, ev, state):
            yield chunk

        if ret.status == "pending":
            interrupts = self._pending(
                pending_tc=ret.pending_tc,
                session_id=ev.thread_id,
                agent_run_id=ret.ctx.exec_id,
            )

            yield enc.encode(ev.run_interrupt(interrupts))
            state.finished = True
            return

        if state.streamed_text:
            yield enc.encode(ev.run_success())
            state.finished = True
            return

        async for chunk in self._emit_non_stream_result(enc=enc, ev=ev, ret=ret):
            yield chunk

        state.finished = True


    async def _emit_error(self, enc: EventEncoder, ev: EventFactory, state: StreamState, error: Exception) -> AsyncIterator[str]:
        
        async for chunk in self._close_text(enc, ev, state):
            yield chunk

        async for chunk in self._text_events(enc=enc, ev=ev, text=f"error occurred: {error}"):
            yield chunk

        yield enc.encode(ev.run_success())


    async def _emit_non_stream_result(self, 
                                      enc: EventEncoder,
                                      ev: EventFactory,
                                      ret: AgentResult) -> AsyncIterator[str]:
        
        if ret.output is not None:
            text = self._output_text(ret.output)

            async for chunk in self._text_events(enc=enc, ev=ev, text=text):
                yield chunk
            
            yield enc.encode(ev.run_success())
            return
        
        raise RuntimeError("Agent finished without output.")
        
    def _output_text(self, output: Any) -> str:
        if isinstance(output, str):
            return output

        if hasattr(output, "model_dump"):
            return json.dumps(output.model_dump(), ensure_ascii=False, default=str)

        return json.dumps(output, ensure_ascii=False, default=str)

    async def _text_events(self, enc: EventEncoder, ev: EventFactory, text: str) -> AsyncIterator[str]:
        mid = f"msg_{uuid.uuid4().hex}"

        yield enc.encode(ev.text_start(mid))
        
        for char in text:
            yield enc.encode(ev.text_content(mid, char))
        
        yield enc.encode(ev.text_end(mid))

    def _pending(self, 
                 pending_tc: list[PendingToolCall],
                 session_id: str,
                 agent_run_id: str) -> list[Interrupt]:

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

    def _interrupt_id(self, tool_call_id: str) -> str:
        return f"interrupt_{tool_call_id}"

    def _resume(self, resume: list[Any]) -> list[ToolConfirm]:
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
    
    def _tool_call_id_from_interrupt(self, interrupt_id: str) -> str:
        return interrupt_id.removeprefix("interrupt_")
    
