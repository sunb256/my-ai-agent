import argparse
import asyncio
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from init import DEFAULT_CONFIG, get_agent, get_client, load_config, load_env

if TYPE_CHECKING:
    from agent.agent import Agent


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


async def run_once(agent: Agent, prompt: str, verbose: bool) -> None:
    
    result = await agent.run(prompt, verbose=verbose)
    if result.output is not None:
        print(result.output)
        return

    raise RuntimeError("Agent finished without output. Check max_steps or model response.")


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
        client = get_client(config)
        agent = get_agent(config, client, args.max_steps)
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
