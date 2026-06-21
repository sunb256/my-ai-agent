from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field
from agent.types import Event

class Session(BaseModel):

    session_id: str
    user_id: str | None = None
    events: list[Event] = Field(default_factory=list)
    state: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.now)
    update_at: datetime = Field(default_factory=datetime.now)


class BaseSessionManager(ABC):

    @abstractmethod
    async def create(self, session_id: str, user_id: str | None = None) -> Session:
        pass

    @abstractmethod
    async def get(self, session_id: str) -> Session | None:
        pass

    @abstractmethod
    async def save(self, session: Session) -> None:
        pass

    async def get_or_create(self, session_id: str, user_id: str | None = None) -> Session:

        session = await self.get(session_id)
        if session is None:
            session = await self.create(session_id, user_id)
        
        return session
    
class InMemorySessionManager(BaseSessionManager):

    def __init__(self):
        self._sessions: dict[str, Session] = {}
    
    async def create(self, session_id: str, user_id: str | None = None) -> Session:

        if session_id in self._sessions:
            raise ValueError(f"Session {session_id} already exists")

        session = Session(session_id=session_id, user_id=user_id)
        self._sessions[session_id] = session
        return session
    
    async def get(self, session_id: str) -> Session | None:
        return self._sessions.get(session_id)
    
    async def save(self, session: Session) -> None:
        self._sessions[session.session_id] = session


