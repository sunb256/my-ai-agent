from typing import Any
from pydantic import AliasChoices, BaseModel, ConfigDict, Field

class ToolConfirmPayload(BaseModel):
    id: str = Field(validation_alias=AliasChoices("id", "tool_call_id"))
    approved: bool
    modified_args: dict[str, Any] | None = None

class ChatRunRequest(BaseModel):
    # assistant-ui runtime 方法 の fields を許可
    model_config = ConfigDict(extra="allow")

    messages: list[dict[str, Any]] = Field(default_factory=list)
    # 互换のため残す（messages優先にしたければ service 側で制御）
    prompt: str | None = None
    session_id: str | None = None
    verbose: bool = False

class ResumeRunRequest(BaseModel):
    confirm: list[ToolConfirmPayload] = Field(min_length=1)
    verbose: bool = False