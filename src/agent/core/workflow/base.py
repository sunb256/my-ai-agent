import logging
from typing import Any, List

from agent.core.agent import Agent

logger = logging.getLogger(__name__)


class WorkflowBase(Agent):

    HANDOFF_PROMPT = (
        "Continue the workflow using all previous results in the conversation. "
        "Perform your assigned role and return a complete result for the next stage."
    )

    def __init__(self, agents: List[Agent], name: str = "workflow",):
        self.agents = agents
        self.name = name

    def label(self, agent: Agent) -> str:
        return (
            getattr(agent, "role", None)
            or getattr(agent, "name", None)
            or type(agent).__name__
        )
    
    def next_prompt(self, initial_prompt: str | None, is_first: bool,) -> str | None:
        if is_first:
            return initial_prompt

        if not initial_prompt:
            return self.HANDOFF_PROMPT

        return (
            f"{self.HANDOFF_PROMPT}\n\n"
            f"Task:\n{initial_prompt}"
        )

    def log_output(self, output: Any, max_length: int = 500) -> str:
        text = repr(output)
        if len(text) <= max_length:
            return text

        return f"{text[:max_length]}..."