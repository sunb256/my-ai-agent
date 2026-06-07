import logging
from typing import Any, Type
from pydantic import BaseModel

from .llm import Request, Response
from .llm_client import Client
from .types import Event, Message, ToolCall, ToolResult
from .tool_base import BaseTool, FuncTool
from .helpers import format_tool_def
from .context import AgentResult, ExecContext

logger = logging.getLogger(__name__)

class Agent:

    def __init__(
        self,
        client: Client,
        tools: list[BaseTool] | None = None,
        insts: str = "",
        max_steps: int = 10,
        name: str = "agent",
        desc: str = "",
        output_type: Type[BaseModel] | None = None
    ):
        self.client = client
        self.insts = insts
        self.max_step = max_steps
        self.name = name
        self.desc = desc
        self.output_type = output_type

        self.output_tool_name: str | None = None
        self.tools = self._setup_tools(tools or [])
    
    # ---------------
    # - Core loop
    # ---------------

    async def run(
        self,
        user_input,
        ctx: ExecContext | None = None,
        verbose: bool = False,
    ) -> AgentResult:

        if ctx is None:
            ctx = ExecContext()
        
        if user_input:
            user_event = Event(
                exec_id=ctx.exec_id,
                author="user",
                content=[Message(role="user", content=user_input)],
            )
            ctx.add_event(user_event)
        
        while ctx.is_continue(self.max_step):
            await self.step(ctx, verbose=verbose)
            
            if ctx.last_event:
                if self._is_final_response(ctx.last_event):
                    ctx.final_result = self._extract_final_result(ctx.last_event)
        
        return AgentResult(output=ctx.final_result, ctx=ctx)
    
    async def step(self, ctx: ExecContext, verbose: bool = False) -> None:
        
        request = self._prepare_request(ctx)
        response = await self.think(request)

        if response.err_msg:
            raise RuntimeError(response.err_msg)

        if verbose:
            self._log_response(response)
        
        res_event = Event(
            exec_id=ctx.exec_id,
            author=self.name,
            content=response.content
        )
        ctx.add_event(res_event)

        tool_calls = [tc for tc in response.content if isinstance(tc, ToolCall)]
        if tool_calls:
            await self.act(ctx, tool_calls)
        
        ctx.increment()


    async def think(self, request: Request) -> Response:
        return await self.client.call_llm(request)
    
    async def act(self, ctx: ExecContext, tool_calls: list[ToolCall]) -> None:
        
        tools_dict = {item.name: item for item in self.tools}
        results: list[Message | ToolCall | ToolResult] = []

        for tool_call in tool_calls:
            if tool_call.name not in tools_dict:
                results.append(
                    ToolResult(
                        tool_call_id=tool_call.tool_call_id,
                        name=tool_call.name,
                        status="error",
                        content=[f"Unknown tool: {tool_call.name}"]
                    )
                )
                continue

            tool_obj = tools_dict[tool_call.name]

            try:
                output = await tool_obj(ctx, **tool_call.args)
                results.append(
                    ToolResult(
                        tool_call_id=tool_call.tool_call_id,
                        name=tool_call.name,
                        status="success",
                        content=[output]
                    )
                )
            except Exception as e:
                results.append(ToolResult(
                        tool_call_id=tool_call.tool_call_id,
                        name=tool_call.name,
                        status="error",
                        content=[str(e)]
                    )
                )
        if results:
            tool_event = Event(
                exec_id=ctx.exec_id,
                author=self.name,
                content=results
            )
            ctx.add_event(tool_event)
        
    # ---------------
    # - internal
    # ---------------

    def _prepare_request(self, ctx: ExecContext) -> Request:
        flat_content = []
        for event in ctx.events:
            flat_content.extend(event.content)
        
        insts = []
        if self.insts:
            insts.append(self.insts)
        
        if self.output_tool_name:
            tool_choice = "required"
        elif self.tools:
            tool_choice = "auto"
        else:
            tool_choice = None
        
        return Request(
            insts = insts,
            contents=flat_content,
            tools=self.tools,
            tool_choice=tool_choice
        )

    def _is_final_response(self, event: Event) -> bool:
        if self.output_tool_name:
            for item in event.content:
                if (
                    isinstance(item, ToolResult) and
                    item.name == self.output_tool_name and
                    item.status == "success"
                ):
                    return True
            return False
        
        has_tool_call = any(isinstance(tc, ToolCall) for tc in event.content)
        has_tool_result = any(isinstance(tc, ToolResult) for tc in event.content)
        return not has_tool_call and not has_tool_result
    
    def _extract_final_result(self, event: Event) -> Any:
        if self.output_tool_name:
            for item in event.content:
                if (
                    isinstance(item, ToolResult) and
                    item.name == self.output_tool_name and
                    item.status == "success" and
                    item.content
                ):
                    return item.content[0]
            return None
            
        for item in event.content:
            if isinstance(item, Message) and \
                item.role == "assistant":
                return item.content
        
        return None
        
    
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
                logger.info(f"[{self.name}] {item.content}")
            elif isinstance(item, ToolCall):
                logger.info(f"[{self.name}] Tool call: {item.name}({item.args})")
