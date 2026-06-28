from typing import Any, Literal

from pydantic import BaseModel, Field

from agent.core.model.tool_base import BaseTool
from agent.core.model.types import ContentItem, ToolCall


class Request(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    system_prompt: list[str] = Field(default_factory=list)
    contents: list[ContentItem] = Field(default_factory=list)
    tools: list[BaseTool] = Field(default_factory=list)
    tool_choice: str | None = None
    model_id: str | None = None

    def append_prompt(self, text: str) -> None:
        self.system_prompt.append(text)

    def get_system_prompt_msgs(self) -> list[str]:
         return [{"role": "system", "content": prompt} for prompt in self.system_prompt]

class Response(BaseModel):
    content: list[ContentItem] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    err_msg: str | None = None

    @property
    def tool_calls(self):
        return [tc for tc in self.content if isinstance(tc, ToolCall)]


class LLMTextDelta(BaseModel):
    type: Literal["text_delta"] = "text_delta"
    delta: str

class LLMResponseDone(BaseModel):
    type: Literal["done"] = "done"
    response: Response

LLMStreamEvent = LLMTextDelta | LLMResponseDone