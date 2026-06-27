from datetime import datetime

from agent.core.model.tool_base import tool


@tool
def get_current_time() -> str:
    """Return the current local datetime."""
    return datetime.now().isoformat(timespec="seconds")


@tool
def add_numbers(a: int, b: int) -> int:
    """Add two integers and return the result."""
    return a + b


@tool(need_confirm=True, confirm_msg_tmpl="Delete file {args}?")
def delete_file(filepath: str) -> str:
    """Deletes a file. This action cannot be undone."""
    return f"File {filepath} has been deleted."

APP_TOOLS = [get_current_time, add_numbers, delete_file]
