from __future__ import annotations

from dataclasses import dataclass
import os
import re
import shutil
import subprocess
from pathlib import Path

from .node_runtime import (
    NODE_RUNTIME_MIN_MAJOR,
    ensure_workspace_node_runtime,
    node_major_from_version,
    summarize_error_text,
    workspace_node_bin_dir,
)
from .paths import ensure_runtime_dirs, runtime_paths


XMTP_CLI_PACKAGE = "@xmtp/cli"
XMTP_CLI_VERSION = "0.2.0"
XMTP_CLI_TIMEOUT_S = 45
XMTP_MIN_NODE_MAJOR = NODE_RUNTIME_MIN_MAJOR

_VERSION_PATTERNS = (
    re.compile(r"@xmtp/cli/([0-9][0-9A-Za-z._-]*)"),
    re.compile(r"xmtp-cli/([0-9][0-9A-Za-z._-]*)"),
)


@dataclass(frozen=True)
class XmtpRuntimeProbe:
    cli_installed: bool
    cli_path: str | None
    cli_version: str | None
    node_ready: bool
    node_version: str | None
    node_source: str | None
    ok: bool
    status: str


def workspace_xmtp_prefix() -> Path:
    paths = ensure_runtime_dirs(runtime_paths())
    return paths.root / "xmtp" / "node"


def workspace_xmtp_cli_path() -> Path:
    root = workspace_xmtp_prefix() / "node_modules" / ".bin"
    executable = "xmtp.cmd" if os.name == "nt" else "xmtp"
    return root / executable


def workspace_xmtp_helper_script_path() -> Path:
    return workspace_xmtp_prefix() / "takobot-profile-sync.mjs"


def ensure_workspace_xmtp_runtime_if_needed() -> str:
    probe = probe_xmtp_runtime()
    if probe.cli_installed and probe.node_ready and probe.cli_version == XMTP_CLI_VERSION:
        return ""
    ok, detail = _ensure_workspace_xmtp_runtime()
    prefix = "workspace xmtp bootstrap complete" if ok else "workspace xmtp bootstrap failed"
    return f"{prefix}: {detail}"


def probe_xmtp_runtime() -> XmtpRuntimeProbe:
    cli_path = workspace_xmtp_cli_path()
    cli_installed = cli_path.exists()

    node_bin_dir = workspace_node_bin_dir(min_major=XMTP_MIN_NODE_MAJOR)
    node_source = None
    node_version = None
    node_ready = False

    if node_bin_dir is not None:
        node_exec = node_bin_dir / ("node.exe" if os.name == "nt" else "node")
        raw_version = _node_version_text(str(node_exec))
        major = node_major_from_version(raw_version)
        if major is not None:
            node_ready = major >= XMTP_MIN_NODE_MAJOR
            node_source = str(node_exec)
            node_version = f"v{major}"

    if not node_ready:
        system_node = shutil.which("node")
        if system_node:
            raw_version = _node_version_text(system_node)
            major = node_major_from_version(raw_version)
            if major is not None:
                node_version = f"v{major}"
                node_source = system_node
                node_ready = major >= XMTP_MIN_NODE_MAJOR

    cli_version = None
    if cli_installed:
        cli_version = _xmtp_cli_version(cli_path)

    ok = cli_installed and node_ready and (cli_version == XMTP_CLI_VERSION)
    if not cli_installed:
        status = f"workspace CLI missing (`{cli_path}`); run startup/bootstrap to install {XMTP_CLI_PACKAGE}@{XMTP_CLI_VERSION}"
    elif not node_ready:
        status = f"CLI detected but compatible node runtime is unavailable (requires node >= {XMTP_MIN_NODE_MAJOR})"
    elif not cli_version:
        status = f"CLI detected but version probe failed ({cli_path})"
    elif cli_version != XMTP_CLI_VERSION:
        status = f"CLI version mismatch: found {cli_version}, expected {XMTP_CLI_VERSION}"
    else:
        status = f"runtime ready ({cli_path}, version={cli_version})"

    return XmtpRuntimeProbe(
        cli_installed=cli_installed,
        cli_path=str(cli_path) if cli_installed else None,
        cli_version=cli_version,
        node_ready=node_ready,
        node_version=node_version,
        node_source=node_source,
        ok=ok,
        status=status,
    )


def _ensure_workspace_xmtp_runtime() -> tuple[bool, str]:
    paths = ensure_runtime_dirs(runtime_paths())
    runtime = ensure_workspace_node_runtime(min_major=XMTP_MIN_NODE_MAJOR, require_npm=True)
    if not runtime.ok:
        return False, runtime.detail
    if not runtime.npm_executable:
        return False, "npm executable unavailable after node runtime bootstrap"

    npm_cache = paths.root / "npm-cache"
    prefix = workspace_xmtp_prefix()
    npm_cache.mkdir(parents=True, exist_ok=True)
    prefix.mkdir(parents=True, exist_ok=True)

    cli_path = workspace_xmtp_cli_path()
    existing_version = _xmtp_cli_version(cli_path) if cli_path.exists() else None
    if existing_version == XMTP_CLI_VERSION:
        return True, f"workspace-local xmtp runtime already present ({cli_path})"

    cmd = [
        runtime.npm_executable,
        "--cache",
        str(npm_cache),
        "--prefix",
        str(prefix),
        "install",
        "--no-audit",
        "--no-fund",
        "--silent",
        f"{XMTP_CLI_PACKAGE}@{XMTP_CLI_VERSION}",
    ]
    proc = subprocess.run(
        cmd,
        check=False,
        capture_output=True,
        text=True,
        timeout=600,
        env=runtime.env,
    )
    if proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip() or f"exit={proc.returncode}"
        return False, f"npm install failed: {summarize_error_text(detail)}"

    if not cli_path.exists():
        return False, f"npm install completed but `{cli_path}` is missing"
    actual_version = _xmtp_cli_version(cli_path)
    if actual_version != XMTP_CLI_VERSION:
        return False, f"installed xmtp cli version `{actual_version or 'unknown'}` (expected `{XMTP_CLI_VERSION}`)"
    return True, f"workspace-local xmtp runtime installed at `{cli_path}` (version={actual_version})"


def _xmtp_cli_version(cli_path: Path) -> str | None:
    if not cli_path.exists():
        return None
    env = _workspace_cli_probe_env()
    try:
        proc = subprocess.run(
            [str(cli_path), "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=XMTP_CLI_TIMEOUT_S,
            env=env,
        )
    except Exception:
        return None
    text = "\n".join(part for part in ((proc.stdout or "").strip(), (proc.stderr or "").strip()) if part)
    for pattern in _VERSION_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(1).strip()
    return None


def _workspace_cli_probe_env() -> dict[str, str]:
    env = os.environ.copy()
    node_bin_dir = workspace_node_bin_dir(min_major=XMTP_MIN_NODE_MAJOR)
    if node_bin_dir is not None:
        current_path = env.get("PATH", "")
        env["PATH"] = f"{node_bin_dir}{os.pathsep}{current_path}" if current_path else str(node_bin_dir)
    return env


def _node_version_text(node_path: str) -> str:
    try:
        proc = subprocess.run(
            [node_path, "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=4.0,
        )
    except Exception:
        return ""
    return (proc.stdout or proc.stderr or "").strip()
