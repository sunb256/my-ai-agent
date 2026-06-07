import json
import logging
from typing import Any, Type

from pydantic import BaseModel, Field

from .helpers import remove_code_fence
from .types import ContentItem, Message, ToolCall, ToolResult
from .tool_base import BaseTool

# litellm ワーニング抑制
_LITELLM_OPTIONAL_PROVIDER_WARNINGS = (
    "could not pre-load bedrock-runtime response stream shape",
    "could not pre-load sagemaker-runtime response stream shape",
)

class _LiteLLMOptionalProviderWarningFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        return not any(
            warning in message for warning in _LITELLM_OPTIONAL_PROVIDER_WARNINGS
        )

def _suppress_litellm_optional_provider_warnings() -> None:
    log_filter = _LiteLLMOptionalProviderWarningFilter()
    for logger_name in ("LiteLLM", "litellm"):
        logger = logging.getLogger(logger_name)
        if not any(
            isinstance(existing, _LiteLLMOptionalProviderWarningFilter)
            for existing in logger.filters
        ):
            logger.addFilter(log_filter)

_suppress_litellm_optional_provider_warnings()

from litellm import acompletion  # noqa: E402

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
    usage_metadata: dict[str, Any] = Field(default_factory=dict)

def build_msgs(request: Request) -> list[dict[str, Any]]:
    msgs: list[dict[str, Any]] = []

    for inst in request.insts:
        msgs.append({
            "role": "system", 
            "content": inst
        })
    
    for item in request.contents:
        if isinstance(item, Message):
            msgs.append({
                "role": item.role, 
                "content": item.content
            })
        elif isinstance(item, ToolCall):
            tool_call_dict: dict[str, Any] = {
                "id": item.tool_call_id,
                "type": "function",
                "function": {
                    "name": item.name,
                    "arguments": json.dumps(item.args)
                }
            }
            if msgs and msgs[-1]["role"] == "assistant":
                msgs[-1].setdefault("tool_calls", []).append(tool_call_dict)
            else:
                msgs.append({
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [tool_call_dict] 
                })
        elif isinstance(item, ToolResult):
            msgs.append({
                "role": "tool",
                "content": str(item.content[0]) if item.content else "",
                "tool_call_id": item.tool_call_id,
            })
    
    return msgs

class Client:

    def __init__(self, model: str, **config):
        self.model = model
        self.config = config
    
    async def generate(self, request: Request) -> Response:
        try:
            msgs = build_msgs(request)
            tools = [t.tool_def for t in request.tools]

            res = await acompletion(
                model=self.model,
                messages=msgs,
                tools=tools,
                **({"tool_choice": request.tool_choice} if request.tool_choice else {}),
                **self.config
            )
        
            return self._parse_response(res)
        
        except Exception as e:
            return Response(err_msg=str(e))
        
    async def ask(
          self,
          prompt: str,
          response_format: Type[BaseModel] | None = None) -> str | BaseModel:
        
        if response_format is not None:
            schema_text = json.dumps(response_format.model_json_schema())
            inst = (
                f"{prompt}\n\n"
                f"Respond ONLY with valid JSON matching this schema:\n{schema_text}"
            )
        else:
            inst = prompt
        
        req = Request(
            model_id=self.model,
            insts=[inst],
            contents=[Message(role="user", content="Please respond.")]
        )
        res = await self.generate(req)
        if res.err_msg:
            raise RuntimeError(res.err_msg)

        text = ""
        for item in res.content:
            if isinstance(item, Message):
                text = item.content
                break
        
        if response_format is None:
            return text
        
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = remove_code_fence(cleaned)
            if cleaned.endswith("```"):
                cleaned = cleaned.rsplit("```", 1)[0]
            if cleaned.startswith("json"):
                cleaned = cleaned[4:].lstrip()
        
        # convert pydantic model
        return response_format.model_validate_json(cleaned.strip())

    def _build_msgs(self, request: Request) -> list[dict[str, Any]]:
        return build_msgs(request)
    
    def _parse_response(self, response) -> Response:
        choice = response.choices[0]
        contents: list[ContentItem] = []

        if choice.message.content:
            message = Message(
                role="assistant",
                content=choice.message.content
            )
            contents.append(message)
        
        if choice.message.tool_calls:
            for tc in choice.message.tool_calls:
                tool_call = ToolCall(
                    tool_call_id=tc.id,
                    name=tc.function.name,
                    args=json.loads(tc.function.arguments or "{}")
                )
                contents.append(tool_call)
        
        return Response(
            content=contents,
            usage_metadata={
                "input_tokens": response.usage.prompt_tokens,
                "output_tokens": response.usage.completion_tokens
            }
        )
