import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

from ag_ui.core import Interrupt, RunAgentInput
from ag_ui.encoder import EventEncoder

from agent.core.agent import Agent
from agent.core.model.context import AgentResult, PendingToolCall, ToolConfirm
from api.event_factory import EventFactory


class AgentApiService:

    def __init__(self, agent: Agent):
        self._agent = agent
    
    async def stream_agent(
            self,
            input_: RunAgentInput,
            accept: str | None,
    ) -> AsyncIterator[str]:
        
        enc = EventEncoder(accept=accept)
        ev = EventFactory(input_)

        yield enc.encode(ev.run_started())

        try:
            ret = await self._run_agent(input_)

            async for chunk in self._to_events(enc=enc, ev=ev, ret=ret):
                yield chunk

        except Exception as error:
            # yield enc.encode(ev.run_error(str(error), "agent_error"))
            async for chunk in self._text_events(enc=enc, ev=ev, text=f"error occurred: {error}"):
                yield chunk

            yield enc.encode(ev.run_success())
            return


    async def _run_agent(self, input_: RunAgentInput) -> AgentResult:
        if input_.resume:
            confirms = self._resume(input_.resume)
            return await self._agent.run(
                prompt="",
                session_id=input_.thread_id,
                confirm=confirms
            )
    
        prompt = self._last_user_text(input_)
        if not prompt:
            raise ValueError("No user message found.")
        
        return await self._agent.run(
            prompt=prompt,
            session_id=input_.thread_id
        )
    

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


    async def _to_events(self, 
                         enc: EventEncoder,
                         ev: EventFactory,
                         ret: AgentResult) -> AsyncIterator[str]:
        
        if ret.status == "pending":
            interrupt = self._pending(
                  pending_tc=ret.pending_tc,
                  session_id=ev.thread_id,
                  agent_run_id=ret.ctx.exec_id,
            )
            yield enc.encode(ev.run_interrupt(interrupt))
            return
        
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
    
