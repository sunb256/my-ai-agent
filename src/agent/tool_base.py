import inspect
from abc import ABC, abstractmethod
from typing import Any, Callable

from .helper_schema import func_input_schema, format_tool_def
from .context import ExecContext

class BaseTool(ABC):

    def __init__(self,
                 name: str | None = None,
                 desc: str | None = None,
                 tool_def: dict[str, Any] | None = None):
    
        self.name = name or self.__class__.__name__
        self.desc = desc or self.__doc__ or ""
        self._tool_def = tool_def
    
    @property
    def tool_def(self) -> dict[str, Any] | None:
        return self._tool_def
    
    @abstractmethod
    async def exec(self, ctx: ExecContext, **kwargs) -> Any:
        pass

    async def __call__(self, ctx: ExecContext, **kwargs) -> Any:
        return await self.exec(ctx, **kwargs)
    

class FuncTool(BaseTool):

    def __init__(self,
                 func: Callable,
                 name: str | None = None,
                 desc: str | None = None,
                 tool_def: dict[str, Any] | None = None,
                 sandbox_exec: bool = False):
    
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
            tool_def = tool_def
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
    
def tool(func=None, *, name=None, desc=None, sandbox_exec=False):
    def decorator(fn):
        return FuncTool(
            func=fn,
            name=name,
            desc=desc,
            sandbox_exec=sandbox_exec
        )
    
    if func is None:
        return decorator
    else:
        return decorator(func)
