import inspect
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Callable, Optional, Type
from pydantic import BaseModel

from agent.core.agent import Agent
from agent.core.helpers.schema import func_input_schema, format_tool_def
from agent.core.model.context import ExecContext

if TYPE_CHECKING:
      from agent.core.model.llm_message import Request

class BaseTool(ABC):

    DEFAULT_CONFIRMATION_TEMPLATE = (
        "The agent wants to execute '{name}' with arguments: {arguments}. "
        "Do you approve?"
    )

    def __init__(self,
                 name: str | None = None,
                 desc: str | None = None,
                 tool_def: dict[str, Any] | None = None,
                 need_confirm: bool = False,
                 confirm_msg_tmpl: str = "",
                 ):
    
        self.name = name or self.__class__.__name__
        self.desc = desc or self.__doc__ or ""
        self._tool_def = tool_def

        self.need_confirm = need_confirm
        self.confirm_msg_tmpl = (
            confirm_msg_tmpl
            if confirm_msg_tmpl
            else self.DEFAULT_CONFIRMATION_TEMPLATE
        )
    
    @property
    def tool_def(self) -> dict[str, Any] | None:
        return self._tool_def
    
    async def process_llm_request(self, ctx: "ExecContext", req: "Request") -> None:
        return None

    @abstractmethod
    async def exec(self, ctx: ExecContext, **kwargs) -> Any:
        pass

    def get_confirm_msg(self, args: dict) -> str:
        return self.confirm_msg_tmpl.format(name=self.name, args=args)

    async def __call__(self, ctx: ExecContext, **kwargs) -> Any:
        return await self.exec(ctx, **kwargs)
    

class FuncTool(BaseTool):

    def __init__(self,
                 func: Callable,
                 name: str | None = None,
                 desc: str | None = None,
                 tool_def: dict[str, Any] | None = None,
                 sandbox_exec: bool = False,
                 need_confirm: bool = False,
                 confirm_msg_tmpl: str = ""):
    
        self.func = func
        self.needs_ctx = "ctx" in inspect.signature(func).parameters
        self.sandbox_exec = sandbox_exec

        if sandbox_exec and self.needs_ctx:
            raise ValueError(
                f"Tool '{func.__name__}' cannot be sandbox_exec "
                "because it requires 'ctx' parameter"
            )
        
        resolve_name = name or func.__name__
        resolve_desc = desc or (func.__doc__ or "").strip()

        super().__init__(
            name = resolve_name,
            desc = resolve_desc,
            tool_def = tool_def,
            need_confirm = need_confirm,
            confirm_msg_tmpl = confirm_msg_tmpl
        )

        if self._tool_def is None:
            self._tool_def = self._make_def()
    
    async def exec(self, ctx: ExecContext, **kwargs) -> Any:

        if self.needs_ctx:
            result = self.func(ctx=ctx, **kwargs)
        else:
            result = self.func(**kwargs)
        
        if inspect.iscoroutine(result):
            return await result
        else:
            return result
        
    def _make_def(self) -> dict[str, Any]:
        params = func_input_schema(self.func)
        return format_tool_def(self.name, self.desc, params)
    
    def get_source_code(self) -> str:
        if not self.sandbox_exec:
            raise ValueError(f"Tool {self.name} is not marked as sandbox_exec")
        
        source = inspect.getsource(self.func)
        lines = source.split('\n')
        filtered_lines = []
        skip_decorator = False

        for line in lines:
            stripped = line.strip()

            if stripped.startswith('@tool'):
                skip_decorator = True
            
                if '(' not in stripped or ')' in stripped:
                    skip_decorator = False
                continue

            if skip_decorator:
                if ')' in stripped:
                    skip_decorator = False
                continue
            
            filtered_lines.append(line)
        return "\n".join(filtered_lines)


class AgentTool(BaseTool):

    def __init__(self, 
                 agent: Agent, 
                 input_schema: Optional[Type[BaseModel]] = None,
                 need_confirm: bool = False,
                 confirm_msg_tmpl: str = "",
                 ):

        self.agent = agent
        self.input_schema = input_schema

    
        if input_schema:
            params = input_schema.model_json_schema()
            params.pop("$defs", None)
            params.pop("title", None)
        else:
            params = {
                "type": "object",
                "properties": {
                    "request": {
                        "type": "string",
                        "description": "The task or question to delegate"
                    }
                },
                "required": ["request"]
            }
        
        tool_def = format_tool_def(agent.name, agent.desc, params)

        super().__init__(
            name = agent.name,
            desc = agent.desc,
            tool_def = tool_def,
            need_confirm = need_confirm,
            confirm_msg_tmpl = confirm_msg_tmpl
        )

    async def execute(self, ctx: ExecContext, **kwargs) -> Any:
        if self.input_schema:
            validated = self.input_schema.model_validate(kwargs)
            req = validated.model_dump_json(exclude_none=True)
        else:
            req = kwargs.get("request", str(kwargs))
        
        result = await self.agent.ru(req)

        return result.output


def tool(func=None, *, 
         name=None, desc=None, sandbox_exec=False, need_confirm: bool = False, confirm_msg_tmpl: str | None = None):
    
    def decorator(fn):
        return FuncTool(
            func=fn,
            name=name,
            desc=desc,
            sandbox_exec=sandbox_exec,
            need_confirm = need_confirm,
            confirm_msg_tmpl = confirm_msg_tmpl or ""
        )
    
    if func is None:
        return decorator
    else:
        return decorator(func)
