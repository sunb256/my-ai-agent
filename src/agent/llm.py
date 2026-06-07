from typing import Any

from pydantic import BaseModel, Field

from .tool_base import BaseTool
from .types import ContentItem


class Request(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    insts: list[str] = Field(default_factory=list)
    contents: list[ContentItem] = Field(default_factory=list)
    tools: list[BaseTool] = Field(default_factory=list)
    tool_choice: str | None = None
    model_id: str | None = None

    def append_insts(self, text: str) -> None:
        self.insts.append(text)


class Response(BaseModel):
    content: list[ContentItem] = Field(default_factory=list)
    err_msg: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
