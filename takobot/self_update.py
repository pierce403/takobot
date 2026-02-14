from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess
import sys
import json
import importlib.metadata


GIT_TIMEOUT_S = 45.0
PIP_TIMEOUT_S = 90.0
ENGINE_PACKAGE_NAME = "takobot"


@dataclass(frozen=True)
class SelfUpdateResult:
    ok: bool
    changed: bool
    summary: str
    details: list[str]


def run_self_update(repo_root: Path, *, apply: bool) -> SelfUpdateResult:
    try:
        # Preferred path: update the installed engine package inside the current python env.
        pip_result = _run_pip_self_update(apply=apply)
        if pip_result is not None:
            return pip_result

        # Fallback path (dev checkouts): git fast-forward if this workspace is an engine repo.
        if not _is_git_repo(repo_root):
            return SelfUpdateResult(False, False, "self-update unavailable: not a git repo and pip update not available.", [])

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


def _pip_version() -> str:
    try:
        return importlib.metadata.version(ENGINE_PACKAGE_NAME)
    except Exception:  # noqa: BLE001
        return ""


def _run_pip(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "pip", *args],
        capture_output=True,
        text=True,
        timeout=PIP_TIMEOUT_S,
        check=False,
    )


def _run_pip_self_update(*, apply: bool) -> SelfUpdateResult | None:
    """Attempt engine self-update via pip.

    Returns:
    - SelfUpdateResult when pip strategy is applicable (even if it fails).
    - None when pip strategy isn't applicable (e.g., pip not usable).
    """

    # If pip is unavailable for some reason, skip and let git fallback handle dev checkouts.
    try:
        _run_pip(["--version"])
    except Exception:  # noqa: BLE001
        return None

    before = _pip_version()

    if not apply:
        proc = _run_pip(["list", "--outdated", "--format=json"])
        if proc.returncode != 0:
            return SelfUpdateResult(False, False, "self-update failed: pip outdated check failed.", [_short(proc.stderr or proc.stdout)])
        try:
            payload = json.loads(proc.stdout or "[]")
        except Exception:  # noqa: BLE001
            payload = []
        latest = ""
        for item in payload if isinstance(payload, list) else []:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "")
            if name.lower() != ENGINE_PACKAGE_NAME:
                continue
            latest = str(item.get("latest_version") or "")
            break
        if latest and before and latest != before:
            return SelfUpdateResult(True, False, "update available.", [f"{ENGINE_PACKAGE_NAME}: {before} -> {latest}", "Run `update` to apply."])
        if latest and before and latest == before:
            return SelfUpdateResult(True, False, "already up to date.", [f"{ENGINE_PACKAGE_NAME}: {before}"])
        if before:
            return SelfUpdateResult(True, False, "no update reported by pip.", [f"{ENGINE_PACKAGE_NAME}: {before}"])
        return SelfUpdateResult(True, False, "pip update check complete.", ["engine package not found (maybe installed from source)."])

    proc = _run_pip(["install", "--upgrade", ENGINE_PACKAGE_NAME])
    if proc.returncode != 0:
        return SelfUpdateResult(False, False, "self-update failed: pip upgrade failed.", [_short(proc.stderr or proc.stdout)])

    after = _pip_version()
    changed = bool(before and after and before != after) or (not before and bool(after))
    details: list[str] = []
    if before:
        details.append(f"{ENGINE_PACKAGE_NAME}: {before} -> {after or before}")
    elif after:
        details.append(f"{ENGINE_PACKAGE_NAME}: installed {after}")
    return SelfUpdateResult(True, changed, "self-update complete (pip).", details)


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
