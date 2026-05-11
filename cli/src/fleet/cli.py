"""CLI entry point. The interactive wizard is implemented in Task 20.

This stub exists so the [project.scripts] entry in pyproject.toml resolves
even on the bootstrap install.
"""
from __future__ import annotations

import sys

import fleet


def main(argv: list[str] | None = None) -> int:
    print(f"agent-fleet v{fleet.__version__}")
    print("CLI wizard is not yet wired up in this alpha build.")
    print("See docs/superpowers/plans/2026-05-11-agent-fleet-cli.md for the implementation plan.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
