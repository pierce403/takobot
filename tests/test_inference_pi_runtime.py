from __future__ import annotations

import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from takobot.inference import InferenceRuntime, _detect_pi, _provider_env, _workspace_node_bin_dir


class TestInferencePiRuntime(unittest.TestCase):
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
