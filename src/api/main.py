from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from ag_ui.core import RunAgentInput

from agent.core.memory.session import InMemorySessionManager
from agent.init import DEFAULT_CONFIG, get_agent, get_client, load_config, load_env

from .service import AgentApiService

@dataclass
class State:
    service: AgentApiService | None = None

state = State()

@asynccontextmanager
async def lifespan(_: FastAPI):
    load_env()
    config = load_config(Path(DEFAULT_CONFIG))
    client = get_client(config)
    session_manager = InMemorySessionManager()

    agent = get_agent(
        config=config,
        client=client,
        max_steps=None,
        session_manager=session_manager,
    )

    state.service = AgentApiService(agent)

    try:
        yield
    finally:
        state.service = None
    
app = FastAPI(title="ai-agent-api", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _get_stream_agent(req: Request, input_: RunAgentInput) -> AgentApiService:
    if state.service is None:
        raise HTTPException(status_code=503, detail="Service not initialized.")

    accept = req.headers.get("accept")
    agent = state.service.stream_agent(input_=input_, accept=accept)
    return agent

@app.get("/healthz")
async def healthz() -> dict[str, bool]:
    return {"ok": True}
    
@app.post("/agent")
async def agent_endpoint(req: Request):

    body = await req.json()
    input_ = RunAgentInput.model_validate(body)
    stream_agent = _get_stream_agent(req, input_)

    return StreamingResponse(
        stream_agent,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )
