import inspect
import posixpath
from pathlib import Path
from typing import Any

from .skills import SkillInfo, find_skill

SANDBOX_SKILLS_DIR = "/tmp/skills"


async def upload_skills_to_sandbox(sandbox: Any, skills_path: str | Path | None) -> None:
    if not skills_path:
        return

    skills = find_skill(skills_path)
    if not skills:
        return

    await _mkdir_p(sandbox, SANDBOX_SKILLS_DIR)

    for skill in skills:
        await _upload_skill_to_sandbox(sandbox, skill)


async def _upload_skill_to_sandbox(sandbox: Any, skill: SkillInfo) -> None:
    skill_root = Path(skill.path)
    sandbox_root = posixpath.join(SANDBOX_SKILLS_DIR, skill.name)

    await _mkdir_p(sandbox, sandbox_root)

    for local_file in skill_root.rglob("*"):
        if not local_file.is_file():
            continue

        relative_path = local_file.relative_to(skill_root).as_posix()
        sandbox_path = posixpath.join(sandbox_root, relative_path)

        await _mkdir_p(sandbox, posixpath.dirname(sandbox_path))
        await _copy_from_host(sandbox, local_file, sandbox_path)


async def _mkdir_p(sandbox: Any, path: str) -> None:
    current = ""

    for part in path.strip("/").split("/"):
        if not part:
            continue

        current = f"{current}/{part}"

        exists = sandbox.fs.exists(current)
        if inspect.isawaitable(exists):
            exists = await exists

        if exists:
            continue

        result = sandbox.fs.mkdir(current)
        if inspect.isawaitable(result):
            await result


async def _copy_from_host(sandbox: Any, local_path: Path, sandbox_path: str) -> None:
    result = sandbox.fs.copy_from_host(str(local_path), sandbox_path)
    if inspect.isawaitable(result):
        await result
