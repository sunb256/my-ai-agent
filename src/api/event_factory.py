import json
from ag_ui.core import (
    EventType,
    Interrupt,
    RunAgentInput,
    RunErrorEvent,
    RunFinishedEvent,
    RunFinishedInterruptOutcome,
    RunFinishedSuccessOutcome,
    RunStartedEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    TextMessageStartEvent,
    ToolCallArgsEvent,
    ToolCallEndEvent,
    ToolCallResultEvent,
    ToolCallStartEvent,
)


class EventFactory:
    def __init__(self, input_: RunAgentInput):
        self._input = input_

    @property
    def thread_id(self) -> str:
        return self._input.thread_id

    @property
    def run_id(self) -> str:
        return self._input.run_id

    def run_started(self) -> RunStartedEvent:

        return RunStartedEvent(
            type=EventType.RUN_STARTED,
            thread_id=self.thread_id,
            run_id=self.run_id,
        )

    def run_success(self) -> RunFinishedEvent:

        return RunFinishedEvent(
            type=EventType.RUN_FINISHED,
            thread_id=self.thread_id,
            run_id=self.run_id,
            outcome=RunFinishedSuccessOutcome(),
        )

    def run_interrupt(self, interrupts: list[Interrupt]) -> RunFinishedEvent:
        
        return RunFinishedEvent(
            type=EventType.RUN_FINISHED,
            thread_id=self.thread_id,
            run_id=self.run_id,
            outcome=RunFinishedInterruptOutcome(
                interrupts=interrupts,
            ),
        )

    def run_error(self, message: str, code: str = "agent_error") -> RunErrorEvent:
        
        return RunErrorEvent(
            type=EventType.RUN_ERROR,
            message=message,
            code=code,
        )

    def text_start(self, message_id: str) -> TextMessageStartEvent:
        
        return TextMessageStartEvent(
            type=EventType.TEXT_MESSAGE_START,
            message_id=message_id,
            role="assistant",
        )

    def text_content(self, message_id: str, delta: str) -> TextMessageContentEvent:
        
        return TextMessageContentEvent(
            type=EventType.TEXT_MESSAGE_CONTENT,
            message_id=message_id,
            delta=delta,
        )

    def text_end(self, message_id: str) -> TextMessageEndEvent:
        
        return TextMessageEndEvent(
            type=EventType.TEXT_MESSAGE_END,
            message_id=message_id,
        )
    
    def tool_call_start(self, tool_call_id: str, tool_name: str) -> ToolCallStartEvent:

        return ToolCallStartEvent(
            type=EventType.TOOL_CALL_START,
            tool_call_id=tool_call_id,
            tool_call_name=tool_name,
        )

    def tool_call_args(self, tool_call_id: str, args: dict) -> ToolCallArgsEvent:

        return ToolCallArgsEvent(
            type=EventType.TOOL_CALL_ARGS,
            tool_call_id=tool_call_id,
            delta=json.dumps(args, ensure_ascii=False),
        )

    def tool_call_end(self, tool_call_id: str) -> ToolCallEndEvent:
        
        return ToolCallEndEvent(
            type=EventType.TOOL_CALL_END,
            tool_call_id=tool_call_id,
        )

    def tool_call_result(self, message_id: str, tool_call_id: str, content: str) -> ToolCallResultEvent:

        return ToolCallResultEvent(
            type=EventType.TOOL_CALL_RESULT,
            message_id=message_id,
            tool_call_id=tool_call_id,
            content=content,
            role="tool",
        )