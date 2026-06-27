
import re
from dataclasses import dataclass
from pathlib import Path

@dataclass
class SkillInfo:
    name: str
    desc: str
    path: Path


def parse_frontmatter(content: str) -> dict[str, str]:

    pattern = r"^---\s*\n(.*?)\n---"
    match = re.match(pattern, content, re.DOTALL)

    if match is None:
        return {}

    result: dict[str, str] = {}

    for line in match.group(1).split("\n"):

        if ":" not in line:
            continue

        key, val = line.split(":", 1)

        key = key.strip()
        if not key:
            continue

        val = val.strip().strip("\"'")
        result[key] = val

    return result

def load_skill(skill_dir: Path) -> SkillInfo | None:

    md = skill_dir / "SKILL.md"
    if not md.exists():
        return None
    
    content = md.read_text(encoding='utf-8')
    frontmatter = parse_frontmatter(content)

    name = frontmatter.get('name')
    desc = frontmatter.get('description')

    if not name or not desc:
        return None
    
    return SkillInfo(name=name, desc=desc, path=skill_dir)


def find_skill(skill_path: str | Path) -> list[SkillInfo]:
    skills_dir = Path(skill_path)

    if not skills_dir.exists():
        return []

    skills: list[SkillInfo] = []

    for item in sorted(skills_dir.iterdir()):
        if not item.is_dir():
            continue

        if item.name.startswith("."):
            continue

        skill = load_skill(item)
        if skill is None:
            continue

        skills.append(skill)

    return skills


def make_skills_prompt(skills: list[SkillInfo], sandbox_path: str="/tmp/skills") -> str:

    if not skills:
        return ""
    
    lines = [
        "## Available Skills",
        "The following skills are available in the sandbox environment",
        ""
    ]

    for skill in skills:
        lines.append(f"### {skill.name}")
        lines.append(f"- Description: {skill.desc}")
        lines.append(f"- Path: {sandbox_path}/{skill.name}/")
        lines.append(f"- Read the SKILL.md for usage instruction: {sandbox_path}/{skill.name}/SKILL.md")
        lines.append(f"")

    lines.append(
        "You can import and use these skills in your Python code."
        "Read the SKILL.md file first to understand how to use each skill."
    )

    return "\n".join(lines)
