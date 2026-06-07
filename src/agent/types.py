import uuid
from typing import Literal
from pydantic import BaseModel, Field
from datetime import datetime

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
    status: Literal["success", "error"]
    content: list

# 種別
ContentItem = Message | ToolCall | ToolResult

class Event(BaseModel):
    # インスタンスごとに新しいIDを付ける
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    exec_id: str
    timestamp: float = Field(default_factory=lambda: datetime.now().timestamp())
    author: str
    content: list[ContentItem] = Field(default_factory=list)
    
