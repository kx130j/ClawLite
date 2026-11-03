from dataclasses import dataclass
from pathlib import Path


@dataclass
class SkillDefinition:
    name: str
    description: str
    triggers: list[str]
    body: str
    path: Path


class SkillRegistry:
    """Progressive-disclosure Skill Manager compatible with OpenClaw / Claude Code SKILL.md format."""

    def __init__(self, skills_dir: Path) -> None:
        self.skills_dir = skills_dir
        self.skills: dict[str, SkillDefinition] = {}
        self.discover()

    def discover(self) -> None:
        if not self.skills_dir.exists():
            return
        for skill_md in sorted(self.skills_dir.glob("*/SKILL.md")):
            parsed = self._parse_skill_md(skill_md)
            if parsed:
                self.skills[parsed.name] = parsed

    def _parse_skill_md(self, path: Path) -> SkillDefinition | None:
        raw = path.read_text(encoding="utf-8")
        if not raw.startswith("---"):
            return None
        parts = raw.split("---", 2)
        if len(parts) < 3:
            return None
        frontmatter, body = parts[1].strip(), parts[2].strip()
        meta: dict[str, str] = {}
        for line in frontmatter.splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip()
        name = meta.get("name", path.parent.name)
        desc = meta.get("description", "")
        triggers = [
            t.strip().lower()
            for t in meta.get("triggers", "").split(",")
            if t.strip()
        ]
        return SkillDefinition(
            name=name,
            description=desc,
            triggers=triggers,
            body=body,
            path=path,
        )

    def build_catalog_prompt(self) -> str:
        """Returns lightweight skill index for the immutable system prompt prefix (preserves Prompt Cache)."""
        if not self.skills:
            return "No skills registered."
        lines = ["<available_skills>"]
        for s in self.skills.values():
            lines.append(f"- {s.name}: {s.description}")
        lines.append("</available_skills>")
        return "\n".join(lines)

    def match_and_load_skills(self, task_text: str) -> list[SkillDefinition]:
        """Dynamically activates full skill bodies matching task triggers."""
        lower_task = task_text.lower()
        activated: list[SkillDefinition] = []
        for s in self.skills.values():
            if any(trig in lower_task for trig in s.triggers) or s.name in lower_task:
                activated.append(s)
        return activated
