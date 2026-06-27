import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from agent.core.model.context import ToolConfirm
from agent.init import DEFAULT_CONFIG, get_agent, get_client, load_config, load_env


class ChatRequest(BaseModel):
    prompt: str
    run_id: str | None = None
    config_path: str | None = None
    max_steps: int | None = None
    verbose: bool = False
    confirms: list[ToolConfirm] | None = None


app = FastAPI(title="my-ai-agent API")
_PENDING_CONTEXTS: dict[str, Any] = {}


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/chat/stream")
async def chat_stream(request: ChatRequest) -> StreamingResponse:
    return StreamingResponse(
        _run_agent_stream(request),
        media_type="application/x-ndjson",
    )


async def _run_agent_stream(request: ChatRequest) -> AsyncIterator[str]:
    try:
        yield _jsonl({"type": "start"})

        load_env()
        config = load_config(Path(request.config_path) if request.config_path else DEFAULT_CONFIG)
        client = get_client(config)
        agent = get_agent(config, client, request.max_steps)
        ctx = _PENDING_CONTEXTS.get(request.run_id) if request.run_id else None

        result = await agent.run(
            "" if ctx is not None and request.confirms else request.prompt,
            ctx=ctx,
            confirm=request.confirms,
            verbose=request.verbose,
        )

        if result.status == "pending":
            _PENDING_CONTEXTS[result.ctx.exec_id] = result.ctx
            yield _jsonl(
                {
                    "type": "pending",
                    "run_id": result.ctx.exec_id,
                    "pending_tool_calls": [
                        {
                            "tool_call_id": pending.tool_call.tool_call_id,
                            "name": pending.tool_call.name,
                            "args": pending.tool_call.args,
                            "confirm": pending.confirm,
                        }
                        for pending in result.pending_tc
                    ],
                }
            )
            return

        _PENDING_CONTEXTS.pop(result.ctx.exec_id, None)
        yield _jsonl({"type": "result", "output": result.output})

    except Exception as error:
        yield _jsonl({"type": "error", "message": str(error)})


def _jsonl(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False) + "\n"
