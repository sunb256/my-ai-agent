from typing import List
import logging

from agent.core.agent import Agent
from agent.core.model.context import AgentResult, ExecContext
from agent.core.workflow.base import WorkflowBase


logger = logging.getLogger(__name__)

class SequentialWorkflow(WorkflowBase):

    def __init__(self, agents: List[Agent], 
                 name: str = "sequential_workflow"):
        
        self.agents = agents
        self.name= name

    async def run(self, prompt: str | None = None,
                  ctx: ExecContext | None = None,
                  verbose: bool = False,
                  **kwargs,) -> AgentResult:
        
        if ctx is None:
            ctx = ExecContext()
        
        result = None

        for i, agent in enumerate(self.agents, start=1):
       
            if ctx is not None:
                ctx.final_result = None
                ctx.step = 0
            
            if verbose:
                logger.info(f"[{self.name}] start {self.label(agent)} ({i}/{len(self.agents)})")

            prompt2 = self.next_prompt(prompt, is_first=i == 1)
            result = await agent.run(prompt=prompt2, ctx=ctx, verbose=verbose)
            ctx = result.ctx
        
            if verbose:
                logger.info(f"[{self.name}] complete {self.label(agent)}, output={self.log_output(result.output)}")

        if result is None:
            raise RuntimeError("SequentialWorkflow requires at least one agent.")

        return result




