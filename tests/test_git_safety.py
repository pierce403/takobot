from __future__ import annotations

import os
from pathlib import Path
from tempfile import TemporaryDirectory
import subprocess
import unittest
from unittest.mock import patch

from takobot.git_safety import default_git_identity, ensure_local_git_identity


def _run_git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(repo),
        text=True,
        capture_output=True,
        check=False,
    )


class TestGitSafety(unittest.TestCase):
    def test_default_git_identity_uses_bot_name_email_pattern(self) -> None:
        name, email = default_git_identity("Captain Tako")
        self.assertEqual("Captain Tako", name)
        self.assertEqual("captain-tako.tako.eth@xmtp.mx", email)

        fallback_name, fallback_email = default_git_identity("")
        self.assertEqual("Takobot", fallback_name)
        self.assertEqual("takobot.tako.eth@xmtp.mx", fallback_email)

    def test_ensure_local_git_identity_auto_configures_missing_values(self) -> None:
        with TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir(parents=True, exist_ok=True)
            env = {"GIT_CONFIG_GLOBAL": str(Path(tmp) / "global.gitconfig"), "GIT_CONFIG_NOSYSTEM": "1"}
            with patch.dict(os.environ, env, clear=False):
                init = _run_git(repo, "init")
                self.assertEqual(0, init.returncode, init.stderr)

                ok, detail, changed = ensure_local_git_identity(repo, identity_name="Inkster")
                self.assertTrue(ok, detail)
                self.assertTrue(changed)
                self.assertIn("Inkster <inkster.tako.eth@xmtp.mx>", detail)

                name = _run_git(repo, "config", "--local", "--get", "user.name")
                email = _run_git(repo, "config", "--local", "--get", "user.email")
                self.assertEqual("Inkster", name.stdout.strip())
                self.assertEqual("inkster.tako.eth@xmtp.mx", email.stdout.strip())

    def test_ensure_local_git_identity_keeps_existing_values(self) -> None:
        with TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir(parents=True, exist_ok=True)
            env = {"GIT_CONFIG_GLOBAL": str(Path(tmp) / "global.gitconfig"), "GIT_CONFIG_NOSYSTEM": "1"}
            with patch.dict(os.environ, env, clear=False):
                init = _run_git(repo, "init")
                self.assertEqual(0, init.returncode, init.stderr)
                self.assertEqual(0, _run_git(repo, "config", "user.name", "Existing Bot").returncode)
                self.assertEqual(0, _run_git(repo, "config", "user.email", "existing@example.com").returncode)

                ok, detail, changed = ensure_local_git_identity(repo, identity_name="Different Bot")
                self.assertTrue(ok, detail)
                self.assertFalse(changed)
                self.assertIn("Existing Bot <existing@example.com>", detail)
