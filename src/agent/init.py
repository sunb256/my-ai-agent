import os
from pathlib import Path
from typing import Any, Callable

import yaml  # type: ignore[import-untyped]

from agent.core.agent import Agent
from agent.core.callbacks import search_compress
from agent.core.tools.app_tools import APP_TOOLS
from agent.core.llm_client import Client
from agent.core.memory.context_optimizer import ContextOptimizer
from agent.core.memory.session import BaseSessionManager


ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = Path(__file__).resolve().parent / "config" / "config.yml"
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


def env_value(name: str) -> str | None:
    value = os.environ.get(name)
    if value is None:
        return None

    stripped = value.strip()
    return stripped or None


def ensure_config_section(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key)
    if value is None:
        section: dict[str, Any] = {}
        data[key] = section
        return section

    if isinstance(value, dict):
        return value

    raise ValueError(f"Config section must be an object: {key}")


def parse_bool(value: str, label: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False

    raise ValueError(f"{label} must be a boolean value.")


def apply_env_overrides(data: dict[str, Any]) -> dict[str, Any]:
    llm_model = env_value("LLM_MODEL")
    llm_base_url = env_value("LLM_BASE_URL")
    llm_temperature = env_value("LLM_TEMPERATURE")

    if llm_model or llm_base_url or llm_temperature:
        llm = ensure_config_section(data, "llm")

        if llm_model:
            llm["model"] = llm_model

        if llm_base_url:
            llm["base_url"] = llm_base_url

        if llm_temperature:
            try:
                llm["temperature"] = float(llm_temperature)
            except ValueError as error:
                raise ValueError("LLM_TEMPERATURE must be a number.") from error

    agent_code_exec = env_value("AGENT_CODE_EXEC")
    agent_code_exec_image = env_value("AGENT_CODE_EXEC_IMAGE")
    agent_code_exec_runtime = env_value("AGENT_CODE_EXEC_RUNTIME")
    agent_skills_dir = env_value("AGENT_SKILLS_DIR")

    if agent_code_exec or agent_code_exec_image or agent_code_exec_runtime or agent_skills_dir:
        agent = ensure_config_section(data, "agent")

        if agent_code_exec:
            agent["code_exec"] = parse_bool(agent_code_exec, "AGENT_CODE_EXEC")

        if agent_code_exec_image:
            agent["code_exec_image"] = agent_code_exec_image

        if agent_code_exec_runtime:
            agent["code_exec_runtime"] = agent_code_exec_runtime

        if agent_skills_dir:
            agent["skills_dir"] = agent_skills_dir

    return data


def load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(config_help(path))

    with path.open(encoding="utf-8") as file:
        data = yaml.safe_load(file) or {}

    if not isinstance(data, dict):
        raise ValueError("config.yml must contain a YAML object.")

    return apply_env_overrides(data)


def config_help(path: Path) -> str:
    return (
        f"Config file not found: {path}\n"
        "Create src/agent/config/config.yml with llm.model, llm.base_url, and agent settings."
    )


def require_section(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key)
    if isinstance(value, dict):
        return value
    raise ValueError(f"Config section must be an object: {key}")


def require_text(data: dict[str, Any], key: str, label: str | None = None) -> str:
    value = data.get(key)
    name = label or key

    if isinstance(value, str) and (text := value.strip()):
        return text

    raise ValueError(f"Missing required config value: {name}")


def get_client(config: dict[str, Any]) -> "Client":

    llm = require_section(config, "llm")
    model = require_text(llm, "model", "llm.model")
    base_url = require_text(llm, "base_url", "llm.base_url")

    options: dict[str, Any] = {
        "base_url": base_url,
        "api_key": require_api_key(),
    }

    if "temperature" in llm:
        options["temperature"] = llm["temperature"]

    return Client(model=model, **options)


def require_api_key() -> str:
    api_key = os.environ.get(API_KEY_NAME)
    if api_key:
        return api_key
    raise ValueError(f"Set {API_KEY_NAME} in .env or your shell environment.")


def get_agent(
    config: dict[str, Any],
    client: "Client",
    max_steps: int | None,
    session_manager: BaseSessionManager | None = None,
) -> "Agent":

    agent = require_section(config, "agent")
    name = str(agent.get("name", "sample-agent"))
    system_prompt = str(agent.get("system_prompt", ""))
    steps = max_steps if max_steps is not None else int(agent.get("max_steps", 5))
    is_code_exec = agent.get("code_exec", True)
    code_exec_image = str(agent.get("code_exec_image", "python")).strip()
    code_exec_runtime = str(agent.get("code_exec_runtime", "microsandbox")).strip()
    skills_path = str(agent.get("skills_dir", "")).strip() or None

    # before_tool_cb = [approval_cb]
    before_tool_cb: list[Callable[..., Any]] = []
    after_tool_cb: list[Callable[..., Any]] = [search_compress]
    before_llm_cb: list[Any] = [ContextOptimizer(client=client)]

    return Agent(
        client=client,
        tools=APP_TOOLS,
        system_prompt=system_prompt,
        max_steps=steps,
        role=name,
        is_code_exec=is_code_exec,
        code_exec_image=code_exec_image,
        code_exec_runtime=code_exec_runtime,
        skills_path=skills_path,
        session_manager=session_manager,
        before_tool_cb=before_tool_cb,
        after_tool_cb=after_tool_cb,
        before_llm_cb=before_llm_cb,
    )
