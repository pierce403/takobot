from __future__ import annotations

import asyncio
from datetime import datetime, timezone
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
    PI_PROMPT_MAX_LINE_CHARS,
    _pi_cli_thinking_args,
    _stream_with_provider,
    _stream_pi,
    inference_reauth_guidance_lines,
    looks_like_openai_oauth_refresh_failure,
    _codex_oauth_credential_from_auth,
    _ensure_workspace_pi_auth,
    _detect_ollama,
    _detect_pi,
    _pi_node_available,
    _provider_env,
    _run_pi,
    _workspace_node_bin_dir,
    auto_repair_inference_runtime,
    discover_inference_runtime,
    clear_inference_api_key,
    format_inference_auth_inventory,
    format_pi_model_plan_lines,
    load_inference_settings,
    prepare_pi_login_plan,
    resolve_pi_model_profile,
    run_inference_prompt_with_fallback,
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

    def test_workspace_node_bin_dir_ignores_incompatible_versions(self) -> None:
        with TemporaryDirectory() as tmp:
            nvm_dir = Path(tmp) / "nvm"
            node_name = "node.exe" if os.name == "nt" else "node"
            for version in ("v18.19.0", "v19.9.0"):
                bin_dir = nvm_dir / "versions" / "node" / version / "bin"
                bin_dir.mkdir(parents=True, exist_ok=True)
                (bin_dir / node_name).write_text("", encoding="utf-8")

            with patch("takobot.inference._workspace_nvm_dir", return_value=nvm_dir):
                selected = _workspace_node_bin_dir()

        self.assertIsNone(selected)

    def test_pi_node_available_requires_node_20_plus(self) -> None:
        with (
            patch("takobot.inference._workspace_node_bin_dir", return_value=None),
            patch("takobot.inference.shutil.which", return_value="/usr/bin/node"),
            patch(
                "takobot.inference.subprocess.run",
                return_value=SimpleNamespace(returncode=0, stdout="v18.19.0\n", stderr=""),
            ),
        ):
            self.assertFalse(_pi_node_available())

        with (
            patch("takobot.inference._workspace_node_bin_dir", return_value=None),
            patch("takobot.inference.shutil.which", return_value="/usr/bin/node"),
            patch(
                "takobot.inference.subprocess.run",
                return_value=SimpleNamespace(returncode=0, stdout="v20.11.0\n", stderr=""),
            ),
        ):
            self.assertTrue(_pi_node_available())

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
        with (
            patch(
                "takobot.inference._safe_help_text",
                return_value="usage: pi --print --mode <text|json> --no-session --thinking-level <level>",
            ),
            patch(
                "takobot.inference.subprocess.run",
                return_value=SimpleNamespace(returncode=0, stdout="ok", stderr=""),
            ) as run_mock,
        ):
            output = _run_pi(runtime, "hello world", env={}, timeout_s=10.0)

        self.assertEqual("ok", output)
        called_cmd = run_mock.call_args.args[0]
        self.assertIn("--print", called_cmd)
        self.assertIn("--mode", called_cmd)
        self.assertIn("--no-session", called_cmd)
        self.assertIn("--thinking-level", called_cmd)
        self.assertIn("minimal", called_cmd)
        self.assertNotIn("--no-tools", called_cmd)
        self.assertNotIn("--no-extensions", called_cmd)
        self.assertNotIn("--no-skills", called_cmd)

    def test_run_pi_failure_writes_error_log_with_command_details(self) -> None:
        runtime = InferenceRuntime(
            statuses={"pi": self._status("pi", cli_installed=True, ready=True)},
            selected_provider="pi",
            selected_auth_kind="oauth",
            selected_key_env_var=None,
            selected_key_source="oauth",
            _api_keys={},
        )
        with TemporaryDirectory() as tmp:
            error_log = Path(tmp) / "error.log"
            with (
                patch("takobot.inference._safe_help_text", return_value=""),
                patch(
                    "takobot.inference.subprocess.run",
                    return_value=SimpleNamespace(returncode=1, stdout="", stderr="pi exploded"),
                ),
                patch("takobot.inference.inference_error_log_path", return_value=error_log),
            ):
                with self.assertRaises(RuntimeError) as ctx:
                    _run_pi(runtime, "hello world", env={}, timeout_s=10.0)
            self.assertTrue(error_log.exists())
            logged = error_log.read_text(encoding="utf-8")

        self.assertIn("cmd:", str(ctx.exception))
        self.assertIn("log:", str(ctx.exception))
        self.assertIn("provider=pi", logged)
        self.assertIn("command:", logged)
        self.assertIn("--print", logged)
        self.assertIn("stderr_tail:", logged)

    def test_run_pi_wraps_oversized_prompt_lines(self) -> None:
        runtime = InferenceRuntime(
            statuses={"pi": self._status("pi", cli_installed=True, ready=True)},
            selected_provider="pi",
            selected_auth_kind="oauth",
            selected_key_env_var=None,
            selected_key_source="oauth",
            _api_keys={},
        )
        long_line = "x" * (PI_PROMPT_MAX_LINE_CHARS + 250)
        with (
            patch("takobot.inference._safe_help_text", return_value=""),
            patch(
                "takobot.inference.subprocess.run",
                return_value=SimpleNamespace(returncode=0, stdout="ok", stderr=""),
            ) as run_mock,
        ):
            output = _run_pi(runtime, long_line, env={}, timeout_s=10.0)

        self.assertEqual("ok", output)
        called_cmd = run_mock.call_args.args[0]
        prepared_prompt = called_cmd[-1]
        self.assertIn("\n", prepared_prompt)
        self.assertTrue(all(len(line) <= PI_PROMPT_MAX_LINE_CHARS for line in prepared_prompt.splitlines()))

    def test_run_pi_retries_without_optional_flags_when_first_call_fails(self) -> None:
        runtime = InferenceRuntime(
            statuses={"pi": self._status("pi", cli_installed=True, ready=True)},
            selected_provider="pi",
            selected_auth_kind="oauth",
            selected_key_env_var=None,
            selected_key_source="oauth",
            _api_keys={},
        )

        calls: list[list[str]] = []

        def fake_run(cmd, **kwargs):
            calls.append(list(cmd))
            if len(calls) == 1:
                return SimpleNamespace(returncode=1, stdout="", stderr="unknown option --no-session")
            return SimpleNamespace(returncode=0, stdout="ok", stderr="")

        with (
            patch("takobot.inference._safe_help_text", return_value=""),
            patch("takobot.inference.subprocess.run", side_effect=fake_run),
        ):
            output = _run_pi(runtime, "hello world", env={}, timeout_s=10.0)

        self.assertEqual("ok", output)
        self.assertGreaterEqual(len(calls), 2)
        first_cmd = calls[0]
        second_cmd = calls[1]
        self.assertIn("--no-session", first_cmd)
        self.assertNotIn("--no-session", second_cmd)
        self.assertNotIn("--mode", second_cmd)
        self.assertNotIn("--print", second_cmd)

    def test_pi_cli_thinking_args_maps_minimal_to_low_when_unavailable(self) -> None:
        with patch("takobot.inference._safe_help_text", return_value="usage: pi --thinking-level {low,medium,high}"):
            args = _pi_cli_thinking_args("pi", "minimal")
        self.assertEqual(["--thinking-level", "low"], args)

    def test_detects_openai_oauth_refresh_failure_signals(self) -> None:
        error_text = (
            "pi inference failed: [openai-codex] Token refresh failed: 401 "
            '{"error":{"message":"Your refresh token has already been used"}}'
        )
        self.assertTrue(looks_like_openai_oauth_refresh_failure(error_text))
        guidance = inference_reauth_guidance_lines(error_text, local_terminal=True)
        self.assertGreaterEqual(len(guidance), 3)
        self.assertIn("inference login force", " ".join(guidance))

    def test_reauth_guidance_is_empty_for_non_auth_errors(self) -> None:
        error_text = "pi inference failed: exit=1 unknown option --mode"
        self.assertFalse(looks_like_openai_oauth_refresh_failure(error_text))
        self.assertEqual((), inference_reauth_guidance_lines(error_text, local_terminal=True))

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
        self.assertIn("requires node >=", status.note)

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
            patch("takobot.inference._workspace_pi_agent_dir", return_value=Path("/tmp/pi-agent")),
            patch("takobot.inference._ensure_workspace_pi_auth", return_value=[]),
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
            patch("takobot.inference._workspace_pi_agent_dir", return_value=Path("/tmp/pi-agent")),
            patch("takobot.inference._ensure_workspace_pi_auth", return_value=[]),
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

    def test_discover_runtime_appends_pi_auth_sync_notes(self) -> None:
        pi_status = self._status("pi", cli_installed=True, ready=True, note="pi runtime detected")
        with (
            patch("takobot.inference._ensure_workspace_pi_runtime_if_needed", return_value=""),
            patch("takobot.inference._workspace_pi_agent_dir", return_value=Path("/tmp/pi-agent")),
            patch("takobot.inference._ensure_workspace_pi_auth", return_value=["imported local Codex OAuth session into workspace pi auth."]),
            patch("takobot.inference._detect_pi", return_value=(pi_status, None)),
            patch("takobot.inference._detect_ollama", return_value=(self._status("ollama", cli_installed=False, ready=False), None)),
            patch("takobot.inference._detect_codex", return_value=(self._status("codex", cli_installed=False, ready=False), None)),
            patch("takobot.inference._detect_claude", return_value=(self._status("claude", cli_installed=False, ready=False), None)),
            patch("takobot.inference._detect_gemini", return_value=(self._status("gemini", cli_installed=False, ready=False), None)),
        ):
            runtime = discover_inference_runtime()

        self.assertIn("Codex OAuth session", runtime.statuses["pi"].note)

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

    def test_workspace_pi_auth_refreshes_from_newer_home_profile(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            source = home / ".pi" / "agent" / "auth.json"
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text(
                json.dumps(
                    {
                        "openai-codex": {
                            "type": "oauth",
                            "access": "fresh-access",
                            "refresh": "fresh-refresh",
                            "expires": 1737000000000,
                        }
                    }
                ),
                encoding="utf-8",
            )

            agent_dir = Path(tmp) / "agent"
            agent_dir.mkdir(parents=True, exist_ok=True)
            target = agent_dir / "auth.json"
            target.write_text(
                json.dumps(
                    {
                        "openai-codex": {
                            "type": "oauth",
                            "access": "stale-access",
                            "refresh": "stale-refresh",
                            "expires": 1736000000000,
                        }
                    }
                ),
                encoding="utf-8",
            )

            now = int(datetime.now(tz=timezone.utc).timestamp())
            os.utime(target, (now - 120, now - 120))
            os.utime(source, (now, now))

            with patch("takobot.inference.Path.home", return_value=home):
                notes = _ensure_workspace_pi_auth(agent_dir)

            payload = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual("fresh-refresh", payload["openai-codex"]["refresh"])
            self.assertTrue(any("refreshed workspace pi auth from newer" in note for note in notes))

    def test_workspace_pi_auth_keeps_existing_openai_entry_when_codex_import_differs(self) -> None:
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
                            "account_id": "acct_codex",
                        }
                    }
                ),
                encoding="utf-8",
            )
            agent_dir = Path(tmp) / "agent"
            agent_dir.mkdir(parents=True, exist_ok=True)
            target = agent_dir / "auth.json"
            target.write_text(
                json.dumps(
                    {
                        "openai-codex": {
                            "type": "oauth",
                            "access": "workspace-access",
                            "refresh": "workspace-refresh",
                            "expires": 1737000000000,
                            "accountId": "acct_workspace",
                        }
                    }
                ),
                encoding="utf-8",
            )

            with patch("takobot.inference.Path.home", return_value=home):
                notes = _ensure_workspace_pi_auth(agent_dir)

            payload = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual("workspace-refresh", payload["openai-codex"]["refresh"])
            self.assertFalse(any("Codex OAuth session" in note for note in notes))

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

    def test_resolve_pi_model_profile_prefers_project_override(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            home = root / "home"
            workspace = root / "workspace"
            runtime_root = workspace / ".tako"
            (home / ".pi" / "agent").mkdir(parents=True, exist_ok=True)
            (runtime_root / "pi" / "agent").mkdir(parents=True, exist_ok=True)
            (workspace / ".pi").mkdir(parents=True, exist_ok=True)

            (home / ".pi" / "agent" / "settings.json").write_text(
                json.dumps({"defaultModel": "anthropic/claude-sonnet", "defaultThinkingLevel": "low"}),
                encoding="utf-8",
            )
            (runtime_root / "pi" / "agent" / "settings.json").write_text(
                json.dumps({"defaultModel": "openai/gpt-4.1-codex", "defaultThinkingLevel": "medium"}),
                encoding="utf-8",
            )
            (workspace / ".pi" / "settings.json").write_text(
                json.dumps({"defaultModel": "openai/gpt-5.3-codex", "defaultThinkingLevel": "high"}),
                encoding="utf-8",
            )

            with (
                patch("takobot.inference.Path.home", return_value=home),
                patch("takobot.inference.repo_root", return_value=workspace),
                patch("takobot.inference.runtime_paths", return_value=SimpleNamespace(root=runtime_root)),
            ):
                profile = resolve_pi_model_profile()

        self.assertEqual("openai/gpt-5.3-codex", profile.model)
        self.assertEqual("high", profile.thinking)
        self.assertTrue(profile.model_source.endswith(".pi/settings.json"))
        self.assertTrue(profile.thinking_source.endswith(".pi/settings.json"))

    def test_format_pi_model_plan_lines_includes_type1_and_type2(self) -> None:
        with patch(
            "takobot.inference.resolve_pi_model_profile",
            return_value=SimpleNamespace(
                model="openai/gpt-5.3-codex",
                thinking="medium",
                model_source="~/.pi/agent/settings.json",
                thinking_source="~/.pi/agent/settings.json",
            ),
        ):
            lines = format_pi_model_plan_lines(type2_thinking_default="high")
        rendered = "\n".join(lines)
        self.assertIn("type1 model: openai/gpt-5.3-codex", rendered)
        self.assertIn("type2 model: openai/gpt-5.3-codex", rendered)
        self.assertIn("type1 thinking: minimal", rendered)
        self.assertIn("type2 thinking: high", rendered)
        self.assertIn("configured base thinking: medium", rendered)

    def test_stream_pi_emits_model_thinking_and_delta_events(self) -> None:
        runtime = InferenceRuntime(
            statuses={"pi": self._status("pi", cli_installed=True, ready=True)},
            selected_provider="pi",
            selected_auth_kind="oauth",
            selected_key_env_var=None,
            selected_key_source="oauth",
            _api_keys={},
        )
        events: list[tuple[str, str]] = []

        async def fake_run_streaming_process(cmd, *, provider, env, timeout_s, on_stdout_line, on_stderr_line):
            self.assertIn("--mode", cmd)
            self.assertIn("json", cmd)
            self.assertEqual("pi", provider)
            on_stdout_line(
                json.dumps(
                    {
                        "type": "message_update",
                        "assistantMessageEvent": {
                            "type": "thinking_delta",
                            "delta": "Checking likely root causes before responding.",
                            "partial": {"model": {"provider": "openai", "id": "gpt-5.3-codex"}},
                        },
                    }
                )
            )
            on_stdout_line(
                json.dumps(
                    {
                        "type": "message_update",
                        "assistantMessageEvent": {"type": "text_delta", "delta": "Hello there"},
                    }
                )
            )
            on_stdout_line(
                json.dumps(
                    {
                        "type": "message_end",
                        "message": {
                            "role": "assistant",
                            "content": [{"type": "text", "text": "Hello there"}],
                        },
                    }
                )
            )

        with (
            patch(
                "takobot.inference._safe_help_text",
                return_value="usage: pi --mode <text|json> --no-session --thinking-level <level>",
            ),
            patch("takobot.inference._run_streaming_process", side_effect=fake_run_streaming_process),
        ):
            output = asyncio.run(
                _stream_pi(
                    runtime,
                    "hi",
                    env={},
                    timeout_s=10.0,
                    on_event=lambda kind, payload: events.append((kind, payload)),
                )
            )

        self.assertEqual("Hello there", output)
        self.assertTrue(any(kind == "model" and "gpt-5.3-codex" in payload for kind, payload in events))
        self.assertTrue(any(kind == "status" and "pi thinking:" in payload for kind, payload in events))
        self.assertTrue(any(kind == "delta" and "Hello there" in payload for kind, payload in events))

    def test_stream_pi_reports_prompt_guard_status_when_wrapping(self) -> None:
        runtime = InferenceRuntime(
            statuses={"pi": self._status("pi", cli_installed=True, ready=True)},
            selected_provider="pi",
            selected_auth_kind="oauth",
            selected_key_env_var=None,
            selected_key_source="oauth",
            _api_keys={},
        )
        events: list[tuple[str, str]] = []
        long_line = "y" * (PI_PROMPT_MAX_LINE_CHARS + 180)

        async def fake_run_streaming_process(cmd, *, provider, env, timeout_s, on_stdout_line, on_stderr_line):
            prepared_prompt = cmd[-1]
            self.assertIn("\n", prepared_prompt)
            self.assertTrue(all(len(line) <= PI_PROMPT_MAX_LINE_CHARS for line in prepared_prompt.splitlines()))
            on_stdout_line(
                json.dumps(
                    {
                        "type": "message_end",
                        "message": {
                            "role": "assistant",
                            "content": [{"type": "text", "text": "wrapped"}],
                        },
                    }
                )
            )

        with (
            patch(
                "takobot.inference._safe_help_text",
                return_value="usage: pi --mode <text|json> --no-session --thinking-level <level>",
            ),
            patch("takobot.inference._run_streaming_process", side_effect=fake_run_streaming_process),
        ):
            output = asyncio.run(
                _stream_pi(
                    runtime,
                    long_line,
                    env={},
                    timeout_s=10.0,
                    on_event=lambda kind, payload: events.append((kind, payload)),
                )
            )

        self.assertEqual("wrapped", output)
        self.assertTrue(any(kind == "status" and "pi prompt guard: wrapped" in payload for kind, payload in events))

    def test_stream_with_provider_pi_falls_back_to_sync_when_stream_fails(self) -> None:
        runtime = InferenceRuntime(
            statuses={"pi": self._status("pi", cli_installed=True, ready=True)},
            selected_provider="pi",
            selected_auth_kind="oauth",
            selected_key_env_var=None,
            selected_key_source="oauth",
            _api_keys={},
        )
        events: list[tuple[str, str]] = []
        with (
            patch("takobot.inference._stream_pi", side_effect=RuntimeError("stream-json unsupported")),
            patch("takobot.inference._run_pi", return_value="sync response"),
        ):
            output = asyncio.run(
                _stream_with_provider(
                    runtime,
                    "pi",
                    "hello",
                    timeout_s=10.0,
                    on_event=lambda kind, payload: events.append((kind, payload)),
                    thinking="minimal",
                )
            )
        self.assertEqual("sync response", output)
        self.assertTrue(any(kind == "status" and "pi stream fallback" in payload for kind, payload in events))
        self.assertTrue(any(kind == "delta" for kind, _payload in events))

    def test_run_fallback_logs_unexpected_provider_exception(self) -> None:
        runtime = InferenceRuntime(
            statuses={"pi": self._status("pi", cli_installed=True, ready=True)},
            selected_provider="pi",
            selected_auth_kind="oauth",
            selected_key_env_var=None,
            selected_key_source="oauth",
            _api_keys={},
        )
        with (
            patch("takobot.inference._run_with_provider", side_effect=RuntimeError("unexpected boom")),
            patch("takobot.inference._append_inference_error_log", return_value=Path("/tmp/error.log")) as append_mock,
        ):
            with self.assertRaises(RuntimeError):
                run_inference_prompt_with_fallback(runtime, "hello", timeout_s=5.0)

        self.assertGreaterEqual(append_mock.call_count, 1)
        kwargs = append_mock.call_args.kwargs
        self.assertEqual("pi", kwargs.get("provider"))
        self.assertEqual(["pi", "<internal-exception>"], kwargs.get("command"))
