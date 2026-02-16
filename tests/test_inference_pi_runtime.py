from __future__ import annotations

import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from takobot.inference import (
    InferenceRuntime,
    InferenceProviderStatus,
    InferenceSettings,
    _detect_ollama,
    _detect_pi,
    _provider_env,
    _workspace_node_bin_dir,
    discover_inference_runtime,
    clear_inference_api_key,
    format_inference_auth_inventory,
    load_inference_settings,
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
