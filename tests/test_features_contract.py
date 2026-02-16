from __future__ import annotations

from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
import sys
import types
import unittest
from unittest.mock import patch

from takobot import cli
from takobot.config import set_workspace_name
from takobot.daily import ensure_daily_log
from takobot.ens import resolve_recipient
from takobot.extensions.draft import create_draft_extension
from takobot.extensions.registry import load_registry
from takobot.keys import load_or_create_keys
from takobot.locks import instance_lock
from takobot.mission import is_activity_mission_aligned
from takobot.paths import RuntimePaths, ensure_runtime_dirs
from takobot.research import take_research_notes
from takobot.skillpacks import OPENCLAW_STARTER_SKILLS, seed_openclaw_starter_skills
from takobot.soul import DEFAULT_SOUL_ROLE, read_identity_mission, update_identity_mission
from takobot.tool_ops import fetch_webpage, run_local_command
from takobot.tools.loader import discover_tools
from takobot.workspace import materialize_workspace
from takobot.xmtp import default_message

from tests.helpers import local_html_server, parse_feature_criteria


ROOT = Path(__file__).resolve().parents[1]
FEATURES_PATH = ROOT / "FEATURES.md"


def _repo_text(relpath: str) -> str:
    return (ROOT / relpath).read_text(encoding="utf-8")


def _probe_docs_contract() -> bool:
    required_files = (
        "AGENTS.md",
        "SOUL.md",
        "VISION.md",
        "MEMORY.md",
        "ONBOARDING.md",
        "FEATURES.md",
        "index.html",
    )
    required_dirs = (
        "tools",
        "skills",
        "memory",
        "tasks",
        "projects",
        "areas",
        "resources",
        "archives",
    )
    return all((ROOT / rel).exists() for rel in required_files) and all((ROOT / rel).is_dir() for rel in required_dirs)


def _probe_legacy_runner() -> bool:
    path = ROOT / "tako.sh"
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8")
    return 'ARGS=("app")' in text and 'exec "$VENV_PY" -m takobot "${ARGS[@]}"' in text and "doctor" in text and "hi" in text


def _probe_setup_script_contract() -> bool:
    text = _repo_text("setup.sh")
    required = (
        "git init -b main",
        "launch: no interactive TTY detected; starting command-line daemon mode",
        "-m takobot run",
        "materialize_workspace",
        "interactive_tty_available",
        "NVM_VERSION=",
        "bootstrapping workspace-local nvm",
        "--cache \"$npm_cache\"",
    )
    return all(token in text for token in required)


def _probe_fresh_workspace_bootstrap() -> bool:
    with TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        first = materialize_workspace(workspace)
        if not (workspace / "SOUL.md").exists():
            return False
        if not first.created:
            return False
        soul = workspace / "SOUL.md"
        soul.write_text(soul.read_text(encoding="utf-8") + "\ndrift-marker\n", encoding="utf-8")
        second = materialize_workspace(workspace)
        return "SOUL.md" in second.drifted and "drift-marker" in soul.read_text(encoding="utf-8")


def _probe_cli_entrypoints() -> bool:
    parser = cli.build_parser()
    parser.parse_args(["doctor"])
    parser.parse_args(["run", "--once"])
    parser.parse_args(["hi", "--to", "0x1111111111111111111111111111111111111111"])

    with patch("takobot.cli.cmd_app", return_value=77):
        if cli.main([]) != 77:
            return False

    wrapper_text = _repo_text("tako.py")
    return 'return ["hi", *args]' in wrapper_text and "from takobot.cli import main" in wrapper_text


def _probe_app_runtime_strings() -> bool:
    app_text = _repo_text("takobot/app.py")
    cli_text = _repo_text("takobot/cli.py")
    required = (
        "ASK_XMTP_HANDLE",
        "PAIRING_OUTBOUND",
        "ONBOARDING_IDENTITY",
        "ONBOARDING_ROUTINES",
        "bubble stream",
        "workspace.name synced from identity",
        "update auto status",
        "starter skills synced",
        "Local web fetch:",
        "ctrl+shift+c",
        "incredibly curious about the world",
        "DOSE",
        "operator.profile.updated",
        "world.watch.sites.added",
    )
    return all(token in app_text for token in required) and "runtime.log" in cli_text


