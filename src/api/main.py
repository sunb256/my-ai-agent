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

def _get_service() -> AgentApiService:
    if state.service is None:
        raise HTTPException(status_code=503, detail="Service not initialized.")

    return state.service

@app.get("/healthz")
async def healthz() -> dict[str, bool]:
    return {"ok": True}
    

# simple impl
# @app.post("/agent")
# async def agent_endpoint(req: Request):
#     body = await req.json()
#     input_ = RunAgentInput.model_validate(body)

#     enc = EventEncoder(accept=req.headers.get("accept"))

#     async def event_stream():
#         tid = input_.thread_id
#         rid = input_.run_id
#         mid = "msg_test" 

#         yield enc.encode(RunStartedEvent(type=EventType.RUN_STARTED, thread_id=tid, run_id=rid))
#         yield enc.encode(TextMessageStartEvent(type=EventType.TEXT_MESSAGE_START, message_id=mid, role="assistant"))

#         for char in "AG UI backend connected":
#             yield enc.encode(TextMessageContentEvent(type=EventType.TEXT_MESSAGE_CONTENT, message_id=mid, delta=char))

#         yield enc.encode(TextMessageEndEvent(type=EventType.TEXT_MESSAGE_END, message_id=mid))
#         yield enc.encode(RunFinishedEvent(type=EventType.RUN_FINISHED, thread_id=tid, run_id=rid))
    
#     return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/agent")
async def agent_endpoint(req: Request):
    body = await req.json()
    input_ = RunAgentInput.model_validate(body)

    return StreamingResponse(
        _get_service().stream_agent(
            input_=input_,
            accept=req.headers.get("accept")
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )
