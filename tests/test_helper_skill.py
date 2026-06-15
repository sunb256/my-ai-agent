import asyncio
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent.helper_skill import upload_skills_to_sandbox  # noqa: E402


class FakeSandboxFs:
    def __init__(self):
        self.dirs = set()
        self.copied = []

    async def exists(self, path: str) -> bool:
        return path in self.dirs

    async def mkdir(self, path: str) -> None:
        self.dirs.add(path)

    async def copy_from_host(self, host_path: str, guest_path: str) -> None:
        self.copied.append((host_path, guest_path))


class FakeSandbox:
    def __init__(self):
        self.fs = FakeSandboxFs()


def test_upload_skills_to_sandbox_copies_skill_files_recursively(tmp_path: Path):
    skill_dir = tmp_path / "sample"
    helper_dir = skill_dir / "lib"
    helper_dir.mkdir(parents=True)

    skill_md = skill_dir / "SKILL.md"
    helper_py = helper_dir / "helper.py"

    skill_md.write_text(
        "---\nname: sample\ndescription: sample skill\n---\n\nUse helper.",
        encoding="utf-8",
    )
    helper_py.write_text("VALUE = 1\n", encoding="utf-8")

    sandbox = FakeSandbox()

    asyncio.run(upload_skills_to_sandbox(sandbox, tmp_path))

    assert "/tmp/skills" in sandbox.fs.dirs
    assert "/tmp/skills/sample" in sandbox.fs.dirs
    assert "/tmp/skills/sample/lib" in sandbox.fs.dirs
    assert (str(skill_md), "/tmp/skills/sample/SKILL.md") in sandbox.fs.copied
    assert (str(helper_py), "/tmp/skills/sample/lib/helper.py") in sandbox.fs.copied


def test_upload_skills_to_sandbox_ignores_empty_path():
    sandbox = FakeSandbox()

    asyncio.run(upload_skills_to_sandbox(sandbox, None))

    assert sandbox.fs.dirs == set()
    assert sandbox.fs.copied == []
