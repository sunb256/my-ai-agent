import asyncio
import logging
from pathlib import Path
from pydantic import BaseModel
from litellm import close_litellm_async_clients

from agent.core.agent import Agent
from agent.core.model.context import AgentResult
from agent.core.workflow.loop import LoopWorkflow
from agent.core.workflow.parallel import ParallelWorkflow
from agent.core.workflow.sequential import SequentialWorkflow
from agent.init import get_client, load_config, load_env
from agent.main import parse_args



args = parse_args()

logging.basicConfig(
      level=logging.INFO if args.verbose else logging.WARNING,
      format="%(asctime)s %(levelname)s %(name)s: %(message)s",
  )


load_env()
config = load_config(Path(args.config))
client = get_client(config)

researcher = Agent(
    client=client,
    role="researcher",
    system_prompt="research the topic and organize key information.",
    is_code_exec=False,
)
editor = Agent(
    client=client,
    role="editor",
    system_prompt="review the writing and improve grammer and readability",
    is_code_exec=False,
)

optimist = Agent(
    client=client,
    role="optimist",
    system_prompt="analyze from a positive perspective, forcusing on opportunities and possibilities",
    is_code_exec=False,
)
pessimist = Agent(
    client=client,
    role="pessimist",
    system_prompt="analyze focusing on risks and potential problems",
    is_code_exec=False,
)
realist = Agent(
    client=client,
    role="realist",
    system_prompt="analyze practival feasibility from a balanced perspective",
    is_code_exec=False,
)

class Review(BaseModel):
    content: str
    score: int
    feedback: str

writer = Agent(
    client=client,
    role="writer",
    system_prompt="write content or improve it based on feedback",
    is_code_exec=False,
)
reviewer = Agent(
    client=client,
    role="reviewer",
    system_prompt="evaluate the writing and provide a score (0-100) with feedback",
    output_type=Review,
    is_code_exec=False,
)

def quality_reached(result: AgentResult, iteration: int) -> bool:
    if isinstance(result.output, Review):
        return result.output.score >= 80
    else:
        return False



workflow = SequentialWorkflow(
    agents = [
        researcher,
        ParallelWorkflow(agents=[optimist, pessimist, realist]),
        LoopWorkflow(agents=[writer, reviewer], 
                     stop_cond=quality_reached,
                     max_iter=2
        ),
        editor
    ]
)



async def main() -> None:
    try:
        result = await workflow.run(
            "write an AI market analysis report。最終回答は日本語で",
            verbose=args.verbose,
        )

        if result.output is None:
            raise RuntimeError(
                "Workflow completed without a final output."
            )

        print(result.output)

    finally:
        await close_litellm_async_clients()


if __name__ == "__main__":
    asyncio.run(main())