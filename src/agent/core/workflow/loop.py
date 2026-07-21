
from typing import Callable, List
import logging

from agent.core.agent import Agent
from agent.core.model.context import AgentResult, ExecContext
from agent.core.workflow.base import WorkflowBase

StopCondition = Callable[[AgentResult, int], bool]

logger = logging.getLogger(__name__)

class LoopWorkflow(WorkflowBase):

    def __init__(self, 
                 agents: List[Agent],
                 stop_cond: StopCondition | None = None,
                 max_iter: int = 10,
                 name: str = "loop_workflow"):
        self.agents = agents
        self.stop_cond = stop_cond
        self.max_iter = max_iter
        self.name = name

    async def run(self, prompt: str | None = None,
                  ctx: ExecContext | None = None,
                  verbose: bool = False,
                  **kwargs,) -> AgentResult:
        
        if ctx is None:
            ctx = ExecContext()
        
        result = None
        is_first_agent = True

        for iter_ in range(1, self.max_iter + 1):

            if verbose:
                logger.info(f"[{self.name}] iteration {iter_}/{self.max_iter}")

            for agent in self.agents:
            
                if ctx is not None:
                    ctx.final_result = None
                    ctx.step = 0
                
                if verbose:
                    logger.info(f"[{self.name}] start {self.label(agent)}")

                prompt2 = self.next_prompt(prompt, is_first=is_first_agent)
                result = await agent.run(prompt=prompt2, ctx=ctx, verbose=verbose)
                is_first_agent = False

                ctx = result.ctx

                if verbose:
                    logger.info(f"[{self.name}] complete {self.label(agent)}")

            if self._is_stop(result, iter_):
                if verbose:
                    logger.info(f"[{self.name}] stop condition reached at iteration {iter_}")
                break

        if result is None:
            raise RuntimeError("LoopWorkflow requires at least one agent.")

        return result

    def _is_stop(self, result, iter_):
        if result and self.stop_cond and self.stop_cond(result, iter_):
            return True
        else:
            return False