
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
          "The following skills are available in the sandbox environment.",
          "",
          "When the user asks to use a specific skill, you MUST read that skill's SKILL.md before using it.",
          "Use bash_tool or exec_python to inspect the SKILL.md file in the sandbox.",
          "After reading SKILL.md, follow its instructions exactly.",
          "",
      ]

    for skill in skills:
        lines.append(f"### {skill.name}")
        lines.append(f"- Description: {skill.desc}")
        lines.append(f"- Path: {sandbox_path}/{skill.name}/")
        lines.append(f"- Read the SKILL.md for usage instruction: {sandbox_path}/{skill.name}/SKILL.md")
        lines.append(
            f"- If the user mentions `{skill.name}`, first read "
            f"`{sandbox_path}/{skill.name}/SKILL.md` before doing the task."
        )
        lines.append("")

    lines.append(
        "Do not assume how a skill works from its name alone. "
        "Always read the matching SKILL.md first when a skill is requested."
    )

    return "\n".join(lines)


def select_requested_skills(skills: list[SkillInfo], text: str) -> list[SkillInfo]:
    text_lower = text.lower()
    selected: list[SkillInfo] = []

    for skill in skills:
        name = skill.name.lower()
        pattern = rf"(?<![a-zA-Z0-9_-]){re.escape(name)}(?![a-zA-Z0-9_-])"

        if re.search(pattern, text_lower):
            selected.append(skill)

    return selected

def make_requested_skills_prompt(skills: list[SkillInfo], sandbox_path: str = "/tmp/skills") -> str:
    
      if not skills:
          return ""

      lines = [
          "## Requested Skill Instructions",
          "The user explicitly requested the following skills.",
          "Use these instructions directly. The same files are also available in the sandbox.",
          "",
      ]

      for skill in skills:
          skill_md = skill.path / "SKILL.md"
          content = skill_md.read_text(encoding="utf-8")

          lines.append(f"### {skill.name}")
          lines.append(f"- Sandbox path: {sandbox_path}/{skill.name}/")
          lines.append(f"- Instruction file: {sandbox_path}/{skill.name}/SKILL.md")
          lines.append("")
          lines.append(content.strip())
          lines.append("")

      return "\n".join(lines)