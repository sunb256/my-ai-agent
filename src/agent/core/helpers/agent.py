from typing import Any

from agent.core.helpers.const import ASSISTANT, STR_SUCCESS
from agent.core.model.types import Event, Message, ToolCall, ToolResult


def is_final_by_output_tool(event: Event, output_tool_name: str) -> bool:
    """
    output_tool_name が指定されている場合:
    指定された output tool が success で返ったら final response とみなす。
    """

    for item in event.content:
        if not isinstance(item, ToolResult):
            continue

        if item.name == output_tool_name and \
           item.status == STR_SUCCESS:
            return True

    return False


def is_final_by_plain_message(event: Event) -> bool:
    """
    output_tool_name が指定されていない場合:
    tool call / tool result を含まない通常メッセージなら final response とみなす。
    """

    for item in event.content:
        if isinstance(item, ToolCall):
            return False

        if isinstance(item, ToolResult):
            return False

    return True


def get_final_by_output_tool(event: Event, output_tool_name: str) -> Any:
    for item in event.content:
        if not isinstance(item, ToolResult):
            continue

        if item.name != output_tool_name:
            continue

        if item.status != STR_SUCCESS:
            continue

        if not item.content:
            continue

        return item.content[0]

    return None


def get_final_by_plain_message(event: Event) -> Any:
    for item in event.content:
        if not isinstance(item, Message):
            continue

        if item.role != ASSISTANT:
            continue

        return item.content

    return None
