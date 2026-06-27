import os
import json
import inspect
from .model.tool_base import tool
from .model.context import ExecContext

def _wrap_python_code(code: str) -> str:
    SANDBOX_TOOLS_DIR = "/tmp"
    return (
         "import sys\n"
        f"sys.path.insert(0, {SANDBOX_TOOLS_DIR!r})\n"
         "try:\n"
         "    from sandbox_tools import *\n"
         "except ModuleNotFoundError:\n"
         "    pass\n\n"
        f"{code}"
    )

@tool(
    name="exec_python",
    desc="Execute Python code in a sandboxed environment. "
         "Use this to perform calculations, data processing, or any Python operations."
)
async def exec_python(ctx: ExecContext, code:str):

    if ctx.code_env is None:
        raise RuntimeError("no code execution environment available")
    
    sandbox = ctx.code_env
    source = _wrap_python_code(code)
    print(f"llm generatied source code:\n\n```{source}\n```")

    try:
        result = sandbox.exec("python", ["-c", source], timeout=30.0)
        if inspect.isawaitable(result):
            result = await result

        return json.dumps(
            {
                "stdout": result.stdout_text,
                "stderr": result.stderr_text,
                "exit_code": result.exit_code,
                "ok": result.exit_code == 0,
            },
            indent=2,
            ensure_ascii=False,
        )
    
    except Exception as e:
        return json.dumps(
            {
                "stdout": "",
                "stderr": str(e),
                "exit_code": None,
                "ok": False,
            },
            indent=2,
            ensure_ascii=False,
        )


@tool(name="bash_tool", desc="Execute a bash command in a sandboxed environment.")
async def bash_tool(ctx: ExecContext, command:str):

    if ctx.code_env is None:
        raise RuntimeError("no code execution environment available")
    
    sandbox = ctx.code_env

    try:
        result = sandbox.exec("bash", ["-lc", command], timeout=30.0)
        if inspect.isawaitable(result):
            result = await result
        
        output_parts: list[str] = []

        if result.stdout_text:
            output_parts.append(f"[stdout]\n{result.stdout_text.rstrip()}")

        if result.stderr_text:
            output_parts.append(f"[stderr]\n{result.stderr_text.rstrip()}")

        output_parts.append(f"[exit_code] {result.exit_code}")
        
        if output_parts:
            return "\n\n".join(output_parts)
        else:
            return "[No output]"

    except Exception as e:
        return f"Command error: {str(e)}"


@tool
async def upload_file(ctx: ExecContext, local_path: str, sandbox_path: str = None) -> str:

    sandbox = ctx.code_env
    if sandbox is None:
        return "no code execution environment available"
    
    if sandbox_path is None:
        sandbox_path = f"/tmp/{os.path.basename(local_path)}"

    try:
        result = sandbox.fs.copy_from_host(local_path, sandbox_path)
        if inspect.isawaitable(result):
            await result
        return f"file uploaded to {sandbox_path}"

    except Exception as e:
        return f"upload error: {str(e)}"