def _probe_name_and_mission() -> bool:
    with TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        materialize_workspace(workspace)
        soul_path = workspace / "SOUL.md"
        config_path = workspace / "tako.toml"

        update_identity_mission("SHELLY", "Your highly autonomous octopus friend", path=soul_path)
        name, mission = read_identity_mission(soul_path)
        if name != "SHELLY" or mission != "Your highly autonomous octopus friend":
            return False

        ok, _summary = set_workspace_name(config_path, "SHELLY")
        return ok


def _probe_keys_lifecycle() -> bool:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        keys_path = root / ".tako" / "keys.json"
        legacy_path = root / ".tako" / "config.json"
        legacy_path.parent.mkdir(parents=True, exist_ok=True)

        first = load_or_create_keys(keys_path, legacy_config_path=legacy_path)
        if not keys_path.exists() or not first.get("wallet_key") or not first.get("db_encryption_key"):
            return False

        keys_path.unlink()
        legacy_path.write_text(
            '{"wallet_key":"0xabc","db_encryption_key":"0xdef"}\n',
            encoding="utf-8",
        )
        second = load_or_create_keys(keys_path, legacy_config_path=legacy_path)
        return second["wallet_key"] == "0xabc" and second["db_encryption_key"] == "0xdef"


def _probe_recipient_resolution() -> bool:
    direct = resolve_recipient("0x1111111111111111111111111111111111111111", ["https://rpc.invalid"])
    if direct != "0x1111111111111111111111111111111111111111":
        return False

    fake_web3 = types.ModuleType("web3")

    class FakeHTTPProvider:
        def __init__(self, *_args, **_kwargs) -> None:
            return

    class FakeWeb3:
        HTTPProvider = FakeHTTPProvider

        def __init__(self, _provider) -> None:
            self.ens = self

        def is_connected(self) -> bool:
            return False

        def address(self, _name: str):
            return None

    fake_web3.Web3 = FakeWeb3

    class FakeResponse:
        status = 200
        reason = "OK"

        def __init__(self, payload: bytes) -> None:
            self._payload = payload

        def read(self) -> bytes:
            return self._payload

        def __enter__(self):
            return self

        def __exit__(self, _exc_type, _exc, _tb) -> None:
            return None

    payload = b'[{"address":"0x2222222222222222222222222222222222222222"}]'
    with patch.dict(sys.modules, {"web3": fake_web3}):
        with patch("takobot.ens.urlopen", return_value=FakeResponse(payload)):
            resolved = resolve_recipient("alice.eth", ["https://rpc.invalid"])
    return resolved == "0x2222222222222222222222222222222222222222"


def _probe_default_hi_message() -> bool:
    message = default_message()
    return message.startswith("hi from ") and message.endswith(" (tako)")


def _probe_runtime_dirs() -> bool:
    with TemporaryDirectory() as tmp:
        root = Path(tmp) / ".tako"
        paths = RuntimePaths(
            root=root,
            keys_json=root / "keys.json",
            operator_json=root / "operator.json",
            locks_dir=root / "locks",
            logs_dir=root / "logs",
            tmp_dir=root / "tmp",
            state_dir=root / "state",
            xmtp_db_dir=root / "xmtp-db",
        )
        ensured = ensure_runtime_dirs(paths)
        return ensured.xmtp_db_dir.exists() and ensured.logs_dir.exists() and ensured.state_dir.exists()


def _probe_operator_boundary() -> bool:
    if not cli._looks_like_command("web https://example.com"):
        return False
    if cli._looks_like_command("just chatting about lunch"):
        return False
    reply = cli._fallback_chat_reply(is_operator=False, operator_paired=True)
    help_text = cli._help_text().lower()
    return "operator-only boundary" in reply.lower() and "update" in help_text and "web" in help_text and "run" in help_text


