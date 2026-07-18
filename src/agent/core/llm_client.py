import json
import logging
from typing import Any, Type

from pydantic import BaseModel

from collections.abc import AsyncIterator
from json import JSONDecodeError

from .model.llm_message import LLMResponseDone, LLMStreamEvent, LLMTextDelta

from .helpers.schema import remove_code_fence
from .model.llm_message import Request, Response
from .model.types import Message, ToolCall, ToolResult


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
        if _has_filter(logger):
            continue
        logger.addFilter(log_filter)


def _has_filter(logger: logging.Logger) -> bool:
    return any(
        isinstance(existing, _LiteLLMOptionalProviderWarningFilter)
        for existing in logger.filters
    )


def _load_acompletion():
    _suppress_litellm_optional_provider_warnings()
    from litellm import acompletion

    return acompletion


acompletion = _load_acompletion()


class MessageHelper:

    @staticmethod
    def build_msgs(req: Request) -> list[dict[str, Any]]:
        msgs = list(req.get_system_prompt_msgs())

        for item in req.contents:
            if isinstance(item, Message):
                msgs.append(MessageHelper.message(item))

            elif isinstance(item, ToolCall):
                tool_call = MessageHelper.tool_call_item(item)

                if msgs and msgs[-1]["role"] == "assistant":
                    msgs[-1].setdefault("tool_calls", []).append(tool_call)
                else:
                    msgs.append(
                        {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [tool_call],
                        }
                    )

            elif isinstance(item, ToolResult):
                msgs.append(MessageHelper.tool_result(item))

        return msgs

    @staticmethod
    def message(item: Message) -> dict[str, Any]:
        return {
            "role": item.role,
            "content": item.content,
        }

    @staticmethod
    def tool_call_item(item: ToolCall) -> dict[str, Any]:
        return {
            "id": item.tool_call_id,
            "type": "function",
            "function": {
                "name": item.name,
                "arguments": json.dumps(item.args, ensure_ascii=False),
            },
        }

    @staticmethod
    def tool_call(item: ToolCall) -> dict[str, Any]:
        return {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": item.tool_call_id,
                    "type": "function",
                    "function": {
                        "name": item.name,
                        "arguments": json.dumps(item.args, ensure_ascii=False),
                    },
                }
            ],
        }

    @staticmethod
    def tool_result(item: ToolResult) -> dict[str, Any]:
        return {
            "role": "tool",
            "content": MessageHelper.serialize_tool_result(item.content),
            "tool_call_id": item.tool_call_id,
        }

    @staticmethod
    def serialize_tool_result(content: Any) -> str:
        if content is None:
            return ""

        if isinstance(content, str):
            return content

        return json.dumps(content, ensure_ascii=False, default=str)

