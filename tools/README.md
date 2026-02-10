# tools/ — Tool Contract

Tools are optional, operator-enabled capabilities that Tako can invoke. This directory is the canonical home for tool implementations.

## Discovery

Tools are discovered by scanning subdirectories of `tools/` for a `tool.py` file:

- `tools/<tool_name>/tool.py`

## Minimal Interface (v0)

Each `tool.py` must export:

- `TOOL_MANIFEST`: a dict with:
  - `name` (string)
  - `description` (string)
  - `permissions` (list of strings)
  - `entrypoint` (string function name, typically `"run"`)
- `run(input: dict, ctx: dict) -> dict`

The loader imports the module, reads `TOOL_MANIFEST`, and calls the entrypoint function.

## Permissions Model

Tools must declare the minimum permissions they need. Example tags (extend as needed):

- `read_repo`: read git-tracked files
- `write_repo`: write git-tracked files (requires operator approval)
- `read_runtime`: read `.tako/**`
- `write_runtime`: write `.tako/**`
- `network`: outbound network calls
- `comms_xmtp`: send messages over XMTP

Operator policy should default to:

- tools disabled
- no `write_repo` without explicit operator confirmation
- no `network` unless explicitly enabled

## Examples

Directory layout:

- `tools/memory_append/tool.py`
- `tools/task_create/tool.py`

Example manifest:

```python
TOOL_MANIFEST = {
    "name": "memory_append",
    "description": "Append a note to today’s memory daily log (no secrets).",
    "permissions": ["write_repo"],
    "entrypoint": "run",
}
```
