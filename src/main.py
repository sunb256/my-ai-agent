from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml  # type: ignore[import-untyped]

from agent.tool_base import tool

if TYPE_CHECKING:
    from agent.agent import Agent
    from agent.llm import Client


ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT_DIR / "src" / "config.yml"
DEFAULT_ENV = ROOT_DIR / ".env"
API_KEY_NAME = "OPENAI_API_KEY"


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


def load_env(path: Path = DEFAULT_ENV) -> None:
    if not path.exists():
        return

    for line in path.read_text(encoding="utf-8").splitlines():
        key, value = parse_env_line(line)
        if key and key not in os.environ:
            os.environ[key] = value


def parse_env_line(line: str) -> tuple[str | None, str]:
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in stripped:
        return None, ""

    key, value = stripped.split("=", 1)
    return key.strip(), value.strip().strip("\"'")


def load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(config_help(path))

    with path.open(encoding="utf-8") as file:
        data = yaml.safe_load(file) or {}

    if not isinstance(data, dict):
        raise ValueError("config.yml must contain a YAML object.")

    return data


def config_help(path: Path) -> str:
    return (
        f"Config file not found: {path}\n"
        "Create src/config.yml with llm.model, llm.base_url, and agent settings."
    )


def build_client(config: dict[str, Any]) -> Client:
    llm = get_map(config, "llm")
    model = require_text(llm, "model", "llm.model")
    base_url = require_text(llm, "base_url", "llm.base_url")
    api_key = require_api_key()

    options: dict[str, Any] = {"base_url": base_url, "api_key": api_key}
    if "temperature" in llm:
        options["temperature"] = llm["temperature"]

    from agent.llm import Client

    return Client(model=model, **options)


def get_map(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key) or {}
    if isinstance(value, dict):
        return value
    raise ValueError(f"Config section must be an object: {key}")


def require_text(data: dict[str, Any], key: str, label: str) -> str:
    value = data.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    raise ValueError(f"Missing required config value: {label}")


def require_api_key() -> str:
    api_key = os.environ.get(API_KEY_NAME)
    if api_key:
        return api_key
    raise ValueError(f"Set {API_KEY_NAME} in .env or your shell environment.")


def build_agent(config: dict[str, Any], client: Client, max_steps: int | None) -> Agent:
    agent_cfg = get_map(config, "agent")
    steps = max_steps if max_steps is not None else int(agent_cfg.get("max_steps", 5))

    from agent.agent import Agent

    return Agent(
        model=client,
        tools=[get_current_time, add_numbers],
        insts=str(agent_cfg.get("instructions", "")),
        max_steps=steps,
        name=str(agent_cfg.get("name", "sample-agent")),
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
