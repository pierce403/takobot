from __future__ import annotations

import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from takobot.tool_ops import run_local_command, workspace_command_path_prefixes


class TestToolOps(unittest.TestCase):
    def test_workspace_command_path_prefixes_include_pi_and_latest_nvm(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            pi_bin = root / ".tako" / "pi" / "node" / "node_modules" / ".bin"
            pi_bin.mkdir(parents=True, exist_ok=True)

            node_name = "node.exe" if os.name == "nt" else "node"
            old_bin = root / ".tako" / "nvm" / "versions" / "node" / "v20.10.0" / "bin"
            old_bin.mkdir(parents=True, exist_ok=True)
            (old_bin / node_name).write_text("", encoding="utf-8")
            new_bin = root / ".tako" / "nvm" / "versions" / "node" / "v22.3.1" / "bin"
            new_bin.mkdir(parents=True, exist_ok=True)
            (new_bin / node_name).write_text("", encoding="utf-8")

            prefixes = workspace_command_path_prefixes(root)

        self.assertEqual(str(pi_bin), prefixes[0])
        self.assertEqual(str(new_bin), prefixes[1])

    def test_run_local_command_respects_path_prefixes(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            bin_dir = root / "bin"
            bin_dir.mkdir(parents=True, exist_ok=True)
            if os.name == "nt":
                script = bin_dir / "hello-cmd.cmd"
                script.write_text("@echo off\necho ok-cmd\n", encoding="utf-8")
                command = "hello-cmd"
            else:
                script = bin_dir / "hello-cmd"
                script.write_text("#!/usr/bin/env bash\necho ok-cmd\n", encoding="utf-8")
                script.chmod(0o755)
                command = "hello-cmd"

            result = run_local_command(command, cwd=root, path_prefixes=[bin_dir])

        self.assertTrue(result.ok, result.output)
        self.assertIn("ok-cmd", result.output)


if __name__ == "__main__":
    unittest.main()