def _probe_starter_skills() -> bool:
    with TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        materialize_workspace(workspace)
        registry_path = workspace / ".tako" / "state" / "extensions.json"
        registry_path.parent.mkdir(parents=True, exist_ok=True)
        result = seed_openclaw_starter_skills(workspace, registry_path=registry_path)
        if len(result.created_skills) + len(result.existing_skills) != len(OPENCLAW_STARTER_SKILLS):
            return False
        registry = load_registry(registry_path)
        installed = registry.get("installed", {})
        if not isinstance(installed, dict):
            return False
        for skill in OPENCLAW_STARTER_SKILLS:
            key = f"skill:{skill.slug}"
            if key not in installed:
                return False
            if bool(installed[key].get("enabled")):
                return False
        pi_skill = workspace / "skills" / "agent-cli-inferencing" / "playbook.md"
        if not pi_skill.exists():
            return False
        pi_text = pi_skill.read_text(encoding="utf-8")
        if "@mariozechner/pi-ai" not in pi_text:
            return False
        if "github.com/badlogic/pi-mono" not in pi_text:
            return False
        return True


def _probe_default_tools() -> bool:
    with local_html_server(title="Feature Probe", body="default tools") as url:
        web = fetch_webpage(url)
    if not web.ok:
        return False
    run = run_local_command("printf 'feature-probe-ok'")
    return run.ok and "feature-probe-ok" in run.output


def _probe_research_notes_workflow() -> bool:
    with TemporaryDirectory() as tmp:
        notes_root = Path(tmp) / "memory" / "dailies"
        with local_html_server(title="Probe Research", body="Topic facts for notes.") as url:
            result = take_research_notes("probe topic", [url], notes_root=notes_root)
        if result.sources_ok != 1 or result.sources_failed != 0:
            return False
        text = result.notes_path.read_text(encoding="utf-8")
        return "Research topic: probe topic" in text and "Research note: topic=probe topic" in text


def _probe_mission_alignment() -> bool:
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
    return all(is_activity_mission_aligned(activity, mission) for activity in activities)


def _probe_daily_log() -> bool:
    with TemporaryDirectory() as tmp:
        root = Path(tmp) / "memory" / "dailies"
        path = ensure_daily_log(root, date.today())
        return path.exists() and path.name.endswith(".md")


def _probe_tool_discovery() -> bool:
    tools = discover_tools(ROOT / "tools")
    return any(tool.name == "memory_append" for tool in tools)


def _probe_lock_behavior() -> bool:
    with TemporaryDirectory() as tmp:
        lock_path = Path(tmp) / ".tako" / "locks" / "tako.lock"
        with instance_lock(lock_path):
            try:
                with instance_lock(lock_path):
                    return False
            except RuntimeError:
                return True


def _probe_type2_contract() -> bool:
    text = _repo_text("takobot/app.py")
    required = (
        "def _assess_event_for_type2",
        'event_type.startswith("health.check.issue")',
        'event_type.startswith("runtime.")',
        "runtime crash",
        "Type2 escalation",
    )
    return all(token in text for token in required)


def _probe_draft_extensions() -> bool:
    with TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        materialize_workspace(workspace)
        registry_path = workspace / ".tako" / "state" / "extensions.json"
        registry_path.parent.mkdir(parents=True, exist_ok=True)

        skill = create_draft_extension(workspace, registry_path=registry_path, kind="skill", name_raw="Draft Alpha")
        tool = create_draft_extension(workspace, registry_path=registry_path, kind="tool", name_raw="Draft Beta")
        if not skill.created or not tool.created:
            return False

        registry = load_registry(registry_path)
        return (
            f"skill:{skill.name}" in registry["installed"]
            and not bool(registry["installed"][f"skill:{skill.name}"]["enabled"])
            and f"tool:{tool.name}" in registry["installed"]
            and not bool(registry["installed"][f"tool:{tool.name}"]["enabled"])
        )


