import sys
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from init import get_map, parse_env_line, require_text  # noqa: E402
from init import resolve_agent_settings, resolve_llm_settings  # noqa: E402


def test_parse_env_line_reads_key_value():
    assert parse_env_line("OPENAI_API_KEY=secret") == ("OPENAI_API_KEY", "secret")


def test_parse_env_line_ignores_comment():
    assert parse_env_line("# comment") == (None, "")


def test_get_map_rejects_non_object_section():
    with pytest.raises(ValueError, match="Config section"):
        get_map({"llm": "invalid"}, "llm")


def test_require_text_rejects_blank_value():
    with pytest.raises(ValueError, match="llm.model"):
        require_text({"model": ""}, "model", "llm.model")


def test_resolve_llm_settings_reads_model_and_options(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("OPENAI_API_KEY", "secret")

    model, options = resolve_llm_settings(
        {
            "llm": {
                "model": "openai/llama3.2",
                "base_url": "http://localhost:11434/v1",
                "temperature": 0.2,
            }
        }
    )

    assert model == "openai/llama3.2"
    assert options == {
        "base_url": "http://localhost:11434/v1",
        "api_key": "secret",
        "temperature": 0.2,
    }


def test_resolve_agent_settings_prefers_max_steps_override():
    settings = resolve_agent_settings(
        {
            "agent": {
                "name": "sample",
                "instructions": "short answer",
                "max_steps": 5,
            }
        },
        max_steps=8,
    )

    assert settings == {
        "name": "sample",
        "instructions": "short answer",
        "max_steps": 8,
    }
