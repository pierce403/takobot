from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from takobot.inference import (
    InferenceRuntime,
    InferenceProviderStatus,
    InferenceSettings,
    _codex_oauth_credential_from_auth,
    _ensure_workspace_pi_auth,
    _detect_ollama,
    _detect_pi,
    _provider_env,
    _run_pi,
    _workspace_node_bin_dir,
    auto_repair_inference_runtime,
    discover_inference_runtime,
    clear_inference_api_key,
    format_inference_auth_inventory,
    load_inference_settings,
    prepare_pi_login_plan,
    set_inference_api_key,
    set_inference_ollama_host,
    set_inference_ollama_model,
    set_inference_preferred_provider,
)


class TestInferencePiRuntime(unittest.TestCase):
    @staticmethod
    def _status(
        provider: str,
        *,
        cli_installed: bool,
        ready: bool,
        auth_kind: str = "none",
        key_env_var: str | None = None,
        key_source: str | None = None,
        key_present: bool = False,
        note: str = "",
    ) -> InferenceProviderStatus:
        return InferenceProviderStatus(
            provider=provider,
            cli_name=provider,
            cli_path=f"/usr/bin/{provider}" if cli_installed else None,
            cli_installed=cli_installed,
            auth_kind=auth_kind,
            key_env_var=key_env_var,
            key_source=key_source,
            key_present=key_present,
            ready=ready,
            note=note,
        )

    def test_workspace_node_bin_dir_picks_latest_installed_node(self) -> None:
        with TemporaryDirectory() as tmp:
            nvm_dir = Path(tmp) / "nvm"
            node_name = "node.exe" if os.name == "nt" else "node"
            for version in ("v20.18.0", "v22.13.1"):
                bin_dir = nvm_dir / "versions" / "node" / version / "bin"
                bin_dir.mkdir(parents=True, exist_ok=True)
                (bin_dir / node_name).write_text("", encoding="utf-8")

            with patch("takobot.inference._workspace_nvm_dir", return_value=nvm_dir):
                selected = _workspace_node_bin_dir()

        self.assertIsNotNone(selected)
        assert selected is not None
        self.assertIn("v22.13.1", str(selected))

    def test_provider_env_prepends_workspace_node_bin_for_pi(self) -> None:
        runtime = InferenceRuntime(
            statuses={},
            selected_provider=None,
            selected_auth_kind="none",
            selected_key_env_var=None,
            selected_key_source=None,
            _api_keys={},
        )

        with TemporaryDirectory() as tmp:
            node_bin = Path(tmp) / "node-bin"
            node_bin.mkdir(parents=True, exist_ok=True)
            nvm_dir = Path(tmp) / "nvm"
            agent_dir = Path(tmp) / "agent"
            agent_dir.mkdir(parents=True, exist_ok=True)
            with (
                patch("takobot.inference._workspace_node_bin_dir", return_value=node_bin),
                patch("takobot.inference._workspace_nvm_dir", return_value=nvm_dir),
                patch("takobot.inference._workspace_pi_agent_dir", return_value=agent_dir),
                patch("takobot.inference._ensure_workspace_pi_auth"),
                patch.dict(os.environ, {"PATH": "/usr/bin"}, clear=False),
            ):
                env = _provider_env(runtime, "pi")

        self.assertTrue(env["PATH"].startswith(str(node_bin) + os.pathsep))
        self.assertEqual(str(nvm_dir), env["NVM_DIR"])
        self.assertEqual(str(agent_dir), env["PI_CODING_AGENT_DIR"])

    def test_run_pi_does_not_disable_tools_or_skills(self) -> None:
        runtime = InferenceRuntime(
            statuses={"pi": self._status("pi", cli_installed=True, ready=True)},
            selected_provider="pi",
            selected_auth_kind="oauth",
            selected_key_env_var=None,
            selected_key_source="oauth",
            _api_keys={},
        )
        with patch(
            "takobot.inference.subprocess.run",
            return_value=SimpleNamespace(returncode=0, stdout="ok", stderr=""),
        ) as run_mock:
            output = _run_pi(runtime, "hello world", env={}, timeout_s=10.0)

        self.assertEqual("ok", output)
        called_cmd = run_mock.call_args.args[0]
        self.assertIn("--print", called_cmd)
        self.assertIn("--mode", called_cmd)
        self.assertIn("--no-session", called_cmd)
        self.assertNotIn("--no-tools", called_cmd)
        self.assertNotIn("--no-extensions", called_cmd)
        self.assertNotIn("--no-skills", called_cmd)

    def test_detect_pi_requires_node_runtime_for_ready(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            home.mkdir(parents=True, exist_ok=True)
            pi_bin = Path(tmp) / "pi"
            pi_bin.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
            env = {"OPENAI_API_KEY": "test-key"}

            with (
                patch("takobot.inference._workspace_pi_cli_path", return_value=pi_bin),
                patch("takobot.inference._pi_node_available", return_value=False),
            ):
                status, _key = _detect_pi(home, env)

        self.assertFalse(status.ready)
        self.assertIn("node runtime is unavailable", status.note)

    def test_detect_ollama_uses_configured_or_discovered_model(self) -> None:
        with patch("takobot.inference.shutil.which", return_value="/usr/bin/ollama"):
            status_env, _key = _detect_ollama(Path("."), {"OLLAMA_MODEL": "llama3.2"})
            self.assertTrue(status_env.ready)
            self.assertEqual("model:llama3.2", status_env.key_source)

            with patch("takobot.inference._list_ollama_models", return_value=["qwen2.5-coder:7b"]):
                status_discovered, _key2 = _detect_ollama(Path("."), {})
            self.assertTrue(status_discovered.ready)
            self.assertEqual("model:qwen2.5-coder:7b", status_discovered.key_source)

    def test_inference_settings_enforce_pi_provider_and_api_keys(self) -> None:
        with TemporaryDirectory() as tmp:
            settings_path = Path(tmp) / "inference-settings.json"
            ok_provider, _msg_provider = set_inference_preferred_provider("ollama", path=settings_path)
            ok_provider_pi, _msg_provider_pi = set_inference_preferred_provider("pi", path=settings_path)
            ok_model, _msg_model = set_inference_ollama_model("llama3.2", path=settings_path)
            ok_host, _msg_host = set_inference_ollama_host("http://127.0.0.1:11434", path=settings_path)
            ok_key, _msg_key = set_inference_api_key("OPENAI_API_KEY", "sk-test-value", path=settings_path)

            self.assertFalse(ok_provider)
            self.assertTrue(ok_provider_pi)
            self.assertTrue(ok_model)
            self.assertTrue(ok_host)
            self.assertTrue(ok_key)

            settings = load_inference_settings(settings_path)
            self.assertEqual("pi", settings.preferred_provider)
            self.assertEqual("llama3.2", settings.ollama_model)
            self.assertEqual("http://127.0.0.1:11434", settings.ollama_host)
            self.assertEqual("sk-test-value", settings.api_keys.get("OPENAI_API_KEY"))

            ok_clear, _msg_clear = clear_inference_api_key("OPENAI_API_KEY", path=settings_path)
            self.assertTrue(ok_clear)
            settings_cleared = load_inference_settings(settings_path)
            self.assertNotIn("OPENAI_API_KEY", settings_cleared.api_keys)

    def test_discover_runtime_attempts_workspace_bootstrap_when_pi_missing(self) -> None:
        pi_status = self._status("pi", cli_installed=False, ready=False, note="install workspace-local pi runtime")
        offline = self._status("ollama", cli_installed=False, ready=False)
        with (
            patch("takobot.inference._ensure_workspace_pi_runtime_if_needed", return_value="workspace pi bootstrap complete: installed"),
            patch("takobot.inference._detect_pi", return_value=(pi_status, None)),
            patch("takobot.inference._detect_ollama", return_value=(offline, None)),
            patch("takobot.inference._detect_codex", return_value=(self._status("codex", cli_installed=False, ready=False), None)),
            patch("takobot.inference._detect_claude", return_value=(self._status("claude", cli_installed=False, ready=False), None)),
            patch("takobot.inference._detect_gemini", return_value=(self._status("gemini", cli_installed=False, ready=False), None)),
        ):
            runtime = discover_inference_runtime()

        self.assertIsNone(runtime.selected_provider)
        self.assertFalse(runtime.ready)
        self.assertIn("workspace pi bootstrap complete", runtime.statuses["pi"].note)

    def test_discover_runtime_adopts_local_system_key_for_pi(self) -> None:
        pi_status = self._status("pi", cli_installed=True, ready=True, note="pi runtime detected")
        codex_status = self._status(
            "codex",
            cli_installed=False,
            ready=False,
            auth_kind="api_key",
            key_env_var="OPENAI_API_KEY",
            key_source="file:~/.codex/auth.json#OPENAI_API_KEY",
            key_present=True,
        )
        with (
            patch("takobot.inference._ensure_workspace_pi_runtime_if_needed", return_value=""),
            patch("takobot.inference._detect_pi", return_value=(pi_status, None)),
            patch("takobot.inference._detect_ollama", return_value=(self._status("ollama", cli_installed=False, ready=False), None)),
            patch("takobot.inference._detect_codex", return_value=(codex_status, "sk-system-openai")),
            patch("takobot.inference._detect_claude", return_value=(self._status("claude", cli_installed=False, ready=False), None)),
            patch("takobot.inference._detect_gemini", return_value=(self._status("gemini", cli_installed=False, ready=False), None)),
        ):
            runtime = discover_inference_runtime()

        self.assertEqual("pi", runtime.selected_provider)
        self.assertTrue(runtime.ready)
        self.assertEqual("OPENAI_API_KEY", runtime.selected_key_env_var)
        self.assertEqual("sk-system-openai", runtime._api_keys.get("pi"))
        self.assertIn("local system", runtime.statuses["pi"].note)

    def test_auth_inventory_masks_api_keys(self) -> None:
        settings = InferenceSettings(
            preferred_provider="auto",
            ollama_model="",
            ollama_host="",
            api_keys={"OPENAI_API_KEY": "sk-super-secret-value"},
        )
        with (
            patch("takobot.inference.load_inference_settings", return_value=settings),
            patch("takobot.inference.enumerate_pi_oauth_tokens", return_value=["openai-codex (expires=unknown, source=~/auth.json)"]),
        ):
            lines = format_inference_auth_inventory()

        text = "\n".join(lines)
        self.assertIn("persisted API keys:", text)
        self.assertIn("OPENAI_API_KEY", text)
        self.assertNotIn("sk-super-secret-value", text)
        self.assertIn("pi oauth providers:", text)

    def test_workspace_pi_auth_imports_codex_oauth_tokens(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            codex_dir = home / ".codex"
            codex_dir.mkdir(parents=True, exist_ok=True)
            (codex_dir / "auth.json").write_text(
                json.dumps(
                    {
                        "tokens": {
                            "access_token": "codex-access-token",
                            "refresh_token": "codex-refresh-token",
                            "account_id": "acct_123",
                        }
                    }
                ),
                encoding="utf-8",
            )
            agent_dir = Path(tmp) / "agent"
            agent_dir.mkdir(parents=True, exist_ok=True)

            with patch("takobot.inference.Path.home", return_value=home):
                notes = _ensure_workspace_pi_auth(agent_dir)

            auth_payload = json.loads((agent_dir / "auth.json").read_text(encoding="utf-8"))
            self.assertIsInstance(auth_payload, dict)
            codex_entry = auth_payload.get("openai-codex")
            self.assertIsInstance(codex_entry, dict)
            assert isinstance(codex_entry, dict)
            self.assertEqual("oauth", codex_entry.get("type"))
            self.assertEqual("codex-access-token", codex_entry.get("access"))
            self.assertEqual("codex-refresh-token", codex_entry.get("refresh"))
            self.assertEqual("acct_123", codex_entry.get("accountId"))
            self.assertGreater(int(codex_entry.get("expires", 0)), 0)
            self.assertTrue(any("Codex OAuth session" in note for note in notes))

    def test_auto_repair_runtime_returns_split_actions(self) -> None:
        with patch("takobot.inference._ensure_workspace_pi_runtime_if_needed", return_value="step one | step two"):
            actions = auto_repair_inference_runtime()
        self.assertEqual(["step one", "step two"], actions)

    def test_codex_oauth_credential_accepts_nested_oauth_shapes(self) -> None:
        credential = _codex_oauth_credential_from_auth(
            {
                "oauth": {
                    "access": "nested-access",
                    "refresh": "nested-refresh",
                    "accountId": "acct_nested",
                    "expires_at": "2026-02-16T12:00:00+00:00",
                }
            }
        )
        self.assertIsNotNone(credential)
        assert credential is not None
        self.assertEqual("nested-access", credential["access"])
        self.assertEqual("nested-refresh", credential["refresh"])
        self.assertEqual("acct_nested", credential["accountId"])
        self.assertGreater(int(credential["expires"]), 0)

    def test_prepare_pi_login_plan_reports_ready_auth_and_command_candidates(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace_auth = Path(tmp) / "auth.json"
            workspace_auth.write_text(
                json.dumps(
                    {
                        "openai-codex": {
                            "type": "oauth",
                            "access": "a",
                            "refresh": "r",
                            "expires": 1737000000000,
                        }
                    }
                ),
                encoding="utf-8",
            )
            workspace_cli = Path(tmp) / "pi"
            workspace_cli.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
            with (
                patch("takobot.inference._ensure_workspace_pi_runtime_if_needed", return_value="repair note | auth note"),
                patch("takobot.inference._ensure_workspace_pi_auth", return_value=["synced codex oauth"]),
                patch("takobot.inference._workspace_pi_agent_dir", return_value=workspace_auth.parent),
                patch("takobot.inference._workspace_pi_cli_path", return_value=workspace_cli),
                patch("takobot.inference._safe_help_text", return_value="usage: pi auth login"),
            ):
                plan = prepare_pi_login_plan()

        self.assertTrue(plan.auth_ready)
        self.assertIn("synced codex oauth", plan.notes)
        self.assertTrue(any("repair note" in note for note in plan.notes))
        self.assertGreaterEqual(len(plan.commands), 1)
        self.assertIn("pi auth is already available", plan.reason)
