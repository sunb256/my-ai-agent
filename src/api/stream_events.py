import json
from typing import Any, Literal

FinishReason = Literal["stop", "tool-calls", "error", "unknown"]

def _line(chunk_type: str, value: Any) -> str:
    # Data Stream Protocol line format: "<type><json>\n"
    return f"{chunk_type}:{json.dumps(value, ensure_ascii=False)}\n"

def ds_text_delta(text: str) -> str:
    return _line("0", text)

def ds_error(message: str) -> str:
    return _line("3", message)

def ds_start_tool_call(tool_call_id: str, tool_name: str, parent_id: str | None = None) -> str:
    payload: dict[str, Any] = {
        "toolCallId": tool_call_id,
        "toolName": tool_name,
    }

    if parent_id:
        payload["parentId"] = parent_id
    return _line("0", payload)
    
def ds_tool_call_args_delta(tool_call_id: str, args_text_delta: str) -> str:
    return _line(
        "c",
        {
            "toolCallId": tool_call_id,
            "argsTextDelta": args_text_delta,
        },
    )

def ds_finish_message(
    finish_reason: FinishReason = "stop",
    input_tokens: int = 0,
    output_tokens: int = 0,
) -> str:

    return _line(
        "d",
        {
            "finishReason": finish_reason,
            "usage": {
                "inputTokens": input_tokens,
                "outputTokens": output_tokens,
            }
        },
    )