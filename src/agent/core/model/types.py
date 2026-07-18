import uuid
from typing import Literal, Any
from pydantic import BaseModel, Field
from datetime import datetime

from agent.core.helpers.const import STR_ERROR, ToolStatus

class Message(BaseModel):
    type: Literal["message"] = "message"
    role: Literal["system", "user", "assistant"]
    content: str

class ToolCall(BaseModel):
    type: Literal["tool_call"] = "tool_call"
    tool_call_id: str
    name: str
    args: dict

class ToolResult(BaseModel):
    type: Literal["tool_result"] = "tool_result"
    tool_call_id: str
    name: str
    status: ToolStatus
    content: Any = None

    @classmethod
    def new(cls, tool_call: ToolCall, status: ToolStatus, content: Any = None) -> "ToolResult":
    
        if status == STR_ERROR and content is None:
            content = f"Unknown tool: {tool_call.name}"

        return cls(
            tool_call_id=tool_call.tool_call_id,
            name=tool_call.name,
            status=status,
            content=content,
        )


# 種別
ContentItem = Message | ToolCall | ToolResult

class Event(BaseModel):
    # インスタンスごとに新しいIDを付ける
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    exec_id: str
    timestamp: float = Field(default_factory=lambda: datetime.now().timestamp())
    user: str
    content: list[ContentItem] = Field(default_factory=list)
    
    @classmethod
    def new_msg(cls, id, user, user_input):
        event = Event(
                exec_id=id,
                user=user,
                content=[Message(role=user, content=user_input)],
        )
        return event
    
    @classmethod
    def new(cls, id: str, user: str, content: list[ContentItem]):
        event = Event(
            exec_id=id,
            user=user,
            content=content
        )
        return event
