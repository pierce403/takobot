from __future__ import annotations

from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from takobot.config import load_tako_toml, set_workspace_name
from takobot.extensions.draft import create_draft_extension
from takobot.extensions.registry import load_registry
from takobot.mission import activity_alignment_score, is_activity_mission_aligned
from takobot.skillpacks import OPENCLAW_STARTER_SKILLS, seed_openclaw_starter_skills
from takobot.soul import DEFAULT_SOUL_ROLE, read_identity_mission, update_identity_mission
from takobot.tool_ops import fetch_webpage, run_local_command
from takobot.workspace import materialize_workspace

from tests.helpers import local_html_server


class TestFreshWorkspace(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.workspace = Path(self._tmp.name)
        self.registry_path = self.workspace / ".tako" / "state" / "extensions.json"
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        self.first_materialize = materialize_workspace(self.workspace)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_materialize_workspace_contract_and_idempotency(self) -> None:
        required_files = ("AGENTS.md", "MEMORY.md", "ONBOARDING.md", "SOUL.md", "tako.toml")
        required_dirs = (
            "archives",
            "areas",
            "memory",
            "memory/dailies",
            "memory/people",
            "memory/places",
            "memory/things",
            "projects",
            "resources",
            "skills",
            "tasks",
            "tools",
        )

        for rel in required_files:
            self.assertTrue((self.workspace / rel).is_file(), f"missing file: {rel}")
        for rel in required_dirs:
            self.assertTrue((self.workspace / rel).is_dir(), f"missing dir: {rel}")
        self.assertGreater(len(self.first_materialize.created), 0)

        soul_path = self.workspace / "SOUL.md"
        soul_path.write_text(soul_path.read_text(encoding="utf-8") + "\ncustom drift marker\n", encoding="utf-8")
        second = materialize_workspace(self.workspace)
        self.assertIn("SOUL.md", second.drifted)
        self.assertIn("custom drift marker", soul_path.read_text(encoding="utf-8"))
        drift_log = self.workspace / "memory" / "dailies" / f"{date.today().isoformat()}.md"
        self.assertTrue(drift_log.exists(), "template drift should be logged in workspace daily log")

    def test_setting_name_and_mission_updates_workspace_identity(self) -> None:
        soul_path = self.workspace / "SOUL.md"
        config_path = self.workspace / "tako.toml"

        update_identity_mission("SHELLY", "Your highly autonomous octopus friend", path=soul_path)
        name, mission = read_identity_mission(soul_path)
        self.assertEqual("SHELLY", name)
        self.assertEqual("Your highly autonomous octopus friend", mission)

        ok, summary = set_workspace_name(config_path, "SHELLY")
        self.assertTrue(ok, summary)
        cfg, warn = load_tako_toml(config_path)
        self.assertEqual("", warn)
        self.assertEqual("SHELLY", cfg.workspace.name)

    def test_starter_skills_seed_and_register_disabled(self) -> None:
        seeded = seed_openclaw_starter_skills(self.workspace, registry_path=self.registry_path)
        total = len(seeded.created_skills) + len(seeded.existing_skills)
        self.assertEqual(len(OPENCLAW_STARTER_SKILLS), total)

        second_seed = seed_openclaw_starter_skills(self.workspace, registry_path=self.registry_path)
        self.assertEqual(0, len(second_seed.created_skills))

        registry = load_registry(self.registry_path)
        installed = registry.get("installed", {})
        self.assertIsInstance(installed, dict)

        for skill in OPENCLAW_STARTER_SKILLS:
            skill_dir = self.workspace / "skills" / skill.slug
            playbook = skill_dir / "playbook.md"
            policy = skill_dir / "policy.toml"
            readme = skill_dir / "README.md"
            self.assertTrue(playbook.exists(), f"missing {playbook}")
            self.assertTrue(policy.exists(), f"missing {policy}")
            self.assertTrue(readme.exists(), f"missing {readme}")
            self.assertIn("Mission alignment check", playbook.read_text(encoding="utf-8"))

            key = f"skill:{skill.slug}"
            self.assertIn(key, installed, f"missing registry entry {key}")
            self.assertFalse(bool(installed[key].get("enabled")), f"{key} should remain disabled")

    def test_draft_skill_and_tool_create_disabled_extensions(self) -> None:
        skill = create_draft_extension(
            self.workspace,
            registry_path=self.registry_path,
            kind="skill",
            name_raw="Mission Planner",
        )
        tool = create_draft_extension(
            self.workspace,
            registry_path=self.registry_path,
            kind="tool",
            name_raw="Safety Runner",
        )
        self.assertTrue(skill.created, skill.message)
        self.assertTrue(tool.created, tool.message)

        self.assertTrue((self.workspace / "skills" / skill.name / "playbook.md").exists())
        self.assertTrue((self.workspace / "tools" / tool.name / "tool.py").exists())

        duplicate = create_draft_extension(
            self.workspace,
            registry_path=self.registry_path,
            kind="skill",
            name_raw="Mission Planner",
        )
        self.assertFalse(duplicate.created)

        registry = load_registry(self.registry_path)
        self.assertFalse(bool(registry["installed"][f"skill:{skill.name}"]["enabled"]))
        self.assertFalse(bool(registry["installed"][f"tool:{tool.name}"]["enabled"]))

    def test_default_tools_and_default_skills_are_mission_aligned(self) -> None:
        with local_html_server(title="Takobot Mission Probe", body="mission aligned") as url:
            web = fetch_webpage(url)
        self.assertTrue(web.ok, web.error)
        self.assertEqual("Takobot Mission Probe", web.title)

        run = run_local_command("printf 'takobot-run-ok'", cwd=self.workspace)
        self.assertTrue(run.ok, run.output)
        self.assertIn("takobot-run-ok", run.output)

        mission = DEFAULT_SOUL_ROLE
        activities = [
            "Use web tool to gather world context safely for the operator and summarize clearly.",
            "Use run tool to execute diagnostics safely for the operator and summarize clearly.",
            "Stay curious and safely ask operator-focused follow-up research questions when uncertainty is high.",
        ]
        for skill in OPENCLAW_STARTER_SKILLS:
            activities.append(
                f"{skill.display_name}: {skill.summary} Execute safely for the operator and summarize clearly."
            )

        for activity in activities:
            score = activity_alignment_score(activity, mission)
            self.assertGreater(score, 0.0, activity)
            self.assertTrue(is_activity_mission_aligned(activity, mission), activity)
