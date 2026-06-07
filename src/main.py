import argparse
import asyncio
import sys
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from init import DEFAULT_CONFIG, load_config, load_env, resolve_agent_settings
from init import resolve_llm_settings
from agent.tool_base import tool

if TYPE_CHECKING:
    from agent.agent import Agent
    from agent.llm import Client


@tool
def get_current_time() -> str:
    """Return the current local datetime."""
    return datetime.now().isoformat(timespec="seconds")


@tool
def add_numbers(a: int, b: int) -> int:
    """Add two integers and return the result."""
    return a + b


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the sample AI agent.")
    parser.add_argument("prompt", nargs="*", help="User prompt to send once.")
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG),
        help="Config YAML path.",
    )
    parser.add_argument("--verbose", action="store_true", help="Log agent responses.")
    parser.add_argument(
        "--max-steps",
        type=int,
        default=None,
        help="Override max steps.",
    )
    return parser.parse_args()


def build_client(config: dict[str, Any]) -> Client:
    model, options = resolve_llm_settings(config)

    from agent.llm import Client

    return Client(model=model, **options)


def build_agent(config: dict[str, Any], client: Client, max_steps: int | None) -> Agent:
    settings = resolve_agent_settings(config, max_steps)

    from agent.agent import Agent

    return Agent(
        model=client,
        tools=[get_current_time, add_numbers],
        insts=settings["instructions"],
        max_steps=settings["max_steps"],
        name=settings["name"],
    )


async def run_once(agent: Agent, prompt: str, verbose: bool) -> None:
    result = await agent.run(prompt, verbose=verbose)
    if result.output is None:
        raise RuntimeError(
            "Agent finished without output. Check max_steps or model response."
        )
    print(result.output)


async def run_repl(agent: Agent, verbose: bool) -> None:
    print("Enter a prompt. Press Ctrl-D or submit an empty line to exit.")
    while True:
        try:
            prompt = input("> ").strip()
        except EOFError:
            print()
            return

        if not prompt:
            return
        await run_once(agent, prompt, verbose)


async def async_main() -> int:
    args = parse_args()
    try:
        load_env()
        config = load_config(Path(args.config))
        client = build_client(config)
        agent = build_agent(config, client, args.max_steps)
        prompt = " ".join(args.prompt).strip()
        if prompt:
            await run_once(agent, prompt, args.verbose)
        else:
            await run_repl(agent, args.verbose)
        return 0
    except (RuntimeError, ValueError, FileNotFoundError, KeyboardInterrupt) as error:
        print(error, file=sys.stderr)
        return 1


def main() -> None:
    raise SystemExit(asyncio.run(async_main()))


if __name__ == "__main__":
    main()
