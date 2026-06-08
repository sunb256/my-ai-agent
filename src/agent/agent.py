import logging
from typing import Any, Type
from pydantic import BaseModel

from .llm import Request, Response
from .llm_client import Client
from .types import Event, Message, ToolCall, ToolResult
from .tool_base import BaseTool, FuncTool
from .helper_schema import format_tool_def
from .context import AgentResult, ExecContext
from .const import STR_SUCCESS, STR_ERROR, USER

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
        output_type: Type[BaseModel] | None = None
    ):
        self.client = client
        self.system_prompt = system_prompt
        self.max_step = max_steps
        self.role = role
        self.desc = desc
        self.output_type = output_type

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
                
        while ctx.is_continue(self.max_step):

            await self.step(ctx, verbose=verbose)

            event = ctx.last_event
            if event is None:
                continue

            if self._is_final_response(event):
                ctx.final_result = self._get_final_result(event)

        return AgentResult(output=ctx.final_result, ctx=ctx)
    

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

            tool_obj = self.tools_dict[tool_call.name]

            try:
                # call tool
                output = await tool_obj(ctx, **tool_call.args)
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

        histories = []
        for event in ctx.events:
            histories.extend(event.content)
        
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

        return tools
    
    def _log_response(self, response: Response):

        for item in response.content:
            if isinstance(item, Message):
                logger.info(f"[{self.role}] {item.content}")
            elif isinstance(item, ToolCall):
                logger.info(f"[{self.role}] Tool call: {item.name}({item.args})")
