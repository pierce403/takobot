from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Callable


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    permissions: list[str]
    entrypoint: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]


def _load_module(path: Path, module_name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(module_name, str(path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to import tool module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[call-arg]
    return module


def discover_tools(tools_root: Path) -> list[Tool]:
    if not tools_root.exists():
        return []

    tools: list[Tool] = []
    for item in sorted(tools_root.iterdir()):
        if not item.is_dir():
            continue
        tool_py = item / "tool.py"
        if not tool_py.exists():
            continue

        module = _load_module(tool_py, f"tako_tool_{item.name}")
        manifest = getattr(module, "TOOL_MANIFEST", None)
        if not isinstance(manifest, dict):
            continue

        name = manifest.get("name")
        description = manifest.get("description")
        permissions = manifest.get("permissions")
        entrypoint_name = manifest.get("entrypoint", "run")
        entrypoint = getattr(module, entrypoint_name, None)

        if not isinstance(name, str) or not name:
            continue
        if not isinstance(description, str) or not description:
            continue
        if not isinstance(permissions, list) or not all(isinstance(p, str) for p in permissions):
            continue
        if not callable(entrypoint):
            continue

        tools.append(
            Tool(
                name=name,
                description=description,
                permissions=list(permissions),
                entrypoint=entrypoint,
            )
        )
    return tools

