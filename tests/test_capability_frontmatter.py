from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from takobot.capability_frontmatter import (
    build_skills_inventory_excerpt,
    build_tools_inventory_excerpt,
    load_skills_frontmatter_excerpt,
    load_tools_frontmatter_excerpt,
)


class TestCapabilityFrontmatter(unittest.TestCase):
    def test_load_frontmatter_missing_files(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertIn("SKILLS.md is missing", load_skills_frontmatter_excerpt(root=root))
            self.assertIn("TOOLS.md is missing", load_tools_frontmatter_excerpt(root=root))

    def test_build_skills_inventory_reads_playbook_purpose(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill_dir = root / "skills" / "sample-skill"
            skill_dir.mkdir(parents=True, exist_ok=True)
            (skill_dir / "playbook.md").write_text(
                "# Sample Skill\n\n## Purpose\nUse this skill to validate capability selection.\n",
                encoding="utf-8",
            )
            inventory = build_skills_inventory_excerpt(root=root)
            self.assertIn("sample-skill", inventory)
            self.assertIn("validate capability selection", inventory)

    def test_build_tools_inventory_reads_manifest_description(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            tool_dir = root / "tools" / "sample-tool"
            tool_dir.mkdir(parents=True, exist_ok=True)
            (tool_dir / "manifest.toml").write_text(
                '[tool]\nname = "sample-tool"\ndescription = "Tool for deterministic checks."\n',
                encoding="utf-8",
            )
            inventory = build_tools_inventory_excerpt(root=root)
            self.assertIn("sample-tool", inventory)
            self.assertIn("Tool for deterministic checks.", inventory)


if __name__ == "__main__":
    unittest.main()
