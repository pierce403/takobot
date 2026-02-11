from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess


GIT_TIMEOUT_S = 45.0


@dataclass(frozen=True)
class SelfUpdateResult:
    ok: bool
    changed: bool
    summary: str
    details: list[str]


def run_self_update(repo_root: Path, *, apply: bool) -> SelfUpdateResult:
    try:
        if not _is_git_repo(repo_root):
            return SelfUpdateResult(False, False, "self-update unavailable: not a git repository.", [])

        dirty = _git(repo_root, "status", "--porcelain")
        if dirty.returncode != 0:
            return SelfUpdateResult(False, False, "self-update failed: unable to inspect git status.", [_short(dirty.stderr)])
        if dirty.stdout.strip():
            return SelfUpdateResult(
                False,
                False,
                "self-update blocked: local changes detected.",
                ["Commit or stash local changes, then retry `update`."],
            )

        fetch = _git(repo_root, "fetch", "--prune", "origin")
        if fetch.returncode != 0:
            return SelfUpdateResult(False, False, "self-update failed: `git fetch` failed.", [_short(fetch.stderr)])

        upstream_ref = _upstream_ref(repo_root)
        counts = _git(repo_root, "rev-list", "--left-right", "--count", f"HEAD...{upstream_ref}")
        if counts.returncode != 0:
            return SelfUpdateResult(
                False,
                False,
                "self-update failed: unable to compare local branch with upstream.",
                [_short(counts.stderr)],
            )

        parts = counts.stdout.strip().split()
        ahead = int(parts[0]) if len(parts) >= 1 and parts[0].isdigit() else 0
        behind = int(parts[1]) if len(parts) >= 2 and parts[1].isdigit() else 0
        details = [f"branch delta: ahead={ahead} behind={behind} vs {upstream_ref}"]

        if behind == 0:
            if ahead > 0:
                return SelfUpdateResult(
                    True,
                    False,
                    "already up to date with upstream; local branch is ahead.",
                    details,
                )
            return SelfUpdateResult(True, False, "already up to date.", details)

        if ahead > 0:
            return SelfUpdateResult(
                False,
                False,
                "self-update blocked: branch has diverged from upstream.",
                details + ["Rebase or merge manually, then retry `update`."],
            )

        if not apply:
            return SelfUpdateResult(True, False, "update available.", details + ["Run `update` to apply fast-forward changes."])

        pull = _git(repo_root, "pull", "--ff-only", "--no-rebase")
        if pull.returncode != 0:
            return SelfUpdateResult(False, False, "self-update failed: `git pull --ff-only` failed.", details + [_short(pull.stderr)])

        return SelfUpdateResult(True, True, "self-update complete (fast-forward applied).", details)
    except Exception as exc:  # noqa: BLE001
        return SelfUpdateResult(False, False, "self-update failed with an unexpected error.", [_short(str(exc))])


def _is_git_repo(repo_root: Path) -> bool:
    proc = _git(repo_root, "rev-parse", "--is-inside-work-tree")
    return proc.returncode == 0 and proc.stdout.strip() == "true"


def _upstream_ref(repo_root: Path) -> str:
    proc = _git(repo_root, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}")
    if proc.returncode == 0:
        value = proc.stdout.strip()
        if value:
            return value
    return "origin/main"


def _git(repo_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo_root), *args],
        capture_output=True,
        text=True,
        timeout=GIT_TIMEOUT_S,
        check=False,
    )


def _short(text: str) -> str:
    value = " ".join(text.strip().split())
    if not value:
        return "no error details available"
    if len(value) <= 220:
        return value
    return f"{value[:217]}..."
