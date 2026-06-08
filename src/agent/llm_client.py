import json
import logging
from typing import Any, Type

from pydantic import BaseModel

from .helper_schema import remove_code_fence
from .llm import Request, Response
from .types import Message, ToolCall, ToolResult


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


class Client:
    def __init__(self, model: str, **config: Any):
        self.model = model
        self.config = config
        
    async def call_llm(self, request: Request) -> Response:
        try:
            msgs = self._build_msgs(request)
            tools = [tool.tool_def for tool in request.tools]

            kwargs = {
                "model": self.model,
                "messages": msgs,
                "tools": tools,
                **self.config,
            }

            if request.tool_choice is not None:
                kwargs["tool_choice"] = request.tool_choice

            # call litellm api
            response = await acompletion(**kwargs)
            return self._parse_response(response)

        except Exception as error:
            return Response(err_msg=str(error))

    def _build_msgs(self, request: Request) -> list[dict[str, Any]]:
        msgs = request.get_system_prompt_msgs()

        for item in request.contents:
            if isinstance(item, Message):
                msgs.append(self._message(item))
            elif isinstance(item, ToolCall):
                msgs.append(self._tool_call(item))
            elif isinstance(item, ToolResult):
                msgs.append(self._tool_result(item))

        return msgs

    def _message(self, item: Message) -> dict[str, Any]:
        return {
                  "role": item.role, 
                  "content": item.content
                }

    def _tool_call(self, item: ToolCall) -> dict[str, Any]:
        return {
                  "role": "assistant",
                  "content": None,
                  "tool_calls": [
                      {
                          "id": item.tool_call_id,
                          "type": "function",
                          "function": {
                              "name": item.name,
                              "arguments": json.dumps(item.args),
                          },
                      }
                  ],
                }

    def _tool_result(self, item: ToolResult) -> dict[str, Any]:
        return {
                  "role": "tool",
                  "content": str(item.content[0]) if item.content else "",
                  "tool_call_id": item.tool_call_id,
                }

    def _parse_response(self, response: Any) -> Response:
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

        choice = response.choices[0]
        contents = self._parse_content(choice.message)

        return Response(
            content=contents,
            metadata={
                "input_tokens": response.usage.prompt_tokens,
                "output_tokens": response.usage.completion_tokens,
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
        response_format: Type[BaseModel] | None = None,
    ) -> str | BaseModel:
        
        inst = self._ask_inst(prompt, response_format)
        req = Request(
            model_id=self.model,
            system_prompt=[inst],
            contents=[Message(role="user", content="Please respond.")],
        )

        res = await self.call_llm(req)
        if res.err_msg:
            raise RuntimeError(res.err_msg)

        text = self._response_text(res)
        if response_format is None:
            return text

        json_text = self._clean_json(text)
        aaa = response_format.model_validate_json(json_text)
        print(f"aaa: {aaa}")
        return aaa

    def _ask_inst(self, prompt: str, response_format: Type[BaseModel] | None) -> str:
        if response_format is None:
            return prompt

        schema_text = json.dumps(response_format.model_json_schema())

        return (
            f"{prompt}\n\n"
            f"Respond ONLY with valid JSON matching this schema:\n{schema_text}"
        )

    def _response_text(self, response: Response) -> str:
        for item in response.content:
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
