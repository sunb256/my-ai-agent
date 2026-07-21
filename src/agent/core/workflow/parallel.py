import asyncio
import copy
import logging
from typing import List

from agent.core.agent import Agent
from agent.core.model.context import AgentResult, ExecContext
from agent.core.workflow.base import WorkflowBase

logger = logging.getLogger(__name__)

class ParallelWorkflow(WorkflowBase):

    def __init__(self, agents: List[Agent], name: str = "parallel_workflow",):
        self.agents = agents
        self.name = name

    async def run(self, prompt: str | None = None,
                  ctx: ExecContext | None = None,
                  verbose: bool = False,
                  **kwargs,) -> AgentResult:
        
        if ctx is None:
            ctx = ExecContext()

        event_cnt = len(ctx.events)

        
        agent_ctx = self._get_agent_ctx(self.agents, ctx)
        agent_tasks = self._get_agent_tasks(self.agents, agent_ctx, prompt, verbose)

        results = await asyncio.gather(*agent_tasks)

        # combine output
        outputs = "\n\n".join(
            f"[{agent.role}]\n{result.output}"
            for agent, result in zip(self.agents, results)
        )

        # combine events
        merged_ctx = ExecContext()
        
        for event in ctx.events:
            merged_ctx.add_event(event)

        has_user_event = any(
            event.user == "user"
            for event in merged_ctx.events
        )

        for result in results:

            new_events = result.ctx.events[event_cnt:]

            for event in new_events:
                if event.user == "user":
                    if not has_user_event:
                        merged_ctx.add_event(event)
                        has_user_event = True
                else:
                    merged_ctx.add_event(event)
        
        if not result:
            raise RuntimeError("ParallelWorkflow requires at least one agent.")

        return AgentResult(output=outputs, ctx=merged_ctx)
        
        
    def _get_agent_ctx(self, agents: list[Agent], ctx: ExecContext,) -> list[ExecContext]:
        
        return [
            ExecContext(
                exec_id=ctx.exec_id,
                events=[
                    event.model_copy(deep=True)
                    for event in ctx.events
                ],
                step=ctx.step,
                state=copy.deepcopy(ctx.state),
                final_result=None,
                session=ctx.session,
                session_manager=ctx.session_manager,
                memory_manager=ctx.memory_manager,
                code_env=None,
            )
            for _ in agents
        ]
    
    def _get_agent_tasks(
        self,
        agents: list[Agent],
        agent_ctxs: list[ExecContext],
        prompt: str | None,
        verbose: bool,
    ):
        return [
            self._run_agent(agent, agent_ctx, prompt, verbose)
            for agent, agent_ctx in zip(agents, agent_ctxs)
        ]

    async def _run_agent(
        self,
        agent: Agent,
        ctx: ExecContext,
        prompt: str | None,
        verbose: bool,
    ) -> AgentResult:

        if verbose:
            logger.info(f"[{self.name}] start {self.label(agent)}")

        result = await agent.run(
            prompt=prompt,
            ctx=ctx,
            verbose=verbose,
        )

        if verbose:
            logger.info(f"[{self.name}] complete {self.label(agent)}")

        return result
