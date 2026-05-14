# agent-fleet CLI

One-command installer and config generator for the agent-fleet MCP bridge.

`agent-fleet` turns a physical device (Windows PC, Mac, Android phone) into an
MCP server that any LLM agent (Claude Code, Cursor, Cline, …) can drive over
Tailscale.  The CLI wizard installs the MCP server on the current machine,
walks you through platform permissions / ADB authorization, runs smoke tests,
and outputs ready-to-paste config snippets for six agent frameworks.

## Prerequisites

| Requirement | Notes |
|---|---|
| [uv](https://docs.astral.sh/uv/) | Package/tool runner; install via `curl -LsSf https://astral.sh/uv/install.sh \| sh` (macOS/Linux) or `irm https://astral.sh/uv/install.ps1 \| iex` (Windows) |
| Host OS | Windows 10/11, macOS 12+, or Linux (as agent host only; device bridges run on Windows/macOS) |
| [Tailscale](https://tailscale.com/) | Recommended for cross-machine access; optional for same-machine / LAN setups |

## Install & run

Run the interactive setup wizard directly from the repo — no local clone needed:

```bash
uvx --from "git+https://github.com/metahub-tech/agent-fleet#subdirectory=cli" agent-fleet setup
```

The wizard will guide you through:

1. Select which device role(s) this machine will host (`win-device`, `mac-device`, `android-device`)
2. Choose network mode (LAN or Tailscale)
3. For Android: pick ADB connection mode (USB / Wireless / Hybrid)
4. Install and start the MCP server
5. Walk through required OS permissions (macOS TCC, Android ADB authorization)
6. Run smoke tests against the freshly started server
7. Output config snippets for Claude Code, Cursor, Cline, Copilot, Windsurf, and Zed

> **macOS 12 note:** run `brew install coreutils` before the first invocation
> (`uv`'s wrapper uses `realpath`, which macOS 12 does not ship by default).

## Subcommands

| Command | Description |
|---|---|
| `agent-fleet setup` | Run the interactive setup wizard |
| `agent-fleet --version` | Print the installed version |
| `agent-fleet --help` | Show help |

`setup` accepts `--dry-run` to preview actions without writing anything.

## Development / running tests

```bash
# Clone the repo
git clone https://github.com/metahub-tech/agent-fleet
cd agent-fleet/cli

# Install dependencies (uv creates a venv automatically)
uv sync

# Run the test suite
PYTHONPATH=src python3 -m pytest

# Or with uv
uv run pytest
```

Tests live in `cli/tests/`. The `PYTHONPATH=src` prefix is required because the
package is not installed in editable mode — it is run directly from the source
tree.

For full design documentation see
[`docs/design/2026-05-11-agent-fleet-cli.md`](../docs/design/2026-05-11-agent-fleet-cli.md).
