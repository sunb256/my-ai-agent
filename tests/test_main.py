import sys
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from main import get_map, parse_env_line, require_text  # noqa: E402


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
