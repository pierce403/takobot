from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class TestPackagingShellScript(unittest.TestCase):
    def test_tako_shell_script_is_packaged_for_install(self) -> None:
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        manifest = (ROOT / "MANIFEST.in").read_text(encoding="utf-8")
        script = (ROOT / "tako.sh").read_text(encoding="utf-8")
        self.assertIn("script-files = [\"tako.sh\"]", pyproject)
        self.assertIn("include tako.sh", manifest)
        self.assertIn("templates/**/*", pyproject)
        self.assertTrue((ROOT / "takobot" / "templates" / "workspace" / "tako.sh").exists())
        self.assertIn("$ROOT/.venv/bin/takobot", script)


if __name__ == "__main__":
    unittest.main()
