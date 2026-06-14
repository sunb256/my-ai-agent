import uuid
from dataclasses import dataclass, field
from typing import Any, Optional
from pydantic import BaseModel

from .types import Event

@dataclass
class ExecContext:

    exec_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    events: list[Event] = field(default_factory=list)
    step: int = 0
    state: dict[str, Any] = field(default_factory=dict)
    final_result: str | BaseModel | None = None

    code_env: Optional[Any] = None

    def add_event(self, event: Event):
        self.events.append(event)

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
