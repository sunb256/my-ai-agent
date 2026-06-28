import json
from typing import Any, AsyncIterator

from agent.core.agent import Agent
from agent.core.model.context import ToolConfirm

from .schemas import ChatRunRequest, ResumeRunRequest, ToolConfirmPayload
# from .stream_events import sse
from .stream_events import (
    ds_error,
    ds_finish_message,
    ds_start_tool_call,
    ds_text_delta,
    ds_tool_call_args_delta,
)

class AgentApiService:

    def __init__(self, agent: Agent):
        self._agent = agent

    async def stream_chat(self, body: ChatRunRequest, session_id: str) -> AsyncIterator[str]:
        run_id = ""

        try:
            prompt = (body.prompt or "").strip()
            if not prompt:
                prompt = self._extract_prompt(body.messages)

            if not prompt:
                yield ds_error("No user text found in messages.")
                yield ds_finish_message("error")
                return

            result = await self._agent.run(
                prompt=prompt,
                session_id=session_id,
                verbose=body.verbose,
            )
            run_id = result.ctx.exec_id

            async for event in self._agent_result(session_id, result, run_id):
                yield event

        except Exception as error:
            yield ds_error(str(error))
            yield ds_finish_message("error")
    

    async def stream_resume(self, session_id: str, body: ResumeRunRequest) -> AsyncIterator[str]:

        try:
            await self._get_pending_run_id(session_id)
            confirms = [self._to_tool_confirm(item) for item in body.confirm]

            result = await self._agent.run(
                prompt="",
                session_id=session_id,
                confirm=confirms,
                verbose=body.verbose,
            )

            next_run_id = result.ctx.exec_id

            async for event in self._agent_result(session_id, result, next_run_id):
                yield event

        except Exception as error:
            yield ds_error(str(error))
            yield ds_finish_message("error")
        
        
    async def _agent_result(self, session_id: str, result: Any, error_run_id: str) -> AsyncIterator[str]:
        run_id = result.ctx.exec_id

        if result.status == "pending":
            await self._save_pending_run_id(session_id, run_id)

            pending = self._pending_payload(result.pending_tc)
            tool_call_id = f"human_approval_{run_id}"

            args = {
                "session_id": session_id,
                "run_id": run_id,
                "pending": pending,
            }

            yield ds_start_tool_call(tool_call_id, "human_approval")
            yield ds_tool_call_args_delta(
                tool_call_id,
                json.dumps(args, ensure_ascii=False),
            )

            yield ds_finish_message("tool-calls")
            return

        await self._clear_pending_run_id(session_id)

        if result.output is not None:
            text = self._output_text(result.output)
            if text:
                yield ds_text_delta(text)
            yield ds_finish_message("stop")
            return

        _ = error_run_id
        yield ds_error("agent_finished_without_output")
        yield ds_finish_message("error")
        
        
    def _extract_prompt(self, messages: list[dict[str, Any]]) -> str:
        # usebataStreamRuntime からなる messages から最後の user_text を抽出
        for message in reversed(messages):

            if not isinstance(message, dict):
                continue

            if message.get("role") != "user":
                continue

            content = message.get("content")

            if isinstance(content, str):
                text = content.strip()
                if text:
                    return text

            if isinstance(content, list):
                parts: list[str] = []

                for part in content:
                    if not isinstance(part, dict):
                        continue
                    if part.get("type") == "text" and isinstance(part.get("text"), str):
                        parts.append(part["text"])
                    elif isinstance(part.get("text"), str):
                        parts.append(part["text"])

                joined = "".join(parts).strip()
                if joined:
                    return joined
        
        return ""
        
    def _to_tool_confirm(self, item: ToolConfirmPayload) -> ToolConfirm:
        return ToolConfirm(tool_call_id=item.id, approved=item.approved, modified_args=item.modified_args)

    def _pending_payload(self, pending_tc: list[Any]) -> list[dict[str, Any]]:
        payload: list[dict[str, Any]] = []

        for pending in pending_tc:
            payload.append(
                {
                    "tool_call_id": pending.tool_call.tool_call_id,
                    "name": pending.tool_call.name,
                    "args": pending.tool_call.args,
                    "confirm": pending.confirm,
                }
            )
        return payload

    def _output_text(self, output: Any) -> str:
        if isinstance(output, str):
            return output

        if hasattr(output, "model_dump"):
            return json.dumps(output.model_dump(), ensure_ascii=False, default=str)

        return json.dumps(output, ensure_ascii=False, default=str)

    async def _get_pending_run_id(self, session_id: str) -> str:
        manager = self._agent.session_manager
        if manager is None:
            raise ValueError("Session manager is not configured.")

        session = await manager.get(session_id)
        if session is None:
            raise ValueError(r"Session not found: {session_id}")

        pending_run_id = session.state.get("pending_run_id")
        if pending_run_id is None:
            raise ValueError("Pending run id not found.")

        if not isinstance(pending_run_id, str) or not pending_run_id:
            raise ValueError("Pending run id is invalid.")

        return pending_run_id


    async def _save_pending_run_id(self, session_id: str, run_id: str) -> None:
        manager = self._agent.session_manager
        if manager is None:
            return

        session = await manager.get(session_id)
        if session is None:
            return

        session.state["pending_run_id"] = run_id
        await manager.save(session)

    async def _clear_pending_run_id(self, session_id: str) -> None:
        manager = self._agent.session_manager
        if manager is None:
            return

        session = await manager.get(session_id)

        if session is None:
            return

        session.state.pop("pending_run_id", None)
        await manager.save(session)
