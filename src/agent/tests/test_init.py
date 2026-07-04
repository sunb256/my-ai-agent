import sys
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.core.tools.app_tools import APP_TOOLS  # noqa: E402
from agent.init import apply_env_overrides, get_agent, get_client, parse_env_line, require_section  # noqa: E402
from agent.init import require_text  # noqa: E402


def test_parse_env_line_reads_key_value():
    assert parse_env_line("OPENAI_API_KEY=secret") == ("OPENAI_API_KEY", "secret")


def test_parse_env_line_ignores_comment():
    assert parse_env_line("# comment") == (None, "")


def test_require_section_rejects_non_object_section():
    with pytest.raises(ValueError, match="Config section"):
        require_section({"llm": "invalid"}, "llm")


def test_require_text_rejects_blank_value():
    with pytest.raises(ValueError, match="llm.model"):
        require_text({"model": ""}, "model", "llm.model")


def test_apply_env_overrides_updates_llm_and_agent(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LLM_MODEL", "openai/test-model")
    monkeypatch.setenv("LLM_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("LLM_TEMPERATURE", "0.1")
    monkeypatch.setenv("AGENT_CODE_EXEC", "false")
    monkeypatch.setenv("AGENT_CODE_EXEC_IMAGE", "ai-agent-python:local")
    monkeypatch.setenv("AGENT_CODE_EXEC_RUNTIME", "docker")
    monkeypatch.setenv("AGENT_SKILLS_DIR", "resources/skills")

    config = apply_env_overrides({"llm": {}, "agent": {}})

    assert config["llm"] == {
        "model": "openai/test-model",
        "base_url": "https://example.test/v1",
        "temperature": 0.1,
    }
    assert config["agent"]["code_exec"] is False
    assert config["agent"]["code_exec_image"] == "ai-agent-python:local"
    assert config["agent"]["code_exec_runtime"] == "docker"
    assert config["agent"]["skills_dir"] == "resources/skills"


def test_get_client_reads_model_and_options(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("OPENAI_API_KEY", "secret")

    client = get_client(
        {
            "llm": {
                "model": "openai/llama3.2",
                "base_url": "http://localhost:11434/v1",
                "temperature": 0.2,
            }
        }
    )

    assert client.model == "openai/llama3.2"
    assert client.config == {
        "base_url": "http://localhost:11434/v1",
        "api_key": "secret",
        "temperature": 0.2,
    }


def test_get_client_builds_client_from_llm_settings(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OPENAI_API_KEY", "secret")

    client = get_client(
        {
            "llm": {
                "model": "openai/llama3.2",
                "base_url": "http://localhost:11434/v1",
            }
        }
    )

    assert client.model == "openai/llama3.2"
    assert client.config == {
        "base_url": "http://localhost:11434/v1",
        "api_key": "secret",
    }


def test_get_agent_uses_app_tools_and_max_steps_override(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("OPENAI_API_KEY", "secret")
    config = {
        "llm": {
            "model": "openai/llama3.2",
            "base_url": "http://localhost:11434/v1",
        },
        "agent": {
            "name": "sample",
            "system_prompt": "short answer",
            "max_steps": 5,
            "code_exec_image": "my-python-data-image:local",
            "code_exec_runtime": "docker",
            "skills_dir": "resources/skills",
        },
    }

    client = get_client(config)
    agent = get_agent(config, client, max_steps=8)

    assert agent.client is client
    assert [tool.name for tool in agent.tools] == [
        *[tool.name for tool in APP_TOOLS],
        "exec_python",
        "bash_tool",
        "upload_file",
    ]
    assert agent.system_prompt == "short answer"
    assert agent.max_step == 8
    assert agent.role == "sample"
    assert agent.code_exec_image == "my-python-data-image:local"
    assert agent.code_exec_runtime == "docker"
    assert agent.skills_path == "resources/skills"
