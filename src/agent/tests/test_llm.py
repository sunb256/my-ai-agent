import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.core.model.llm_message import Request  # noqa: E402
from agent.core.llm_client import Client  # noqa: E402
from agent.core.model.types import Message, ToolCall, ToolResult  # noqa: E402


def test_generate_builds_litellm_messages(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    async def fake_completion(**kwargs: Any) -> Any:
        captured.update(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="ok", tool_calls=None)
                )
            ],
            usage=SimpleNamespace(prompt_tokens=3, completion_tokens=2),
        )

    monkeypatch.setattr("agent.core.llm_client.acompletion", fake_completion)
    client = Client(model="openai/test", api_key="secret")
    request = Request(
        system_prompt=["Be concise."],
        contents=[
            Message(role="user", content="Add numbers."),
            ToolCall(
                tool_call_id="call-1",
                name="add_numbers",
                args={"a": 3, "b": 5},
            ),
            ToolResult(
                tool_call_id="call-1",
                name="add_numbers",
                status="success",
                content=[8],
            ),
        ],
    )

    response = asyncio.run(client.call_llm(request))

    assert response.err_msg is None
    assert captured["messages"] == [
        {"role": "system", "content": "Be concise."},
        {"role": "user", "content": "Add numbers."},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call-1",
                    "type": "function",
                    "function": {
                        "name": "add_numbers",
                        "arguments": '{"a": 3, "b": 5}',
                    },
                }
            ],
        },
        {
            "role": "tool",
            "content": "8",
            "tool_call_id": "call-1",
        },
    ]
