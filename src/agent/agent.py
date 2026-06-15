import logging
import inspect
from typing import Any, Type
from pydantic import BaseModel
import json

from .llm import Request, Response
from .llm_client import Client
from .types import Event, Message, ToolCall, ToolResult
from .tool_base import BaseTool, FuncTool
from .helper_schema import format_tool_def
from .context import AgentResult, ExecContext
from .const import STR_SUCCESS, STR_ERROR, USER

from .code_exec import exec_python, bash_tool, upload_file
from .skills import find_skill, make_skills_prompt
from .helper_skill import upload_skills_to_sandbox
from .helper_agent import *

logger = logging.getLogger(__name__)

class Agent:

    def __init__(
        self,
        client: Client,
        tools: list[BaseTool] | None = None,
        system_prompt: str = "",
        max_steps: int = 10,
        role: str = "agent",
        desc: str = "",
        output_type: Type[BaseModel] | None = None,
        is_code_exec: bool = True,
        code_exec_image: str = "python",
        skills_path: str | None = None,
    ):
        self.client = client
        self.system_prompt = system_prompt
        self.max_step = max_steps
        self.role = role
        self.desc = desc
        self.output_type = output_type

        self.is_code_exec = is_code_exec
        self.code_exec_image = code_exec_image
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

    async def run(self, prompt, ctx: ExecContext | None = None, verbose: bool = False) -> AgentResult:

        if ctx is None:
            ctx = ExecContext()
        
        if prompt:
            user_event = Event.new_msg(ctx.exec_id, USER, prompt)
            ctx.add_event(user_event)

        if self.is_code_exec and \
           ctx.code_env is None:
            await self._setup_code_env(ctx)

        try:
            while ctx.is_continue(self.max_step):

                await self.step(ctx, verbose=verbose)

                event = ctx.last_event
                if event is None:
                    continue

                if self._is_final_response(event):
                    ctx.final_result = self._get_final_result(event)

            return AgentResult(output=ctx.final_result, ctx=ctx)

        finally:
            if ctx.code_env is not None:
                result = ctx.code_env.kill()
                if inspect.isawaitable(result):
                    await result


    async def step(self, ctx: ExecContext, verbose: bool = False) -> None:
        
        req = self._get_request(ctx)
        res = await self.think(req)

        if res.err_msg:
            raise RuntimeError(res.err_msg)

        if verbose:
            self._log_response(res)
        
        res_event = Event.new(ctx.exec_id, self.role, res.content)
        ctx.add_event(res_event)

        if res.tool_calls:
            await self.act(ctx, res.tool_calls)
        
        ctx.increment()


    async def think(self, request: Request) -> Response:
        return await self.client.call_llm(request)
    
    async def act(self, ctx: ExecContext, tool_calls: list[ToolCall]) -> None:
        
        results: list[Message | ToolCall | ToolResult] = []

        for tool_call in tool_calls:

            # not register tool
            if tool_call.name not in self.tools_dict:
                tool_ret = ToolResult.new(tool_call, STR_ERROR)
                results.append(tool_ret)
                continue

            tool_call_obj = self.tools_dict[tool_call.name]

            try:
                # call tool
                output = await tool_call_obj(ctx, **tool_call.args)
                tool_ret = ToolResult.new(tool_call, STR_SUCCESS, output)
                results.append(tool_ret)

            except Exception as e:
                tool_ret = ToolResult.new(tool_call, STR_ERROR, str(e))
                results.append(tool_ret)

        if results:
            tool_event = Event.new(ctx.exec_id, self.role, results)
            ctx.add_event(tool_event)
        
    # ---------------
    # - internal
    # ---------------

    def _get_request(self, ctx: ExecContext) -> Request:

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
                skill = find_skill(self.skills_path)
                skills_prompt = make_skills_prompt(skill)
                if skills_prompt:
                    system_prompt.append(skills_prompt)
            except Exception:
                pass

        if self.output_tool_name:
            tool_choice = "required"
        elif self.tools:
            tool_choice = "auto"
        else:
            tool_choice = None
        
        return Request(
            system_prompt=system_prompt,
            contents=histories,
            tools=self.tools,
            tool_choice=tool_choice
        )
    
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

        return tools
    
    async def _setup_code_env(self, ctx: ExecContext):

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
        
        except Exception:
            ctx.code_env = None

            if sandbox is None:
                logger.warning("failed to set up code execution environment", exc_info=True)
                return

            result = sandbox.kill()
            if inspect.isawaitable(result):
                await result

            logger.warning("failed to set up code execution environment", exc_info=True)
    
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

    def _log_response(self, response: Response):

        for item in response.content:
            if isinstance(item, Message):
                logger.info(f"[{self.role}] {item.content}")
            elif isinstance(item, ToolCall):
                logger.info(f"[{self.role}] Tool call: {item.name}({item.args})")
