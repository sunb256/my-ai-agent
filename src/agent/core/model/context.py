from datetime import datetime
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Optional
from pydantic import BaseModel

from agent.core.memory.session import Session, BaseSessionManager
from agent.core.model.types import Event, ToolCall

if TYPE_CHECKING:
      from agent.core.memory.long_term import TaskMemoryManager

@dataclass
class ExecContext:

    exec_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    events: list[Event] = field(default_factory=list)
    step: int = 0
    state: dict[str, Any] = field(default_factory=dict)
    final_result: str | BaseModel | None = None

    # session
    session: Session | None = None
    session_manager: BaseSessionManager | None = None
    # long memory
    memory_manager: "TaskMemoryManager | None" = None

    code_env: Optional[Any] = None

    def add_event(self, event: Event):
        self.events.append(event)

        if self.session:
            self.session.update_at = datetime.now()

    def increment(self):
        self.step += 1

    def is_continue(self, max_steps: int) -> bool:
        return self.final_result is None and self.step < max_steps

    @property
    def last_event(self) -> Event | None:
        if not self.events:
            return None

        return self.events[-1]


@dataclass
class AgentResult:
    output: Any
    ctx: ExecContext
    status: str = "complete"  # complete | pending | error
    pending_tc: list = field(default_factory=list)

class PendingToolCall(BaseModel):
    tool_call: ToolCall
    confirm: str

class ToolConfirm(BaseModel):
    tool_call_id: str
    approved: bool
    modified_args: dict | None = None
    

@dataclass(frozen=True)
class AgentStreamTextStart:
    pass

@dataclass(frozen=True)
class AgentStreamTextDelta:
    delta: str

@dataclass(frozen=True)
class AgentStreamTextEnd:
    pass

@dataclass(frozen=True)
class AgentStreamResult:
    result: AgentResult

AgentStreamEvent = (
    AgentStreamTextStart
    | AgentStreamTextDelta
    | AgentStreamTextEnd
    | AgentStreamResult
)