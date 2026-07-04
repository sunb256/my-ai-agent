from collections.abc import AsyncIterator
from dataclasses import dataclass
import logging
import inspect
from typing import TYPE_CHECKING, Any, Optional, Type, Callable
from pydantic import BaseModel
import json

from .llm_client import Client
from .model.types import Event, Message, ToolCall, ToolResult
from .model.tool_base import BaseTool, FuncTool
from .helpers.schema import format_tool_def
from .helpers.const import STR_SUCCESS, STR_ERROR, USER

from .memory.session import BaseSessionManager
from .code_exec import exec_python, bash_tool, upload_file
from .skills import find_skill, make_skills_prompt, make_requested_skills_prompt, select_requested_skills
from .helpers.skill import upload_skills_to_sandbox
from .helpers.agent import (
      get_final_by_output_tool,
      get_final_by_plain_message,
      is_final_by_output_tool,
      is_final_by_plain_message,
  )

from .model.llm_message import (
    LLMResponseDone,
    LLMTextDelta,
    Request,
    Response,
)

from .model.context import (
    AgentResult,
    AgentStreamEvent,
    AgentStreamResult,
    AgentStreamTextDelta,
    AgentStreamTextEnd,
    AgentStreamTextStart,
    AgentStreamToolCallArgs,
    AgentStreamToolCallEnd,
    AgentStreamToolCallResult,
    AgentStreamToolCallStart,
    ExecContext,
    PendingToolCall,
    ToolConfirm,
)

if TYPE_CHECKING:
    from .memory.long_term import TaskMemoryManager

@dataclass(frozen=True)
class _StepComplete:
    result: AgentResult | None

logger = logging.getLogger(__name__)