class Client:

    def __init__(self, model: str, **config: Any):
        self.model = model
        self.config = config
        
    async def call_llm(self, req: Request) -> Response:
        try:
            kwargs = self._build_kwargs(req)
            response = await acompletion(**kwargs)
            return self._parse_response(response)

        except Exception as error:
            return Response(err_msg=str(error))

    async def stream_llm(self, req: Request) -> AsyncIterator[LLMStreamEvent]:
        try:
            kwargs = self._build_kwargs(req)
            kwargs["stream"] = True

            stream = await acompletion(**kwargs)

            text_parts: list[str] = []
            tool_buffs: dict[int, dict[str, str]] = {}

            async for chunk in stream:
                choice = chunk.choices[0]
                delta = choice.delta

                content = getattr(delta, "content", None)
                if content:
                    text_parts.append(content)
                    yield LLMTextDelta(delta=content)
                
                for item in getattr(delta, "tool_calls", None) or []:
                    idx = getattr(item, "index", 0) or 0
                    buf = tool_buffs.setdefault(idx, {"id": "", "name": "", "arguments": ""})

                    if getattr(item, "id", None):
                        buf["id"] = item.id
                    
                    fn = getattr(item, "function", None)
                    if fn is not None:
                        if getattr(fn, "name", None):
                            buf["name"] = self._merge_tool_name(buf["name"], fn.name)
                        
                        if getattr(fn, "arguments", None):
                            buf["arguments"] += fn.arguments
            
            contents: list[Message | ToolCall | ToolResult] = []

            full = "".join(text_parts)
            if full:
                contents.append(Message(role="assistant", content=full))
                        
            for idx in sorted(tool_buffs):
                buf = tool_buffs[idx]

                name = buf["name"].strip()
                if not name:
                    continue

                try:
                    args = json.loads(buf["arguments"] or "{}")
                except JSONDecodeError:
                    args = {}

                tc = ToolCall(tool_call_id=buf["id"] or f"call_{idx}", name=name, args=args)
                contents.append(tc)


            yield LLMResponseDone(response=Response(content=contents))
        
        except Exception as error:
            yield LLMResponseDone(response=Response(err_msg=str(error)))

    def _build_kwargs(self, req: Request) -> dict[str, Any]:
        msgs = MessageHelper.build_msgs(req)
        tools = [tool.tool_def for tool in req.tools]

        kwargs = {
            "model": self.model,
            "messages": msgs,
            "tools": tools,
            **self.config,
        }

        if req.tool_choice is not None:
            kwargs["tool_choice"] = req.tool_choice
        
        return kwargs

    def _merge_tool_name(self, current: str, chunk: str) -> str:
        if not chunk:
            return current
        if not current:
            return chunk
        if chunk == current or current.endswith(chunk):
            return current

        max_overlap = min(len(current), len(chunk))
        for size in range(max_overlap, 0, -1):
            if current.endswith(chunk[:size]):
                return current + chunk[size:]

        return current + chunk

    def _parse_response(self, res: Any) -> Response:
        """
        # normal call
        [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "通常回答のテキスト",
                    "tool_calls": None,
                },
                "finish_reason": "stop",
            }
        ]

        # tool call
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_xxx",
                    "type": "function",
                    "function": {
                        "name": "add_numbers",
                        "arguments": "{\"a\":3,\"b\":5}",
                    },
                }
            ],
        }
        """

        choice = res.choices[0]
        contents = self._parse_content(choice.message)

        return Response(
            content=contents,
            metadata={
                "input_tokens": res.usage.prompt_tokens,
                "output_tokens": res.usage.completion_tokens,
            },
        )

    def _parse_content(self, message: Any) -> list[Message | ToolCall | ToolResult]:

        contents: list[Message | ToolCall | ToolResult] = []

        # normal call response
        if message.content:
            contents.append(Message(role="assistant", content=message.content))

        if not message.tool_calls:
            return contents

        # tool call response
        for item in message.tool_calls:
            contents.append(
                ToolCall(
                    tool_call_id=item.id,
                    name=item.function.name,
                    args=json.loads(item.function.arguments or "{}"),
                )
            )

        return contents

    async def ask(
        self,
        prompt: str,
        res_format: Type[BaseModel] | None = None,
    ) -> str | BaseModel:
        
        inst = self._ask_inst(prompt, res_format)
        req = Request(
            model_id=self.model,
            system_prompt=[inst],
            contents=[Message(role="user", content="Please respond.")],
        )

        res = await self.call_llm(req)
        if res.err_msg:
            raise RuntimeError(res.err_msg)

        text = self._res_text(res)
        if res_format is None:
            return text

        json_text = self._clean_json(text)
        res = res_format.model_validate_json(json_text)
        print(f"res: {res}")
        return res

    def _ask_inst(self, prompt: str, res_format: Type[BaseModel] | None) -> str:
        if res_format is None:
            return prompt

        schema_text = json.dumps(res_format.model_json_schema())

        return (
            f"{prompt}\n\n"
            f"Respond ONLY with valid JSON matching this schema:\n{schema_text}"
        )

    def _res_text(self, res: Response) -> str:
        for item in res.content:
            if isinstance(item, Message):
                return item.content
        return ""

    def _clean_json(self, text: str) -> str:
        cleaned = text.strip()
        if not cleaned.startswith("```"):
            return cleaned

        cleaned = remove_code_fence(cleaned)
        
        if cleaned.endswith("```"):
            cleaned = cleaned.rsplit("```", 1)[0]
        if cleaned.startswith("json"):
            cleaned = cleaned[4:].lstrip()
        return cleaned.strip()
