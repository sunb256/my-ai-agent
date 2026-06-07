import asyncio
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent.context import ExecContext  # noqa: E402
from app_tools import APP_TOOLS, add_numbers, get_current_time  # noqa: E402


def test_app_tools_contains_sample_tools():
    names = [tool.name for tool in APP_TOOLS]

    assert names == ["get_current_time", "add_numbers"]


def test_add_numbers_returns_sum():
    assert asyncio.run(add_numbers(ExecContext(), a=3, b=5)) == 8


def test_get_current_time_returns_text():
    assert asyncio.run(get_current_time(ExecContext()))