class Agent:

    def __init__(
        self,
        # baseic feature
        client: Client,
        tools: list[BaseTool] | None = None,
        system_prompt: str = "",
        max_steps: int = 10,
        role: str = "agent",
        desc: str = "",
        output_type: Type[BaseModel] | None = None,
        # callback
        before_tool_cb: list[Callable] | None = None,
        after_tool_cb: list[Callable] | None = None,
        # session
        session_manager: Optional["BaseSessionManager"] = None,
        memory_manager: Optional["TaskMemoryManager"] = None,
        before_llm_cb: list[Callable] | None = None,
        # code exec
        is_code_exec: bool = True,
        code_exec_image: str = "python",
        code_exec_runtime: str = "microsandbox",
        # skill
        skills_path: str | None = None,
    ):
        self.client = client
        self.system_prompt = system_prompt
        self.max_step = max_steps
        self.role = role
        self.desc = desc
        self.output_type = output_type

        self.before_tool_cb = before_tool_cb or []
        self.after_tool_cb = after_tool_cb or []
        
        self.session_manager = session_manager
        self.memory_manager = memory_manager
        self.before_llm_cb = before_llm_cb or []
        
        self.is_code_exec = is_code_exec
        self.code_exec_image = code_exec_image
        self.code_exec_runtime = code_exec_runtime
        self._sandbox_tools: list[FuncTool] = []

        self.skills_path = skills_path
        
        self.output_tool_name: str | None = None
        self.tools = self._setup_tools(tools or [])
    
    @property
    def tools_dict(self):
        return {item.name: item for item in self.tools}

    # ---------------
    # - Core loop
    # ---------------

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

        # hitl
        if confirm:
            conf_rets = await self._process_confirm(ctx, confirm)

            if stream_llm:
                for tool_result in conf_rets:
                    yield AgentStreamToolCallResult(tool_result)

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

                # hitl
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

            if ctx.final_result is None and conf_rets:
                ctx.final_result = self._tool_rets_output(conf_rets)

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
    
    async def step(self, ctx: ExecContext, verbose: bool = False) -> AgentResult | None:

        async for event in self._step_loop(ctx, stream_llm=False, verbose=verbose):
            if isinstance(event, _StepComplete):
                return event.result

        return None

    async def _step_loop(self, ctx: ExecContext, stream_llm: bool, verbose: bool) -> AsyncIterator[AgentStreamEvent | _StepComplete]:

        req = await self._get_request(ctx)
        res = await self._run_before_llm_cb(ctx, req)

        if res is None:

            # stream
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

            # normal
            else:
                res = await self.think(req)

        if res is None:
            raise RuntimeError("LLM finished without response.")

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

    async def _run_before_llm_cb(self, ctx: ExecContext, req: Request) -> Response | None:

        for callback in self.before_llm_cb:

            cb_result = callback(ctx, req)
            if inspect.isawaitable(cb_result):
                cb_result = await cb_result

            if isinstance(cb_result, Response):
                return cb_result

        return None


    async def _apply_llm_response(self, ctx: ExecContext, res: Response, verbose: bool) -> list[ToolCall]:

        if res.err_msg:
            raise RuntimeError(res.err_msg)

        if verbose:
            self._log_response(res)

        res_event = Event.new(ctx.exec_id, self.role, res.content)
        ctx.add_event(res_event)

        return [c for c in res.content if isinstance(c, ToolCall)]

    def _tool_results_since(self, ctx: ExecContext, event_cnt: int) -> list[ToolResult]:
        
        results: list[ToolResult] = []

        for event in ctx.events[event_cnt:]:
            for item in event.content:
                if isinstance(item, ToolResult):
                    results.append(item)

        return results

    async def think(self, req: Request) -> Response:
        return await self.client.call_llm(req)
    
    async def act(self, ctx: ExecContext, tool_calls: list[ToolCall]) -> AgentResult | None:  # noqa: C901
        
        results: list[Message | ToolCall | ToolResult] = []
        pending = []

        for tool_call in tool_calls:

            # not register tool
            if tool_call.name not in self.tools_dict:
                tool_ret = ToolResult.new(tool_call, STR_ERROR)
                results.append(tool_ret)
                continue

            tool_obj = self.tools_dict[tool_call.name]

            # confirm
            if tool_obj.need_confirm:
                msg = tool_obj.get_confirm_msg(tool_call.args)
                pending.append(PendingToolCall(tool_call=tool_call, confirm=msg))
                continue

            # before callback
            skip = False
            for callback in self.before_tool_cb:
                cb_ret1 = callback(ctx, tool_call)
                if inspect.isawaitable(cb_ret1):
                    cb_ret1 = await cb_ret1

                if cb_ret1 is not None:
                    tool_result = ToolResult.new(tool_call, STR_SUCCESS, cb_ret1)
                    results.append(tool_result)
                    skip = True
                    break
            
            if skip:
                continue
            
            # main tool_call
            tool_res = None

            try:
                tool_res = await tool_obj(ctx, **tool_call.args)
                tool_ret = ToolResult.new(tool_call, STR_SUCCESS, tool_res)
                
            except Exception as e:
                tool_res = str(e)
                tool_ret = ToolResult.new(tool_call, STR_ERROR, tool_res)

            # after callback
            for callback in self.after_tool_cb:
                cb_ret2 = callback(ctx, tool_ret)
                if inspect.isawaitable(cb_ret2):
                    cb_ret2 = await cb_ret2

                if cb_ret2 is not None:
                    if isinstance(cb_ret2, ToolResult):
                        tool_ret = cb_ret2
                    else:
                        tool_ret = ToolResult.new(tool_call, STR_SUCCESS, cb_ret2)
                    break
            
            results.append(tool_ret)

        if pending:
            ctx.state["pending_tool_calls"] = [p.model_dump() for p in pending]
            if results:
                tool_event = Event.new(ctx.exec_id, self.role, results)
                ctx.add_event(tool_event)
            return AgentResult(output=None, ctx=ctx, status="pending", pending_tc=pending)
        
        # record tool_result
        if results:
            tool_event = Event.new(ctx.exec_id, self.role, results)
            ctx.add_event(tool_event)
        
        return None
        
    # ---------------
    # - internal
    # ---------------

    async def _get_request(self, ctx: ExecContext) -> Request:

        system_prompt = []
        if self.system_prompt:
            system_prompt.append(self.system_prompt)

        # add sandbox prompt
        sandbox_prompt = self._get_sandbox_tools_prompt()
        if sandbox_prompt:
            system_prompt.append(sandbox_prompt)

        # instruction
        histories = []
        for event in ctx.events:
            histories.extend(event.content)
        
        if self.skills_path:
            try:
                skills = find_skill(self.skills_path)

                skills_prompt = make_skills_prompt(skills)
                if skills_prompt:
                    system_prompt.append(skills_prompt)

                user_text = self._last_user_text(histories)
                requested_skills = select_requested_skills(skills, user_text)

                skills_prompt = make_requested_skills_prompt(requested_skills)
                if skills_prompt:
                    system_prompt.append(skills_prompt)

            except Exception:
                pass

        llm_tools = [tool for tool in self.tools if tool.tool_def is not None]

        if self.output_tool_name:
            tool_choice = "required"
        elif llm_tools:
            tool_choice = "auto"
        elif self.tools:
            tool_choice = "auto"
        else:
            tool_choice = None
        
        req = Request(
            system_prompt=system_prompt,
            contents=histories,
            tools=llm_tools,
            tool_choice=tool_choice,
        )

        for tool_obj in self.tools:
            await tool_obj.process_llm_request(ctx, req)

        return req

    def _last_user_text(self, histories: list[Message | ToolCall | ToolResult]) -> str:
        for item in reversed(histories):
            if isinstance(item, Message) and item.role == USER:
                return item.content

        return ""
    
    def _is_final_response(self, event: Event) -> bool:
        if self.output_tool_name:
            return is_final_by_output_tool(event, self.output_tool_name)
        else:
            return is_final_by_plain_message(event)
    
    def _get_final_result(self, event: Event) -> Any:
        if self.output_tool_name:
            return get_final_by_output_tool(event, self.output_tool_name)
        else:
            return get_final_by_plain_message(event)
    
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

    def _setup_tools(self, tools: list[BaseTool]) -> list[BaseTool]:
        tools = list(tools)

        if self.output_type is not None:
            output_schema = self.output_type.model_json_schema()
            output_schema.pop("title", None)
            output_schema.pop("$defs", None)

            tool_def = format_tool_def(
                "final_answer",
                "Return the final structured answer matching the required schema.",
                {
                    "type": "object",
                    "properties": {"output": output_schema},
                    "required": ["output"],
                },
            )

            captured_type = self.output_type
            
            def _parse_output(output) -> Any:
                if isinstance(output, dict):
                    return captured_type.model_validate(output)
                return output
            
            # register final_answer tool for structured output
            final_answer_tool = FuncTool(
                func=_parse_output,
                name="final_answer",
                desc="Return the final structured answer matching the required schema.",
                tool_def =tool_def
            )
            
            tools.append(final_answer_tool)
            self.output_tool_name = "final_answer"

        for t in tools:
            if not isinstance(t, FuncTool) or \
               not t.sandbox_exec:
                continue
            self._sandbox_tools.append(t)

        if self.is_code_exec:
            tools.extend([exec_python, bash_tool, upload_file])

        if self.memory_manager:
            from .tools.memory_tool import MemoryTool
            tools.append(MemoryTool())

        return tools
    
    async def _setup_code_env(self, ctx: ExecContext):
        runtime = self.code_exec_runtime.strip().lower()
        if runtime not in {"microsandbox", "docker", "auto"}:
            logger.warning("unsupported code execution runtime: %s", self.code_exec_runtime)
            ctx.code_env = None
            return

        if runtime in {"microsandbox", "auto"}:
            if await self._setup_microsandbox_code_env(ctx):
                return

            if runtime == "microsandbox":
                return

        await self._setup_docker_code_env(ctx)

    async def _setup_microsandbox_code_env(self, ctx: ExecContext) -> bool:

        sandbox = None
        try:
            from microsandbox import Sandbox
            
            name = f"agent-{ctx.exec_id}"
            sandbox = await Sandbox.create(
                name,
                image=self.code_exec_image,
                cpus=1,
                memory=512,
                replace=True
            )

            await self._register_sandbox_tools(sandbox)
            ctx.code_env = sandbox

            await upload_skills_to_sandbox(sandbox, self.skills_path)
            return True
        
        except Exception:
            ctx.code_env = None

            if sandbox is None:
                logger.warning("failed to set up code execution environment", exc_info=True)
                return False

            result = sandbox.kill()
            if inspect.isawaitable(result):
                await result

            logger.warning("failed to set up code execution environment", exc_info=True)
            return False

    async def _setup_docker_code_env(self, ctx: ExecContext) -> None:
        sandbox = None
        try:
            from .docker_code_env import DockerCodeSandbox

            name = f"agent-{ctx.exec_id}"
            sandbox = await DockerCodeSandbox.create(
                name,
                image=self.code_exec_image,
                replace=True,
            )

            await self._register_sandbox_tools(sandbox)
            ctx.code_env = sandbox

            await upload_skills_to_sandbox(sandbox, self.skills_path)

        except Exception:
            ctx.code_env = None

            if sandbox is None:
                logger.warning("failed to set up Docker code execution environment", exc_info=True)
                return

            result = sandbox.kill()
            if inspect.isawaitable(result):
                await result

            logger.warning("failed to set up Docker code execution environment", exc_info=True)
    
    async def _register_sandbox_tools(self, sandbox) -> None:

        sandbox_home = "/tmp"
        tool_path = f"{sandbox_home}/sandbox_tools.py"

        tool_srcs = []
        for tool in self._sandbox_tools:
            src = tool.get_source_code()
            tool_srcs.append(src)
        
        combined_src = "\n\n".join(tool_srcs)
        result = sandbox.fs.write(tool_path, combined_src.encode("utf-8"))
        if inspect.isawaitable(result):
            await result

        # check import 
        result = sandbox.exec(
            "python",
            [
                "-c",
                (
                    "import sys; "
                    f"sys.path.insert(0, {sandbox_home!r}); "
                    "import sandbox_tools"
                ),
            ],
        )
        if inspect.isawaitable(result):
            result = await result
        
        if result.exit_code != 0:
            raise RuntimeError(f"Failed to register sandbox tools: {result.stderr_text}")

    def _get_sandbox_tools_prompt(self) -> str:
        if not self._sandbox_tools:
            return ""
        
        tool_def = [t.tool_def for t in self._sandbox_tools]
        tools_json = json.dumps(tool_def, indent=2, ensure_ascii=False)

        return (
            "\n\n## Sandbox-Executable Tools\n"
            "The following functions are pre-registered in the sandbox"
            "and can be called directory in your Python code:\n"
           f"{tools_json}"
        )

    async def _process_confirm(self, ctx: ExecContext, confirms: list[ToolConfirm]) -> list[ToolResult]:

        raw_pending = ctx.state.pop("pending_tool_calls", [])
        pending = [PendingToolCall.model_validate(d) for d in raw_pending]

        tool_dict = {t.name: t for t in self.tools}
        results = []

        for pending_call in pending:

            tc = pending_call.tool_call
            conf = next((c for c in confirms if c.tool_call_id  == tc.tool_call_id), None,)

            if conf and conf.approved:

                args = conf.modified_args or tc.args
                tool_obj = tool_dict.get(tc.name)

                if tool_obj:
                    try:
                        output = await tool_obj(ctx, **args)
                        tool_result = ToolResult.new(tc, STR_SUCCESS, output)
                    except Exception as e:
                        tool_result = ToolResult.new(tc, STR_ERROR, str(e))
                else:
                    tool_result = ToolResult.new(tc, STR_ERROR)
            else:
                tool_result = ToolResult.new(tc, STR_ERROR, "User denied the tool execution.")

            results.append(tool_result)

        if results:
            event = Event.new(ctx.exec_id, self.role, results)
            ctx.add_event(event)

        return results


    def _log_response(self, res: Response):

        for item in res.content:
            if isinstance(item, Message):
                logger.info(f"[{self.role}] {item.content}")
            elif isinstance(item, ToolCall):
                logger.info(f"[{self.role}] Tool call: {item.name}({item.args})")

