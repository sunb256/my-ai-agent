import os
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]


ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT_DIR / "src" / "config.yml"
DEFAULT_ENV = ROOT_DIR / ".env"
API_KEY_NAME = "OPENAI_API_KEY"


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


def resolve_llm_settings(config: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    llm = get_map(config, "llm")
    model = require_text(llm, "model", "llm.model")
    base_url = require_text(llm, "base_url", "llm.base_url")
    options: dict[str, Any] = {
        "base_url": base_url,
        "api_key": require_api_key(),
    }

    if "temperature" in llm:
        options["temperature"] = llm["temperature"]

    return model, options


def resolve_agent_settings(
    config: dict[str, Any], max_steps: int | None
) -> dict[str, Any]:
    agent = get_map(config, "agent")
    steps = max_steps if max_steps is not None else int(agent.get("max_steps", 5))

    return {
        "name": str(agent.get("name", "sample-agent")),
        "instructions": str(agent.get("instructions", "")),
        "max_steps": steps,
    }
