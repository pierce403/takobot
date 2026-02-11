#!/usr/bin/env python3
"""Backwards-compatible wrapper for the Tako CLI.

Historically this repo exposed a single `tako.py` script that sent one DM.
The new contract is a multi-command CLI (`tako hi|run|doctor`).

This wrapper preserves the old UX:

- `python3 tako.py --to <addr|ens> [--message ...]`
"""

from __future__ import annotations

import sys

from tako_bot.cli import main


def _argv() -> list[str]:
    args = sys.argv[1:]
    if not args:
        return []
    if args[0] in {"-h", "--help", "help", "--version"}:
        return args
    if args[0] in {"app", "hi", "run", "doctor", "bootstrap"}:
        return args
    return ["hi", *args]


if __name__ == "__main__":
    raise SystemExit(main(_argv()))
