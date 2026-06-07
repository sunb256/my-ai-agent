from datetime import datetime

from agent.tool_base import tool


@tool
def get_current_time() -> str:
    """Return the current local datetime."""
    return datetime.now().isoformat(timespec="seconds")


@tool
def add_numbers(a: int, b: int) -> int:
    """Add two integers and return the result."""
    return a + b


APP_TOOLS = [get_current_time, add_numbers]