PROBES = {
    "docs_contract": _probe_docs_contract,
    "legacy_runner": _probe_legacy_runner,
    "setup_script_contract": _probe_setup_script_contract,
    "fresh_workspace_bootstrap": _probe_fresh_workspace_bootstrap,
    "cli_entrypoints": _probe_cli_entrypoints,
    "app_runtime_strings": _probe_app_runtime_strings,
    "name_and_mission": _probe_name_and_mission,
    "keys_lifecycle": _probe_keys_lifecycle,
    "recipient_resolution": _probe_recipient_resolution,
    "default_hi_message": _probe_default_hi_message,
    "runtime_dirs": _probe_runtime_dirs,
    "operator_boundary": _probe_operator_boundary,
    "starter_skills": _probe_starter_skills,
    "default_tools": _probe_default_tools,
    "research_notes_workflow": _probe_research_notes_workflow,
    "mission_alignment": _probe_mission_alignment,
    "daily_log": _probe_daily_log,
    "tool_discovery": _probe_tool_discovery,
    "lock_behavior": _probe_lock_behavior,
    "type2_contract": _probe_type2_contract,
    "draft_extensions": _probe_draft_extensions,
}


SECTION_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Docs-first repo contract", ("docs_contract",)),
    ("Legacy repo runner", ("legacy_runner",)),
    ("Workspace bootstrap", ("setup_script_contract", "fresh_workspace_bootstrap")),
    ("CLI entrypoints", ("cli_entrypoints",)),
    (
        "Interactive terminal app main loop",
        (
            "app_runtime_strings",
            "name_and_mission",
            "starter_skills",
            "default_tools",
            "research_notes_workflow",
            "mission_alignment",
            "operator_boundary",
            "type2_contract",
        ),
    ),
    ("DOSE cognitive state", ("app_runtime_strings",)),
    ("Productivity engine v1", ("app_runtime_strings",)),
    ("Skills / tools install pipeline", ("draft_extensions",)),
    ("Local runtime keys", ("keys_lifecycle",)),
    ("Recipient resolution", ("recipient_resolution",)),
    ("One-off XMTP DM send", ("default_hi_message",)),
    ("Local XMTP DB storage + reset", ("runtime_dirs",)),
    ("XMTP settings", ("operator_boundary",)),
    ("Farcaster integration", ("operator_boundary",)),
    ("Operator imprint", ("operator_boundary",)),
    ("Daily logs", ("daily_log",)),
    ("Tool discovery", ("tool_discovery",)),
    ("Multi-instance lock", ("lock_behavior",)),
    ("Operator-only command authorization", ("operator_boundary",)),
    ("Tasks + calendar storage", ("app_runtime_strings",)),
    ("Sensors framework", ("app_runtime_strings",)),
    ("Cognitive state", ("type2_contract",)),
    ("“Eat the crab” importer", ("app_runtime_strings",)),
)


def _probes_for_section(section: str) -> tuple[str, ...]:
    for prefix, probes in SECTION_RULES:
        if section.startswith(prefix):
            return probes
    return ()


class TestFeaturesContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.criteria = parse_feature_criteria(FEATURES_PATH)
        cls._probe_cache: dict[str, bool] = {}

    @classmethod
    def _run_probe(cls, name: str) -> bool:
        if name in cls._probe_cache:
            return cls._probe_cache[name]
        fn = PROBES[name]
        value = bool(fn())
        cls._probe_cache[name] = value
        return value

    def test_feature_sections_have_probe_rules(self) -> None:
        sections = {item.section for item in self.criteria}
        missing = sorted(section for section in sections if not _probes_for_section(section))
        self.assertEqual([], missing, f"Missing probe rules for sections: {missing}")

    def test_each_feature_criterion_is_checked_by_probes(self) -> None:
        self.assertGreater(len(self.criteria), 0)
        for item in self.criteria:
            with self.subTest(section=item.section, checked=item.checked, criterion=item.text):
                probes = _probes_for_section(item.section)
                self.assertTrue(probes, f"no probes configured for section: {item.section}")
                for probe_name in probes:
                    self.assertIn(probe_name, PROBES, f"unknown probe configured: {probe_name}")
                    outcome = self._run_probe(probe_name)
                    self.assertIsInstance(outcome, bool)
                    if item.checked:
                        self.assertTrue(
                            outcome,
                            f"checked criterion failed probe `{probe_name}`: {item.text}",
                        )
