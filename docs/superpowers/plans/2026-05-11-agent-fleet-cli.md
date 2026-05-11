# agent-fleet CLI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `uvx agent-fleet setup` — a single-device wizard that installs MCP server(s), guides through GUI permissions / ADB authorization, and generates agent-client config snippets for 6 frameworks, replacing the current "read 5 docs and copy 3 scripts" flow.

**Architecture:** Python package `agent-fleet` (module `fleet`) distributed via uvx. Wizard layer is pure Python + questionary TUI; calls existing `platforms/<plat>/scripts/setup-{platform}.{ps1,sh}` as subprocess backends. Internal abstractions: `BaseInstaller` per (OS, role) and `BaseFrameworkConfig` per agent framework. Guidance text stored in YAML under `cli/src/fleet/guidance/` with OEM/version variants. Tests use pytest with mocked subprocess / network / TUI.

**Tech Stack:** Python ≥3.10, `fastmcp` ≥3.2 (existing), `mcp` (existing), `pyyaml`, `questionary`, `httpx`, `rich` (formatting), `pytest`, `pytest-mock`. Distribution: `pyproject.toml` with `[project.scripts] agent-fleet = "fleet.cli:main"`, runnable via `uvx agent-fleet setup`.

**Spec reference:** [`docs/design/2026-05-11-agent-fleet-cli.md`](../../design/2026-05-11-agent-fleet-cli.md)

**Working directory throughout:** repo root `/home/worker/claude-test/claude-remote/agent-test-bench/` (the repo, soon to be renamed `agent-fleet`).

---

## Phase 0 — Bootstrap

### Task 1: Create `cli/` package skeleton

**Files:**
- Create: `cli/pyproject.toml`
- Create: `cli/src/fleet/__init__.py`
- Create: `cli/tests/__init__.py`
- Create: `cli/tests/test_smoke.py`
- Create: `cli/README.md`

- [ ] **Step 1: Write `cli/pyproject.toml`**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "agent-fleet"
version = "0.5.0a1"
description = "One-command CLI to install agent-fleet MCP servers and generate agent-client config."
readme = "README.md"
requires-python = ">=3.10"
license = {text = "Apache-2.0"}
authors = [{name = "MetaHub Tech"}]
classifiers = [
    "License :: OSI Approved :: Apache Software License",
    "Programming Language :: Python :: 3",
    "Operating System :: Microsoft :: Windows",
    "Operating System :: MacOS",
    "Operating System :: POSIX :: Linux",
]
dependencies = [
    "questionary>=2.0",
    "pyyaml>=6.0",
    "httpx>=0.28",
    "rich>=13.0",
    "mcp>=1.0",
]

[project.scripts]
agent-fleet = "fleet.cli:main"

[project.optional-dependencies]
dev = ["pytest>=8.0", "pytest-mock>=3.12"]

[tool.hatch.build.targets.wheel]
packages = ["src/fleet"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 2: Write `cli/src/fleet/__init__.py`**

```python
"""agent-fleet: one-command CLI wizard for MCP server install + agent-client config gen."""

__version__ = "0.5.0a1"
```

- [ ] **Step 3: Write `cli/tests/__init__.py` (empty file)**

```python
```

- [ ] **Step 4: Write smoke test `cli/tests/test_smoke.py`**

```python
def test_package_imports():
    import fleet
    assert fleet.__version__ == "0.5.0a1"
```

- [ ] **Step 5: Write `cli/README.md`**

```markdown
# agent-fleet CLI

One-command MCP server installer and agent-client config generator.

```bash
uvx agent-fleet setup
```

See `docs/design/2026-05-11-agent-fleet-cli.md` for the full design.
```

- [ ] **Step 6: Verify package builds and test passes**

Run:
```bash
cd cli && python -m pip install -e .[dev]
pytest tests/test_smoke.py -v
```
Expected:
```
tests/test_smoke.py::test_package_imports PASSED
```

- [ ] **Step 7: Commit**

```bash
git add cli/
git commit -m "feat(cli): bootstrap agent-fleet package skeleton"
```

---

## Phase 1 — Core types & detection

### Task 2: Define core dataclasses

**Files:**
- Create: `cli/src/fleet/types.py`
- Create: `cli/tests/test_types.py`

- [ ] **Step 1: Write test `cli/tests/test_types.py`**

```python
from fleet.types import OSInfo, ServerRole, VerifyResult, InstallContext, InstallEvent, GuidanceStep, GuidanceVariant


def test_os_info_basic():
    o = OSInfo(system="Darwin", version="12.7.6", arch="x86_64", is_apple_silicon=False)
    assert o.kind == "macos"


def test_os_info_kind_windows():
    o = OSInfo(system="Windows", version="11", arch="AMD64", is_apple_silicon=False)
    assert o.kind == "windows"


def test_os_info_kind_linux():
    o = OSInfo(system="Linux", version="6.5", arch="x86_64", is_apple_silicon=False)
    assert o.kind == "linux"


def test_server_role_url():
    r = ServerRole(role_id="macbox-gui", display_name="macOS desktop", hostname="mac-test", port=8767)
    assert r.url == "http://mac-test:8767/mcp"


def test_verify_result_default():
    v = VerifyResult(ok=True, tool_count=31)
    assert v.ok and v.tool_count == 31
    assert v.error is None


def test_guidance_step_default_only():
    s = GuidanceStep(title="Open dev options", default_description="long-press version 7×")
    assert s.title == "Open dev options"
    assert s.variants == {}
```

- [ ] **Step 2: Run test, confirm it fails**

```bash
pytest cli/tests/test_types.py -v
```
Expected: ImportError / ModuleNotFoundError.

- [ ] **Step 3: Write `cli/src/fleet/types.py`**

```python
"""Core dataclasses used across the wizard."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Literal, Optional


@dataclass
class OSInfo:
    system: str          # "Darwin" / "Windows" / "Linux"
    version: str
    arch: str            # "x86_64" / "arm64" / "AMD64"
    is_apple_silicon: bool

    @property
    def kind(self) -> Literal["macos", "windows", "linux", "unknown"]:
        s = self.system.lower()
        if s == "darwin":
            return "macos"
        if s == "windows":
            return "windows"
        if s == "linux":
            return "linux"
        return "unknown"


@dataclass
class ServerRole:
    role_id: str               # "macbox-gui" / "winpc-gui" / "android-gui"
    display_name: str
    hostname: str
    port: int

    @property
    def url(self) -> str:
        return f"http://{self.hostname}:{self.port}/mcp"


@dataclass
class VerifyResult:
    ok: bool
    tool_count: int = 0
    error: Optional[str] = None
    details: dict = field(default_factory=dict)


@dataclass
class InstallContext:
    repo_root: str             # absolute path to agent-fleet repo
    os_info: OSInfo
    dry_run: bool = False
    selected_network: Literal["lan", "tailscale"] = "tailscale"
    tailscale_hostname: Optional[str] = None


@dataclass
class InstallEvent:
    """Streamed during install — wizard renders these as live progress."""
    role_id: str
    stage: str                 # "preflight" / "deps" / "service" / "verify"
    message: str
    level: Literal["info", "warn", "error"] = "info"


@dataclass
class GuidanceVariant:
    label: str                 # e.g. "华为 / HarmonyOS / EMUI"
    description: str           # path / instruction text


@dataclass
class GuidanceStep:
    title: str
    default_description: str
    variants: dict[str, GuidanceVariant] = field(default_factory=dict)
    variant_label: str = ""    # e.g. "Android 品牌"
    verify_fn: Optional[Callable[[], bool]] = None
    verify_label: str = ""     # e.g. "wizard runs pyautogui.position()"
```

- [ ] **Step 4: Run test, confirm pass**

```bash
pytest cli/tests/test_types.py -v
```
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add cli/src/fleet/types.py cli/tests/test_types.py
git commit -m "feat(cli): core dataclasses (OSInfo, ServerRole, VerifyResult, ...)"
```

---

### Task 3: OS / environment detection

**Files:**
- Create: `cli/src/fleet/detect.py`
- Create: `cli/tests/test_detect.py`

- [ ] **Step 1: Write test `cli/tests/test_detect.py`**

```python
import platform
from unittest.mock import patch
from fleet.detect import detect_os, detect_uv, detect_tailscale


@patch("platform.system", return_value="Darwin")
@patch("platform.release", return_value="22.0.0")
@patch("platform.machine", return_value="x86_64")
def test_detect_os_macos(m1, m2, m3):
    o = detect_os()
    assert o.kind == "macos"
    assert o.arch == "x86_64"
    assert o.is_apple_silicon is False


@patch("platform.system", return_value="Darwin")
@patch("platform.release", return_value="23.0.0")
@patch("platform.machine", return_value="arm64")
def test_detect_os_apple_silicon(m1, m2, m3):
    o = detect_os()
    assert o.is_apple_silicon is True


@patch("shutil.which", return_value="/usr/local/bin/uv")
def test_detect_uv_present(m):
    found = detect_uv()
    assert found is not None
    assert "uv" in found


@patch("shutil.which", return_value=None)
def test_detect_uv_absent(m):
    found = detect_uv()
    assert found is None


@patch("subprocess.run")
def test_detect_tailscale_logged_in(mock_run):
    class R:
        returncode = 0
        stdout = '{"Self": {"HostName": "mac-test", "DNSName": "mac-test.tailb15936.ts.net."}}'
    mock_run.return_value = R()
    ts = detect_tailscale()
    assert ts is not None
    assert ts.hostname == "mac-test"


@patch("subprocess.run", side_effect=FileNotFoundError)
def test_detect_tailscale_missing(mock_run):
    assert detect_tailscale() is None
```

- [ ] **Step 2: Run test, fail**

```bash
pytest cli/tests/test_detect.py -v
```
Expected: ImportError.

- [ ] **Step 3: Write `cli/src/fleet/detect.py`**

```python
"""Detect OS, uv, Tailscale, prior deployment."""
from __future__ import annotations

import json
import platform
import shutil
import subprocess
from dataclasses import dataclass
from typing import Optional

from .types import OSInfo


@dataclass
class TailscaleStatus:
    hostname: str
    fqdn: str
    ip: Optional[str] = None


def detect_os() -> OSInfo:
    system = platform.system()
    version = platform.release()
    arch = platform.machine()
    is_arm_mac = system == "Darwin" and arch.lower() in ("arm64", "aarch64")
    return OSInfo(system=system, version=version, arch=arch, is_apple_silicon=is_arm_mac)


def detect_uv() -> Optional[str]:
    return shutil.which("uv")


def detect_tailscale() -> Optional[TailscaleStatus]:
    try:
        r = subprocess.run(
            ["tailscale", "status", "--json"],
            capture_output=True, text=True, timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0 or not r.stdout.strip():
        return None
    try:
        data = json.loads(r.stdout)
        self_node = data.get("Self") or {}
        host = self_node.get("HostName")
        fqdn = (self_node.get("DNSName") or "").rstrip(".")
        if not host:
            return None
        return TailscaleStatus(hostname=host, fqdn=fqdn or host)
    except (json.JSONDecodeError, KeyError):
        return None


def detect_existing_deployment(role_id: str, port: int) -> bool:
    """Quick port-listen check — if the port is open locally we assume something is deployed."""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.5)
    try:
        r = s.connect_ex(("127.0.0.1", port))
        return r == 0
    finally:
        s.close()
```

- [ ] **Step 4: Run test, pass**

```bash
pytest cli/tests/test_detect.py -v
```
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add cli/src/fleet/detect.py cli/tests/test_detect.py
git commit -m "feat(cli): detect OS / uv / Tailscale / existing deployment"
```

---

## Phase 2 — Framework config generators (Claude Code + Cursor + Cline)

### Task 4: BaseFrameworkConfig ABC + registry

**Files:**
- Create: `cli/src/fleet/frameworks/__init__.py`
- Create: `cli/src/fleet/frameworks/base.py`
- Create: `cli/tests/test_frameworks_base.py`

- [ ] **Step 1: Write test**

```python
# cli/tests/test_frameworks_base.py
import pytest
from fleet.frameworks.base import BaseFrameworkConfig, ServerRoleEntry


class DummyFramework(BaseFrameworkConfig):
    framework_id = "dummy"
    display_name = "Dummy"
    config_format = "json"
    config_path_template = "~/.dummy.json"

    def render_entry(self, role):
        return {"url": role.url}

    def render_full_snippet(self, entries):
        import json
        d = {"servers": {e.role.role_id: self.render_entry(e.role) for e in entries}}
        return json.dumps(d, indent=2)


def test_base_framework_required_fields():
    with pytest.raises(TypeError):
        BaseFrameworkConfig()  # abstract


def test_dummy_render():
    from fleet.types import ServerRole
    role = ServerRole(role_id="x", display_name="X", hostname="h", port=1234)
    fw = DummyFramework()
    entry = fw.render_entry(role)
    assert entry["url"] == "http://h:1234/mcp"
```

- [ ] **Step 2: Run, fail with ImportError**

```bash
pytest cli/tests/test_frameworks_base.py -v
```

- [ ] **Step 3: Write `cli/src/fleet/frameworks/__init__.py`**

```python
"""Per-agent-framework MCP config generators."""
from .base import BaseFrameworkConfig, ServerRoleEntry

__all__ = ["BaseFrameworkConfig", "ServerRoleEntry"]
```

- [ ] **Step 4: Write `cli/src/fleet/frameworks/base.py`**

```python
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal, Optional

from ..types import ServerRole


@dataclass
class ServerRoleEntry:
    role: ServerRole


class BaseFrameworkConfig(ABC):
    framework_id: str = ""
    display_name: str = ""
    config_format: Literal["json", "yaml"] = "json"
    config_path_template: str = ""   # ~/.foo/bar.json

    @abstractmethod
    def render_entry(self, role: ServerRole) -> dict:
        """Return the framework-specific dict for a single MCP server entry."""

    @abstractmethod
    def render_full_snippet(self, entries: list[ServerRoleEntry]) -> str:
        """Return the complete snippet (including the outer mcpServers / mcp.servers / etc. wrapper)."""

    def cli_alternative(self) -> Optional[str]:
        """Return an equivalent CLI command string, if the framework offers one."""
        return None

    def notes(self) -> str:
        """Free-text notes printed to the user. Subclasses override."""
        return ""
```

- [ ] **Step 5: Run, pass**

```bash
pytest cli/tests/test_frameworks_base.py -v
```
Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add cli/src/fleet/frameworks/
git commit -m "feat(cli): BaseFrameworkConfig ABC"
```

---

### Task 5: Claude Code + Cursor configs

**Files:**
- Create: `cli/src/fleet/frameworks/claude_code.py`
- Create: `cli/src/fleet/frameworks/cursor.py`
- Create: `cli/tests/test_frameworks_jsonhttp.py`

- [ ] **Step 1: Write test**

```python
# cli/tests/test_frameworks_jsonhttp.py
import json
from fleet.types import ServerRole
from fleet.frameworks.base import ServerRoleEntry
from fleet.frameworks.claude_code import ClaudeCodeConfig
from fleet.frameworks.cursor import CursorConfig


def _role(name, port):
    return ServerRole(role_id=name, display_name=name, hostname="test-host", port=port)


def test_claude_code_single_entry():
    fw = ClaudeCodeConfig()
    role = _role("macbox-gui", 8767)
    e = fw.render_entry(role)
    assert e == {"type": "http", "url": "http://test-host:8767/mcp"}


def test_claude_code_full_snippet():
    fw = ClaudeCodeConfig()
    entries = [ServerRoleEntry(role=_role("macbox-gui", 8767)),
               ServerRoleEntry(role=_role("android-gui", 8768))]
    out = json.loads(fw.render_full_snippet(entries))
    assert "mcpServers" in out
    assert set(out["mcpServers"].keys()) == {"macbox-gui", "android-gui"}
    assert out["mcpServers"]["macbox-gui"]["type"] == "http"


def test_cursor_same_shape_as_claude():
    fw = CursorConfig()
    role = _role("macbox-gui", 8767)
    e = fw.render_entry(role)
    assert e == {"type": "http", "url": "http://test-host:8767/mcp"}


def test_cursor_path():
    assert "~/.cursor/mcp.json" in CursorConfig().config_path_template
```

- [ ] **Step 2: Run, fail**

```bash
pytest cli/tests/test_frameworks_jsonhttp.py -v
```

- [ ] **Step 3: Write `cli/src/fleet/frameworks/claude_code.py`**

```python
import json
from .base import BaseFrameworkConfig, ServerRoleEntry
from ..types import ServerRole


class ClaudeCodeConfig(BaseFrameworkConfig):
    framework_id = "claude-code"
    display_name = "Claude Code"
    config_format = "json"
    config_path_template = "~/.claude.json"

    def render_entry(self, role: ServerRole) -> dict:
        return {"type": "http", "url": role.url}

    def render_full_snippet(self, entries: list[ServerRoleEntry]) -> str:
        body = {"mcpServers": {e.role.role_id: self.render_entry(e.role) for e in entries}}
        return json.dumps(body, indent=2, ensure_ascii=False)

    def cli_alternative(self) -> str | None:
        # Claude Code does not currently ship a CLI for editing mcpServers in ~/.claude.json
        return None

    def notes(self) -> str:
        return ("Merge the mcpServers block into ~/.claude.json (top-level single-file state, "
                "NOT ~/.claude/settings.json). Restart Claude Code after editing.")
```

- [ ] **Step 4: Write `cli/src/fleet/frameworks/cursor.py`**

```python
import json
from .base import BaseFrameworkConfig, ServerRoleEntry
from ..types import ServerRole


class CursorConfig(BaseFrameworkConfig):
    framework_id = "cursor"
    display_name = "Cursor"
    config_format = "json"
    config_path_template = "~/.cursor/mcp.json"

    def render_entry(self, role: ServerRole) -> dict:
        return {"type": "http", "url": role.url}

    def render_full_snippet(self, entries: list[ServerRoleEntry]) -> str:
        body = {"mcpServers": {e.role.role_id: self.render_entry(e.role) for e in entries}}
        return json.dumps(body, indent=2, ensure_ascii=False)

    def notes(self) -> str:
        return "Write the snippet to ~/.cursor/mcp.json (create parent dirs if missing)."
```

- [ ] **Step 5: Run, pass**

```bash
pytest cli/tests/test_frameworks_jsonhttp.py -v
```
Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
git add cli/src/fleet/frameworks/claude_code.py cli/src/fleet/frameworks/cursor.py cli/tests/test_frameworks_jsonhttp.py
git commit -m "feat(cli): Claude Code + Cursor framework configs (type=http /mcp)"
```

---

### Task 6: Cline (VSCode) + OpenClaw + Antigravity + Hermes configs

**Files:**
- Create: `cli/src/fleet/frameworks/cline.py`
- Create: `cli/src/fleet/frameworks/openclaw.py`
- Create: `cli/src/fleet/frameworks/antigravity.py`
- Create: `cli/src/fleet/frameworks/hermes.py`
- Create: `cli/tests/test_frameworks_other.py`

- [ ] **Step 1: Write tests**

```python
# cli/tests/test_frameworks_other.py
import json
import yaml as pyyaml
from fleet.types import ServerRole
from fleet.frameworks.base import ServerRoleEntry
from fleet.frameworks.cline import ClineConfig
from fleet.frameworks.openclaw import OpenClawConfig
from fleet.frameworks.antigravity import AntigravityConfig
from fleet.frameworks.hermes import HermesConfig


def _role(name, port):
    return ServerRole(role_id=name, display_name=name, hostname="test-host", port=port)


def test_cline_renders_type_http():
    fw = ClineConfig()
    e = fw.render_entry(_role("macbox-gui", 8767))
    assert e == {"type": "http", "url": "http://test-host:8767/mcp"}


def test_openclaw_uses_transport_field():
    fw = OpenClawConfig()
    e = fw.render_entry(_role("macbox-gui", 8767))
    assert e == {"transport": "streamable-http", "url": "http://test-host:8767/mcp"}


def test_openclaw_snippet_uses_mcp_servers_nesting():
    fw = OpenClawConfig()
    out = json.loads(fw.render_full_snippet([ServerRoleEntry(role=_role("x", 1))]))
    assert "mcp" in out and "servers" in out["mcp"]


def test_openclaw_cli_alt_present():
    fw = OpenClawConfig()
    assert fw.cli_alternative()
    assert "openclaw mcp set" in fw.cli_alternative()


def test_antigravity_uses_httpUrl():
    fw = AntigravityConfig()
    e = fw.render_entry(_role("macbox-gui", 8767))
    assert e == {"httpUrl": "http://test-host:8767/mcp"}


def test_hermes_yaml_output():
    fw = HermesConfig()
    out = fw.render_full_snippet([ServerRoleEntry(role=_role("macbox-gui", 8767))])
    parsed = pyyaml.safe_load(out)
    assert "mcp_servers" in parsed
    assert parsed["mcp_servers"]["macbox-gui"]["url"] == "http://test-host:8767/mcp"
```

- [ ] **Step 2: Run, fail**

```bash
pytest cli/tests/test_frameworks_other.py -v
```

- [ ] **Step 3: Write `cli/src/fleet/frameworks/cline.py`**

```python
import json
from .base import BaseFrameworkConfig, ServerRoleEntry
from ..types import ServerRole


class ClineConfig(BaseFrameworkConfig):
    framework_id = "cline"
    display_name = "Cline (VSCode extension)"
    config_format = "json"
    config_path_template = (
        "VSCode user settings.json (path varies by OS); "
        "merge under cline.mcpServers"
    )

    def render_entry(self, role: ServerRole) -> dict:
        return {"type": "http", "url": role.url}

    def render_full_snippet(self, entries: list[ServerRoleEntry]) -> str:
        body = {"mcpServers": {e.role.role_id: self.render_entry(e.role) for e in entries}}
        return json.dumps(body, indent=2, ensure_ascii=False)

    def notes(self) -> str:
        return ("Cline reads MCP config from VSCode user settings. "
                "Open Command Palette → 'Preferences: Open User Settings (JSON)' "
                "and add `cline.mcpServers` with the snippet above.")
```

- [ ] **Step 4: Write `cli/src/fleet/frameworks/openclaw.py`**

```python
import json
from .base import BaseFrameworkConfig, ServerRoleEntry
from ..types import ServerRole


class OpenClawConfig(BaseFrameworkConfig):
    framework_id = "openclaw"
    display_name = "OpenClaw"
    config_format = "json"
    config_path_template = "~/.openclaw/ (managed via `openclaw mcp` CLI; see openclaw docs)"

    def render_entry(self, role: ServerRole) -> dict:
        return {"transport": "streamable-http", "url": role.url}

    def render_full_snippet(self, entries: list[ServerRoleEntry]) -> str:
        servers = {e.role.role_id: self.render_entry(e.role) for e in entries}
        body = {"mcp": {"servers": servers}}
        return json.dumps(body, indent=2, ensure_ascii=False)

    def cli_alternative(self) -> str | None:
        return ("For each entry, run:\n"
                "  openclaw mcp set <NAME> '{\"transport\":\"streamable-http\",\"url\":\"<URL>\"}'")

    def notes(self) -> str:
        return ("OpenClaw uses `transport: streamable-http` (not `type: http` like Claude Code). "
                "The `openclaw mcp set` CLI is the recommended way to apply each entry.")
```

- [ ] **Step 5: Write `cli/src/fleet/frameworks/antigravity.py`**

```python
import json
from .base import BaseFrameworkConfig, ServerRoleEntry
from ..types import ServerRole


class AntigravityConfig(BaseFrameworkConfig):
    framework_id = "antigravity"
    display_name = "Google Antigravity"
    config_format = "json"
    config_path_template = "~/.gemini/antigravity/mcp_config.json"

    def render_entry(self, role: ServerRole) -> dict:
        # Antigravity (Gemini CLI lineage) uses httpUrl field for streamable-http,
        # no explicit `type` / `transport`.
        return {"httpUrl": role.url}

    def render_full_snippet(self, entries: list[ServerRoleEntry]) -> str:
        body = {"mcpServers": {e.role.role_id: self.render_entry(e.role) for e in entries}}
        return json.dumps(body, indent=2, ensure_ascii=False)

    def notes(self) -> str:
        return ("Antigravity → MCP Store → 'Manage MCP Servers' → 'View raw config' "
                "opens the mcp_config.json file. Merge the snippet above.")
```

- [ ] **Step 6: Write `cli/src/fleet/frameworks/hermes.py`**

```python
import yaml
from .base import BaseFrameworkConfig, ServerRoleEntry
from ..types import ServerRole


class HermesConfig(BaseFrameworkConfig):
    framework_id = "hermes"
    display_name = "Hermes Agent (Nous Research)"
    config_format = "yaml"
    config_path_template = "~/.hermes/config.yaml"

    def render_entry(self, role: ServerRole) -> dict:
        # Hermes auto-detects transport based on presence of `url` vs `command`.
        return {"url": role.url}

    def render_full_snippet(self, entries: list[ServerRoleEntry]) -> str:
        body = {"mcp_servers": {e.role.role_id: self.render_entry(e.role) for e in entries}}
        return yaml.safe_dump(body, sort_keys=False, allow_unicode=True)

    def notes(self) -> str:
        return ("Hermes uses YAML. After editing config.yaml, run `/reload-mcp` in the Hermes "
                "chat or restart the daemon. Use `hermes mcp test <name>` to verify connectivity.")
```

- [ ] **Step 7: Run, pass**

```bash
pytest cli/tests/test_frameworks_other.py -v
```
Expected: 6 passed.

- [ ] **Step 8: Commit**

```bash
git add cli/src/fleet/frameworks/cline.py cli/src/fleet/frameworks/openclaw.py cli/src/fleet/frameworks/antigravity.py cli/src/fleet/frameworks/hermes.py cli/tests/test_frameworks_other.py
git commit -m "feat(cli): Cline, OpenClaw, Antigravity, Hermes framework configs"
```

---

### Task 7: Framework registry

**Files:**
- Modify: `cli/src/fleet/frameworks/__init__.py`
- Create: `cli/tests/test_frameworks_registry.py`

- [ ] **Step 1: Write test**

```python
# cli/tests/test_frameworks_registry.py
from fleet.frameworks import FRAMEWORK_REGISTRY


def test_six_frameworks_registered():
    ids = {fw.framework_id for fw in FRAMEWORK_REGISTRY}
    assert ids == {"claude-code", "cursor", "cline", "openclaw", "antigravity", "hermes"}


def test_each_has_display_name_and_path():
    for fw in FRAMEWORK_REGISTRY:
        assert fw.display_name
        assert fw.config_path_template
```

- [ ] **Step 2: Modify `cli/src/fleet/frameworks/__init__.py`**

```python
"""Per-agent-framework MCP config generators."""
from .base import BaseFrameworkConfig, ServerRoleEntry
from .claude_code import ClaudeCodeConfig
from .cursor import CursorConfig
from .cline import ClineConfig
from .openclaw import OpenClawConfig
from .antigravity import AntigravityConfig
from .hermes import HermesConfig

# Instantiated registry — wizard iterates this for the multi-select prompt.
FRAMEWORK_REGISTRY: list[BaseFrameworkConfig] = [
    ClaudeCodeConfig(),
    CursorConfig(),
    ClineConfig(),
    OpenClawConfig(),
    AntigravityConfig(),
    HermesConfig(),
]

__all__ = [
    "BaseFrameworkConfig", "ServerRoleEntry", "FRAMEWORK_REGISTRY",
    "ClaudeCodeConfig", "CursorConfig", "ClineConfig",
    "OpenClawConfig", "AntigravityConfig", "HermesConfig",
]
```

- [ ] **Step 3: Run, pass**

```bash
pytest cli/tests/test_frameworks_registry.py -v
```
Expected: 2 passed.

- [ ] **Step 4: Commit**

```bash
git add cli/src/fleet/frameworks/__init__.py cli/tests/test_frameworks_registry.py
git commit -m "feat(cli): framework registry"
```

---

## Phase 3 — Installer abstraction & 3 OS implementations

### Task 8: BaseInstaller ABC

**Files:**
- Create: `cli/src/fleet/installers/__init__.py`
- Create: `cli/src/fleet/installers/base.py`
- Create: `cli/tests/test_installers_base.py`

- [ ] **Step 1: Write test**

```python
# cli/tests/test_installers_base.py
import pytest
from fleet.types import OSInfo
from fleet.installers.base import BaseInstaller


class DummyInstaller(BaseInstaller):
    role_id = "dummy"
    display_name = "Dummy"
    port = 9999

    def is_supported_on(self, os_info):
        return os_info.kind == "macos"

    def preflight(self):
        return []

    def install(self, ctx):
        yield "starting"

    def verify(self):
        from fleet.types import VerifyResult
        return VerifyResult(ok=True, tool_count=0)

    def guidance_steps(self):
        return []


def test_abstract_class_cannot_instantiate():
    with pytest.raises(TypeError):
        BaseInstaller()


def test_concrete_subclass_works():
    d = DummyInstaller()
    mac = OSInfo(system="Darwin", version="22", arch="x86_64", is_apple_silicon=False)
    win = OSInfo(system="Windows", version="11", arch="AMD64", is_apple_silicon=False)
    assert d.is_supported_on(mac)
    assert not d.is_supported_on(win)
```

- [ ] **Step 2: Run, fail**

```bash
pytest cli/tests/test_installers_base.py -v
```

- [ ] **Step 3: Write `cli/src/fleet/installers/__init__.py`** (initially just re-exports base)

```python
"""Per-(OS, role) installers. Each subclasses BaseInstaller."""
from .base import BaseInstaller

__all__ = ["BaseInstaller"]
```

- [ ] **Step 4: Write `cli/src/fleet/installers/base.py`**

```python
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterator

from ..types import InstallContext, InstallEvent, OSInfo, VerifyResult, GuidanceStep


class BaseInstaller(ABC):
    role_id: str = ""        # e.g. "macbox-gui" / "android-gui-win"
    display_name: str = ""
    port: int = 0

    @abstractmethod
    def is_supported_on(self, os_info: OSInfo) -> bool: ...

    @abstractmethod
    def preflight(self) -> list[str]:
        """Return human-readable list of missing prerequisites (empty = ready)."""

    @abstractmethod
    def install(self, ctx: InstallContext) -> Iterator[InstallEvent]:
        """Drive the per-platform setup script; yield events as install progresses."""

    @abstractmethod
    def verify(self) -> VerifyResult:
        """Probe the server and confirm it's serving MCP."""

    @abstractmethod
    def guidance_steps(self) -> list[GuidanceStep]:
        """Post-install operation guidance (permissions / authorization)."""
```

- [ ] **Step 5: Run, pass**

```bash
pytest cli/tests/test_installers_base.py -v
```
Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add cli/src/fleet/installers/
git commit -m "feat(cli): BaseInstaller ABC"
```

---

### Task 9: macOS installer (macbox-gui) — wraps setup-macos.sh

**Files:**
- Create: `cli/src/fleet/installers/macos.py`
- Create: `cli/tests/test_installers_macos.py`

- [ ] **Step 1: Write test**

```python
# cli/tests/test_installers_macos.py
from unittest.mock import patch, MagicMock
from fleet.installers.macos import MacosDesktop
from fleet.types import OSInfo, InstallContext


def test_macos_desktop_supported_only_on_macos():
    m = MacosDesktop()
    assert m.is_supported_on(OSInfo(system="Darwin", version="22", arch="x86_64", is_apple_silicon=False))
    assert not m.is_supported_on(OSInfo(system="Windows", version="11", arch="AMD64", is_apple_silicon=False))
    assert not m.is_supported_on(OSInfo(system="Linux", version="6.5", arch="x86_64", is_apple_silicon=False))


def test_macos_desktop_metadata():
    m = MacosDesktop()
    assert m.role_id == "macbox-gui"
    assert m.port == 8767


@patch("subprocess.Popen")
def test_install_invokes_setup_script(mock_popen):
    proc = MagicMock()
    proc.stdout.readline.side_effect = ["[1/8] Tailscale\n", "ok logged in\n", ""]
    proc.wait.return_value = 0
    proc.returncode = 0
    mock_popen.return_value = proc

    m = MacosDesktop()
    ctx = InstallContext(
        repo_root="/tmp/repo",
        os_info=OSInfo(system="Darwin", version="22", arch="x86_64", is_apple_silicon=False),
        dry_run=False,
    )
    events = list(m.install(ctx))
    assert any("Tailscale" in e.message for e in events)
    # Popen should have been called with bash and the setup-macos.sh path
    call_args = mock_popen.call_args[0][0]
    assert "bash" in call_args[0]
    assert "setup-macos.sh" in call_args[1]


def test_install_dry_run_skips_subprocess():
    m = MacosDesktop()
    ctx = InstallContext(
        repo_root="/tmp/repo",
        os_info=OSInfo(system="Darwin", version="22", arch="x86_64", is_apple_silicon=False),
        dry_run=True,
    )
    with patch("subprocess.Popen") as mock_popen:
        list(m.install(ctx))
        assert not mock_popen.called
```

- [ ] **Step 2: Run, fail**

```bash
pytest cli/tests/test_installers_macos.py -v
```

- [ ] **Step 3: Write `cli/src/fleet/installers/macos.py`**

```python
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Iterator

from .base import BaseInstaller
from ..types import (
    GuidanceStep, GuidanceVariant, InstallContext, InstallEvent, OSInfo, ServerRole, VerifyResult,
)


class MacosDesktop(BaseInstaller):
    role_id = "macbox-gui"
    display_name = "macOS desktop (macbox-gui)"
    port = 8767

    def is_supported_on(self, os_info: OSInfo) -> bool:
        return os_info.kind == "macos"

    def preflight(self) -> list[str]:
        missing = []
        if not _which("brew"):
            missing.append("Homebrew (brew). Install: /bin/bash -c \"$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\"")
        return missing

    def install(self, ctx: InstallContext) -> Iterator[InstallEvent]:
        setup = Path(ctx.repo_root) / "platforms" / "macos" / "scripts" / "setup-macos.sh"
        if ctx.dry_run:
            yield InstallEvent(self.role_id, "deps", f"[DRY RUN] would run {setup}")
            return
        if not setup.exists():
            yield InstallEvent(self.role_id, "preflight", f"setup script missing at {setup}", level="error")
            return

        proc = subprocess.Popen(
            ["bash", str(setup)],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1,
        )
        for line in iter(proc.stdout.readline, ""):
            line = line.rstrip()
            if not line:
                continue
            yield InstallEvent(self.role_id, "install", line)
        proc.wait()
        if proc.returncode != 0:
            yield InstallEvent(self.role_id, "install", f"setup-macos.sh exited rc={proc.returncode}", level="error")

    def verify(self) -> VerifyResult:
        # Lazy import to keep test fast
        from ..verify import probe_mcp_server
        return probe_mcp_server("127.0.0.1", self.port)

    def guidance_steps(self) -> list[GuidanceStep]:
        # Filled in Task 16 via YAML loader.
        from ..guidance import load_guidance_yaml
        return [
            load_guidance_yaml("macos_accessibility.yaml"),
            load_guidance_yaml("macos_screen_recording.yaml"),
            load_guidance_yaml("macos_automation.yaml"),
            load_guidance_yaml("macos_full_disk_access.yaml"),
        ]


def _which(name: str) -> str | None:
    import shutil
    return shutil.which(name)
```

- [ ] **Step 4: Run, pass**

Run:
```bash
pytest cli/tests/test_installers_macos.py::test_macos_desktop_supported_only_on_macos cli/tests/test_installers_macos.py::test_macos_desktop_metadata cli/tests/test_installers_macos.py::test_install_dry_run_skips_subprocess -v
```
(skip `test_install_invokes_setup_script` for now — depends on real setup file existing in cwd; full integration test in Phase 7).

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add cli/src/fleet/installers/macos.py cli/tests/test_installers_macos.py
git commit -m "feat(cli): MacosDesktop installer (wraps setup-macos.sh)"
```

---

### Task 10: macOS android-bridge installer

**Files:**
- Create: `cli/src/fleet/installers/macos.py` (modify: add MacosAndroidBridge class)
- Modify: `cli/tests/test_installers_macos.py` (add tests)

- [ ] **Step 1: Add test**

```python
# Append to cli/tests/test_installers_macos.py
from fleet.installers.macos import MacosAndroidBridge


def test_macos_android_metadata():
    m = MacosAndroidBridge()
    assert m.role_id == "android-gui"
    assert m.port == 8768


def test_macos_android_supported_only_on_macos():
    m = MacosAndroidBridge()
    assert m.is_supported_on(OSInfo(system="Darwin", version="22", arch="x86_64", is_apple_silicon=False))
    assert not m.is_supported_on(OSInfo(system="Linux", version="6.5", arch="x86_64", is_apple_silicon=False))
```

- [ ] **Step 2: Run, fail (ImportError)**

```bash
pytest cli/tests/test_installers_macos.py -v -k android
```

- [ ] **Step 3: Append to `cli/src/fleet/installers/macos.py`**

```python
class MacosAndroidBridge(BaseInstaller):
    role_id = "android-gui"
    display_name = "Android bridge on macOS"
    port = 8768

    def is_supported_on(self, os_info: OSInfo) -> bool:
        return os_info.kind == "macos"

    def preflight(self) -> list[str]:
        m = []
        if not _which("brew"):
            m.append("Homebrew (brew)")
        return m

    def install(self, ctx: InstallContext) -> Iterator[InstallEvent]:
        setup = Path(ctx.repo_root) / "platforms" / "android" / "scripts" / "setup-android.sh"
        if ctx.dry_run:
            yield InstallEvent(self.role_id, "deps", f"[DRY RUN] would run {setup}")
            return
        if not setup.exists():
            yield InstallEvent(self.role_id, "preflight", f"setup script missing at {setup}", level="error")
            return
        proc = subprocess.Popen(["bash", str(setup)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        for line in iter(proc.stdout.readline, ""):
            line = line.rstrip()
            if not line:
                continue
            yield InstallEvent(self.role_id, "install", line)
        proc.wait()
        if proc.returncode != 0:
            yield InstallEvent(self.role_id, "install", f"setup-android.sh exited rc={proc.returncode}", level="error")

    def verify(self) -> VerifyResult:
        from ..verify import probe_mcp_server
        return probe_mcp_server("127.0.0.1", self.port)

    def guidance_steps(self) -> list[GuidanceStep]:
        from ..guidance import load_guidance_yaml
        return [
            load_guidance_yaml("android_dev_options.yaml"),
            load_guidance_yaml("android_usb_debug.yaml"),
            load_guidance_yaml("android_wireless_pair.yaml"),
        ]
```

- [ ] **Step 4: Run, pass**

```bash
pytest cli/tests/test_installers_macos.py -v -k android
```
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add cli/src/fleet/installers/macos.py cli/tests/test_installers_macos.py
git commit -m "feat(cli): MacosAndroidBridge installer"
```

---

### Task 11: Windows installer (winpc-gui + android bridge)

**Files:**
- Create: `cli/src/fleet/installers/windows.py`
- Create: `cli/tests/test_installers_windows.py`

- [ ] **Step 1: Write test**

```python
# cli/tests/test_installers_windows.py
from fleet.installers.windows import WindowsTestPC, WindowsAndroidBridge
from fleet.types import OSInfo, InstallContext


def test_windows_metadata():
    assert WindowsTestPC().role_id == "winpc-gui"
    assert WindowsTestPC().port == 8766
    assert WindowsAndroidBridge().role_id == "android-gui"
    assert WindowsAndroidBridge().port == 8768


def test_windows_supported_only_on_windows():
    osw = OSInfo(system="Windows", version="11", arch="AMD64", is_apple_silicon=False)
    osm = OSInfo(system="Darwin", version="22", arch="x86_64", is_apple_silicon=False)
    assert WindowsTestPC().is_supported_on(osw)
    assert not WindowsTestPC().is_supported_on(osm)
    assert WindowsAndroidBridge().is_supported_on(osw)


def test_dry_run_skips_subprocess():
    osw = OSInfo(system="Windows", version="11", arch="AMD64", is_apple_silicon=False)
    ctx = InstallContext(repo_root="C:\\repo", os_info=osw, dry_run=True)
    events = list(WindowsTestPC().install(ctx))
    assert any("DRY RUN" in e.message for e in events)
```

- [ ] **Step 2: Run, fail**

```bash
pytest cli/tests/test_installers_windows.py -v
```

- [ ] **Step 3: Write `cli/src/fleet/installers/windows.py`**

```python
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Iterator

from .base import BaseInstaller
from ..types import GuidanceStep, InstallContext, InstallEvent, OSInfo, VerifyResult


def _run_setup_ps1(ctx: InstallContext, script_path: Path, role_id: str) -> Iterator[InstallEvent]:
    if ctx.dry_run:
        yield InstallEvent(role_id, "deps", f"[DRY RUN] would run {script_path}")
        return
    if not script_path.exists():
        yield InstallEvent(role_id, "preflight", f"setup script missing at {script_path}", level="error")
        return
    proc = subprocess.Popen(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script_path)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
    )
    for line in iter(proc.stdout.readline, ""):
        line = line.rstrip()
        if not line:
            continue
        yield InstallEvent(role_id, "install", line)
    proc.wait()
    if proc.returncode != 0:
        yield InstallEvent(role_id, "install", f"setup script exited rc={proc.returncode}", level="error")


class WindowsTestPC(BaseInstaller):
    role_id = "winpc-gui"
    display_name = "Windows testable desktop (winpc-gui)"
    port = 8766

    def is_supported_on(self, os_info: OSInfo) -> bool:
        return os_info.kind == "windows"

    def preflight(self) -> list[str]:
        return []  # winget bundled on Win 10/11; powershell.exe always present

    def install(self, ctx: InstallContext) -> Iterator[InstallEvent]:
        yield from _run_setup_ps1(
            ctx,
            Path(ctx.repo_root) / "platforms" / "windows" / "scripts" / "setup-windows.ps1",
            self.role_id,
        )

    def verify(self) -> VerifyResult:
        from ..verify import probe_mcp_server
        return probe_mcp_server("127.0.0.1", self.port)

    def guidance_steps(self) -> list[GuidanceStep]:
        from ..guidance import load_guidance_yaml
        return [load_guidance_yaml("windows_postinstall.yaml")]


class WindowsAndroidBridge(BaseInstaller):
    role_id = "android-gui"
    display_name = "Android bridge on Windows"
    port = 8768

    def is_supported_on(self, os_info: OSInfo) -> bool:
        return os_info.kind == "windows"

    def preflight(self) -> list[str]:
        return []

    def install(self, ctx: InstallContext) -> Iterator[InstallEvent]:
        yield from _run_setup_ps1(
            ctx,
            Path(ctx.repo_root) / "platforms" / "android" / "scripts" / "setup-android.ps1",
            self.role_id,
        )

    def verify(self) -> VerifyResult:
        from ..verify import probe_mcp_server
        return probe_mcp_server("127.0.0.1", self.port)

    def guidance_steps(self) -> list[GuidanceStep]:
        from ..guidance import load_guidance_yaml
        return [
            load_guidance_yaml("android_dev_options.yaml"),
            load_guidance_yaml("android_usb_debug.yaml"),
            load_guidance_yaml("android_wireless_pair.yaml"),
        ]
```

- [ ] **Step 4: Run, pass**

```bash
pytest cli/tests/test_installers_windows.py -v
```
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add cli/src/fleet/installers/windows.py cli/tests/test_installers_windows.py
git commit -m "feat(cli): WindowsTestPC + WindowsAndroidBridge installers"
```

---

### Task 12: Linux installer + setup-android-linux.sh

**Files:**
- Create: `platforms/android/scripts/setup-android-linux.sh`
- Create: `cli/src/fleet/installers/linux.py`
- Create: `cli/tests/test_installers_linux.py`

- [ ] **Step 1: Write `platforms/android/scripts/setup-android-linux.sh`**

```bash
#!/usr/bin/env bash
# agent-fleet / Android (Linux host) platform setup
#
# Run from inside the cloned repo:
#   cd <repo-root>
#   bash platforms/android/scripts/setup-android-linux.sh
#
# Steps:
#   1. verify Tailscale logged in
#   2. apt install android-platform-tools (adb)
#   3. install Python 3.10+ (apt python3-venv if missing)
#   4. venv + pip install requirements
#   5. ask ADB mode -> ~/.atb-android/config.toml
#   6. verify `adb devices`
#   7. install systemd user unit
#   8. start + verify port 8768

set -euo pipefail

trap 'rc=$?; echo; echo "ERROR: setup-android-linux.sh failed at line $LINENO (exit=$rc)" >&2; echo "       Last step: $LAST_STEP" >&2; exit $rc' ERR
LAST_STEP="(before any step)"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLATFORM_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SERVER_DIR="$PLATFORM_DIR/server"
LOGS_DIR="$PLATFORM_DIR/logs"
VENV_DIR="$SERVER_DIR/.venv"
VENV_PY="$VENV_DIR/bin/python3"
SERVER_PY="$SERVER_DIR/android_mcp.py"
REQ_TXT="$SERVER_DIR/requirements.txt"
UNIT_PATH="$HOME/.config/systemd/user/atb-android-gui.service"
PORT=8768
CONFIG_DIR="$HOME/.atb-android"
CONFIG_PATH="$CONFIG_DIR/config.toml"

mkdir -p "$LOGS_DIR" "$(dirname "$UNIT_PATH")"

echo "=== agent-fleet / Android Bridge Setup (Linux host) ==="
echo

LAST_STEP="[1/8] Tailscale"
echo "$LAST_STEP"
if ! command -v tailscale >/dev/null 2>&1; then
    echo "  tailscale not found. Install: curl -fsSL https://tailscale.com/install.sh | sh"
    exit 1
fi
if ! tailscale status >/dev/null 2>&1; then
    echo "  tailscale not logged in. Run: sudo tailscale up"
    exit 1
fi
TS_HOST="$(tailscale status --json 2>/dev/null | python3 -c 'import json,sys;print(json.load(sys.stdin)["Self"]["HostName"])')"
echo "  ok logged in (hostname: $TS_HOST)"
echo

LAST_STEP="[2/8] adb (android platform-tools)"
echo "$LAST_STEP"
if ! command -v adb >/dev/null 2>&1; then
    echo "  installing android-tools-adb via apt"
    sudo apt update
    sudo apt install -y android-tools-adb
fi
echo "  ok adb at $(command -v adb): $(adb version | head -1)"
echo

LAST_STEP="[3/8] Python 3.10+"
echo "$LAST_STEP"
PYTHON_BIN=""
for cand in python3.12 python3.11 python3.10 python3; do
    if command -v "$cand" >/dev/null 2>&1; then
        ver="$($cand -c 'import sys;print(f"{sys.version_info[0]}.{sys.version_info[1]}")' 2>/dev/null || echo "0.0")"
        major="${ver%%.*}"; minor="${ver#*.}"
        if [ "$major" = "3" ] && [ "$minor" -ge 10 ]; then
            PYTHON_BIN="$(command -v "$cand")"
            break
        fi
    fi
done
if [ -z "$PYTHON_BIN" ]; then
    echo "  installing python3 + python3-venv via apt"
    sudo apt install -y python3 python3-venv
    PYTHON_BIN="$(command -v python3)"
fi
echo "  ok using $PYTHON_BIN"
echo

LAST_STEP="[4/8] venv + deps"
echo "$LAST_STEP"
[ -d "$VENV_DIR" ] || "$PYTHON_BIN" -m venv "$VENV_DIR"
"$VENV_PY" -m pip install --upgrade pip --quiet
"$VENV_PY" -m pip install -r "$REQ_TXT"
echo "  ok"
echo

LAST_STEP="[5/8] ADB connection mode"
echo "$LAST_STEP"
mkdir -p "$CONFIG_DIR"
if [ -f "$CONFIG_PATH" ]; then
    echo "  existing $CONFIG_PATH found; reusing"
else
    echo "  Choose ADB mode:"
    echo "    1) USB"
    echo "    2) Wireless Debugging (Android 11+)"
    echo "    3) Hybrid"
    while true; do
        read -r -p "  mode [1/2/3]: " mode
        case "$mode" in
            1) MODE=usb; break ;;
            2) MODE=wireless; break ;;
            3) MODE=hybrid; break ;;
        esac
    done
    cat > "$CONFIG_PATH" <<EOF
mode = "$MODE"

[host]
os = "linux"
adb_path = "$(command -v adb)"
EOF
    echo "  ok wrote $CONFIG_PATH"
fi
echo

LAST_STEP="[6/8] adb devices"
echo "$LAST_STEP"
adb devices -l
echo

LAST_STEP="[7/8] systemd user unit"
echo "$LAST_STEP"
cat > "$UNIT_PATH" <<EOF
[Unit]
Description=agent-fleet android-gui MCP server
After=network.target

[Service]
Type=simple
ExecStart=$VENV_PY $SERVER_PY
Restart=on-failure
RestartSec=3
Environment=PYTHONUNBUFFERED=1
Environment=ATB_ANDROID_ADB=$(command -v adb)
StandardOutput=append:$LOGS_DIR/android-gui.log
StandardError=append:$LOGS_DIR/android-gui.log

[Install]
WantedBy=default.target
EOF
systemctl --user daemon-reload
systemctl --user enable --now atb-android-gui.service
echo "  ok unit at $UNIT_PATH"
echo

LAST_STEP="[8/8] verify"
echo "$LAST_STEP"
sleep 4
if ss -tlnp 2>/dev/null | grep -q ":$PORT"; then
    echo "  ok android-gui listening on :$PORT"
else
    echo "  WARN not yet on :$PORT; check $LOGS_DIR/android-gui.log"
fi

echo
echo "=== Done ==="
echo "On agent host: python3 scripts/install-agent-side.py --platform android-gui --hostname $TS_HOST"
```

- [ ] **Step 2: Make executable + bash syntax check**

```bash
chmod +x platforms/android/scripts/setup-android-linux.sh
bash -n platforms/android/scripts/setup-android-linux.sh && echo OK
```
Expected: `OK`.

- [ ] **Step 3: Write test `cli/tests/test_installers_linux.py`**

```python
from fleet.installers.linux import LinuxAndroidBridge
from fleet.types import OSInfo, InstallContext


def test_linux_android_metadata():
    m = LinuxAndroidBridge()
    assert m.role_id == "android-gui"
    assert m.port == 8768


def test_linux_supported_only_on_linux():
    m = LinuxAndroidBridge()
    osl = OSInfo(system="Linux", version="6.5", arch="x86_64", is_apple_silicon=False)
    osm = OSInfo(system="Darwin", version="22", arch="x86_64", is_apple_silicon=False)
    assert m.is_supported_on(osl)
    assert not m.is_supported_on(osm)


def test_dry_run_skips_subprocess():
    osl = OSInfo(system="Linux", version="6.5", arch="x86_64", is_apple_silicon=False)
    ctx = InstallContext(repo_root="/tmp/repo", os_info=osl, dry_run=True)
    events = list(LinuxAndroidBridge().install(ctx))
    assert any("DRY RUN" in e.message for e in events)
```

- [ ] **Step 4: Write `cli/src/fleet/installers/linux.py`**

```python
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Iterator

from .base import BaseInstaller
from ..types import GuidanceStep, InstallContext, InstallEvent, OSInfo, VerifyResult


class LinuxAndroidBridge(BaseInstaller):
    role_id = "android-gui"
    display_name = "Android bridge on Linux"
    port = 8768

    def is_supported_on(self, os_info: OSInfo) -> bool:
        return os_info.kind == "linux"

    def preflight(self) -> list[str]:
        return []

    def install(self, ctx: InstallContext) -> Iterator[InstallEvent]:
        setup = Path(ctx.repo_root) / "platforms" / "android" / "scripts" / "setup-android-linux.sh"
        if ctx.dry_run:
            yield InstallEvent(self.role_id, "deps", f"[DRY RUN] would run {setup}")
            return
        if not setup.exists():
            yield InstallEvent(self.role_id, "preflight", f"setup script missing at {setup}", level="error")
            return
        proc = subprocess.Popen(["bash", str(setup)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        for line in iter(proc.stdout.readline, ""):
            line = line.rstrip()
            if not line:
                continue
            yield InstallEvent(self.role_id, "install", line)
        proc.wait()
        if proc.returncode != 0:
            yield InstallEvent(self.role_id, "install", f"setup-android-linux.sh exited rc={proc.returncode}", level="error")

    def verify(self) -> VerifyResult:
        from ..verify import probe_mcp_server
        return probe_mcp_server("127.0.0.1", self.port)

    def guidance_steps(self) -> list[GuidanceStep]:
        from ..guidance import load_guidance_yaml
        return [
            load_guidance_yaml("android_dev_options.yaml"),
            load_guidance_yaml("android_usb_debug.yaml"),
        ]
```

- [ ] **Step 5: Run, pass**

```bash
pytest cli/tests/test_installers_linux.py -v
```
Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add platforms/android/scripts/setup-android-linux.sh cli/src/fleet/installers/linux.py cli/tests/test_installers_linux.py
git commit -m "feat(cli): Linux android bridge installer + setup-android-linux.sh (apt + systemd)"
```

---

### Task 13: Installer registry

**Files:**
- Modify: `cli/src/fleet/installers/__init__.py`
- Create: `cli/tests/test_installers_registry.py`

- [ ] **Step 1: Write test**

```python
# cli/tests/test_installers_registry.py
from fleet.installers import INSTALLER_REGISTRY, filter_for_os
from fleet.types import OSInfo


def test_registry_has_all_installers():
    role_ids = {(i.__class__.__name__, i.role_id) for i in INSTALLER_REGISTRY}
    expected = {
        ("MacosDesktop", "macbox-gui"),
        ("MacosAndroidBridge", "android-gui"),
        ("WindowsTestPC", "winpc-gui"),
        ("WindowsAndroidBridge", "android-gui"),
        ("LinuxAndroidBridge", "android-gui"),
    }
    assert expected.issubset(role_ids)


def test_filter_for_macos():
    macs = filter_for_os(OSInfo(system="Darwin", version="22", arch="x86_64", is_apple_silicon=False))
    role_ids = {i.role_id for i in macs}
    assert "macbox-gui" in role_ids
    assert "android-gui" in role_ids
    assert "winpc-gui" not in role_ids


def test_filter_for_windows():
    wins = filter_for_os(OSInfo(system="Windows", version="11", arch="AMD64", is_apple_silicon=False))
    role_ids = {i.role_id for i in wins}
    assert "winpc-gui" in role_ids
    assert "android-gui" in role_ids
    assert "macbox-gui" not in role_ids


def test_filter_for_linux():
    lins = filter_for_os(OSInfo(system="Linux", version="6.5", arch="x86_64", is_apple_silicon=False))
    role_ids = {i.role_id for i in lins}
    assert role_ids == {"android-gui"}
```

- [ ] **Step 2: Modify `cli/src/fleet/installers/__init__.py`**

```python
"""Per-(OS, role) installers."""
from .base import BaseInstaller
from .macos import MacosDesktop, MacosAndroidBridge
from .windows import WindowsTestPC, WindowsAndroidBridge
from .linux import LinuxAndroidBridge
from ..types import OSInfo


INSTALLER_REGISTRY: list[BaseInstaller] = [
    MacosDesktop(),
    MacosAndroidBridge(),
    WindowsTestPC(),
    WindowsAndroidBridge(),
    LinuxAndroidBridge(),
]


def filter_for_os(os_info: OSInfo) -> list[BaseInstaller]:
    return [i for i in INSTALLER_REGISTRY if i.is_supported_on(os_info)]


__all__ = [
    "BaseInstaller", "INSTALLER_REGISTRY", "filter_for_os",
    "MacosDesktop", "MacosAndroidBridge",
    "WindowsTestPC", "WindowsAndroidBridge",
    "LinuxAndroidBridge",
]
```

- [ ] **Step 3: Run, pass**

```bash
pytest cli/tests/test_installers_registry.py -v
```
Expected: 4 passed.

- [ ] **Step 4: Commit**

```bash
git add cli/src/fleet/installers/__init__.py cli/tests/test_installers_registry.py
git commit -m "feat(cli): installer registry + per-OS filter"
```

---

## Phase 4 — Guidance subsystem (YAML variant tables)

### Task 14: GuidanceStep YAML loader

**Files:**
- Create: `cli/src/fleet/guidance/__init__.py`
- Create: `cli/tests/test_guidance_loader.py`

- [ ] **Step 1: Write test**

```python
# cli/tests/test_guidance_loader.py
from fleet.guidance import load_guidance_yaml
import pytest


def test_load_android_dev_options(tmp_path, monkeypatch):
    yaml_text = '''
step:
  title: "开启开发者选项"
  default_description: '设置 → 关于手机 → 连按"版本号" 7 次'
  variant_label: "Android 品牌"
  variants:
    huawei:
      label: "华为 / HarmonyOS / EMUI"
      description: '设置 → 关于手机 → 连按"版本号"'
    pixel:
      label: "Pixel / 原生 AOSP"
      description: 'Settings → About phone → tap "Build number" 7×'
'''
    f = tmp_path / "android_dev_options.yaml"
    f.write_text(yaml_text)
    monkeypatch.setenv("ATB_GUIDANCE_DIR", str(tmp_path))

    s = load_guidance_yaml("android_dev_options.yaml")
    assert s.title == "开启开发者选项"
    assert "版本号" in s.default_description
    assert s.variant_label == "Android 品牌"
    assert "huawei" in s.variants
    assert s.variants["huawei"].label == "华为 / HarmonyOS / EMUI"


def test_load_missing_file_raises(monkeypatch, tmp_path):
    monkeypatch.setenv("ATB_GUIDANCE_DIR", str(tmp_path))
    with pytest.raises(FileNotFoundError):
        load_guidance_yaml("does_not_exist.yaml")
```

- [ ] **Step 2: Run, fail**

```bash
pytest cli/tests/test_guidance_loader.py -v
```

- [ ] **Step 3: Write `cli/src/fleet/guidance/__init__.py`**

```python
"""Guidance YAML loading. YAML files live next to this module."""
from __future__ import annotations

import os
from pathlib import Path

import yaml

from ..types import GuidanceStep, GuidanceVariant


def _guidance_dir() -> Path:
    env = os.environ.get("ATB_GUIDANCE_DIR")
    if env:
        return Path(env)
    return Path(__file__).parent


def load_guidance_yaml(filename: str) -> GuidanceStep:
    path = _guidance_dir() / filename
    if not path.exists():
        raise FileNotFoundError(f"guidance YAML not found: {path}")
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    step = data["step"]
    variants = {}
    for vid, vdata in (step.get("variants") or {}).items():
        variants[vid] = GuidanceVariant(label=vdata["label"], description=vdata["description"])
    return GuidanceStep(
        title=step["title"],
        default_description=step["default_description"],
        variant_label=step.get("variant_label", ""),
        variants=variants,
    )


__all__ = ["load_guidance_yaml"]
```

- [ ] **Step 4: Run, pass**

```bash
pytest cli/tests/test_guidance_loader.py -v
```
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add cli/src/fleet/guidance/__init__.py cli/tests/test_guidance_loader.py
git commit -m "feat(cli): guidance YAML loader"
```

---

### Task 15: macOS guidance YAMLs

**Files:**
- Create: `cli/src/fleet/guidance/macos_accessibility.yaml`
- Create: `cli/src/fleet/guidance/macos_screen_recording.yaml`
- Create: `cli/src/fleet/guidance/macos_automation.yaml`
- Create: `cli/src/fleet/guidance/macos_full_disk_access.yaml`

- [ ] **Step 1: Write `macos_accessibility.yaml`**

```yaml
# cli/src/fleet/guidance/macos_accessibility.yaml
step:
  title: "辅助功能 (Accessibility) 权限"
  default_description: |
    打开 System Settings → 隐私与安全性 → 辅助功能。
    点 + 拖入 Python.framework 的 Python.app：
      Intel: /usr/local/opt/python@3.12/Frameworks/Python.framework/Versions/3.12/Resources/Python.app
      ARM:   /opt/homebrew/opt/python@3.12/Frameworks/Python.framework/Versions/3.12/Resources/Python.app
    打开开关。
    ⚠️ 不要拖 venv 的 bin/python3（macOS 拒绝符号链接）。
  variant_label: "macOS 版本"
  variants:
    ventura_plus:
      label: "macOS 13 Ventura+ (System Settings)"
      description: |
        System Settings → Privacy & Security → Accessibility → +
    monterey_minus:
      label: "macOS 12 Monterey-"
      description: |
        System Preferences → Security & Privacy → Privacy → Accessibility
        （界面布局不同，但功能一致）
```

- [ ] **Step 2: Write `macos_screen_recording.yaml`**

```yaml
step:
  title: "屏幕录制 (Screen Recording) 权限"
  default_description: |
    同样的面板，左栏选 屏幕录制；拖入同一个 Python.app。
    没有这个权限时 take_screenshot 返回黑图。
  variant_label: "macOS 版本"
  variants:
    ventura_plus:
      label: "macOS 13 Ventura+"
      description: "System Settings → Privacy & Security → Screen Recording → +"
    monterey_minus:
      label: "macOS 12 Monterey-"
      description: "System Preferences → Security & Privacy → Privacy → Screen Recording"
```

- [ ] **Step 3: Write `macos_automation.yaml`**

```yaml
step:
  title: "自动化 (Automation) 权限"
  default_description: |
    无需现在操作。下次 agent 调 run_applescript 控制其他 app（System Events / Finder / Safari）时，
    macOS 会自动弹窗"允许 Python 控制 XXX"——点同意即永久生效。
    可选：预先在 隐私与安全性 → 自动化 里展开 python3，勾选 System Events 等。
```

- [ ] **Step 4: Write `macos_full_disk_access.yaml`**

```yaml
step:
  title: "完全磁盘访问 (Full Disk Access) 可选"
  default_description: |
    如果 agent 需要读 ~/Documents / ~/Library/Logs 等，给 Python.app 一份 Full Disk Access：
    System Settings → Privacy & Security → Full Disk Access → +
    拖入同一个 Python.app。
    永远不要授权：照片 / 日历 / 提醒事项 / 通讯录——agent 不需要也不该有这些数据。
```

- [ ] **Step 5: Sanity-check via the loader**

```bash
cd cli && python -c "
from fleet.guidance import load_guidance_yaml
for n in ['macos_accessibility.yaml','macos_screen_recording.yaml','macos_automation.yaml','macos_full_disk_access.yaml']:
    s = load_guidance_yaml(n)
    print(n, '->', s.title)
"
```
Expected: 4 lines printing the titles without exceptions.

- [ ] **Step 6: Commit**

```bash
git add cli/src/fleet/guidance/macos_*.yaml
git commit -m "feat(cli): macOS guidance YAMLs (Accessibility / Screen Recording / Automation / FDA)"
```

---

### Task 16: Android guidance YAMLs (with 6 OEM variants)

**Files:**
- Create: `cli/src/fleet/guidance/android_dev_options.yaml`
- Create: `cli/src/fleet/guidance/android_usb_debug.yaml`
- Create: `cli/src/fleet/guidance/android_wireless_pair.yaml`

- [ ] **Step 1: Write `android_dev_options.yaml`**

```yaml
step:
  title: "开启开发者选项"
  default_description: |
    通用：找到带"版本号"或"Build number"的字段连按 7 次。
    成功后会弹"已开启开发者选项"提示。
  variant_label: "Android 品牌 (各家路径不同)"
  variants:
    huawei:
      label: "华为 / HarmonyOS / EMUI"
      description: '设置 → 关于手机 → 连按"版本号" 7 次'
    xiaomi:
      label: "小米 / MIUI / HyperOS"
      description: '设置 → 我的设备 → 全部参数 → 连按"MIUI 版本" 7 次'
    samsung:
      label: "Samsung / One UI"
      description: 'Settings → About phone → Software information → tap "Build number" 7×'
    oppo:
      label: "OPPO / realme / ColorOS"
      description: '设置 → 关于本机 → 连按"版本号"'
    vivo:
      label: "vivo / OriginOS / Funtouch"
      description: '设置 → 我的设备 → 连按"软件版本"'
    pixel:
      label: "Pixel / 原生 AOSP"
      description: 'Settings → About phone → tap "Build number" 7×'
    fallback:
      label: "找不到 / 其他"
      description: '通用规律：找到带"版本号" 或 "Build number" 字段连按 7 次。'
```

- [ ] **Step 2: Write `android_usb_debug.yaml`**

```yaml
step:
  title: "USB 调试授权"
  default_description: |
    1. 开发者选项 → USB 调试 ON
    2. USB 数据线插电脑
    3. 手机弹窗"是否允许 USB 调试" → 勾"始终允许此电脑" → 确定
    4. PC 端 `adb devices` 看到设备 = OK
  variant_label: "Android 品牌"
  variants:
    huawei:
      label: "华为 / HarmonyOS"
      description: |
        华为可能需要先装"华为 HiSuite"才能识别 USB 调试。
        Windows 上有时 USB 驱动需要手动安装。
    xiaomi:
      label: "小米 / MIUI"
      description: |
        MIUI 要求登录小米账号才能开 USB 调试。
        开发者选项里要先开"USB 调试 (安全设置)"。
    pixel:
      label: "Pixel / 原生 AOSP"
      description: "默认行为，照通用流程走即可。"
```

- [ ] **Step 3: Write `android_wireless_pair.yaml`**

```yaml
step:
  title: "Wireless Debugging 配对（可选，Android 11+ / SDK 30+）"
  default_description: |
    1. 开发者选项 → 无线调试 ON
    2. "使用配对码配对设备"
    3. 手机显示 6 位配对码 + IP:配对端口
    4. PC 端：
       adb pair <PHONE_IP>:<PAIRING_PORT>
       (提示输入配对码 → 输入)
    5. adb connect <PHONE_IP>:<ADB_PORT>
       (ADB_PORT 在无线调试主界面，与配对端口不同)
    一次配对永久有效。
  variant_label: "Android 版本"
  variants:
    api30plus:
      label: "Android 11+ / SDK 30+"
      description: "原生支持无线调试，照默认步骤走。"
    harmonyos4_p30pro_legacy:
      label: "HarmonyOS 4.0（如 P30 Pro，实测 build version=10/SDK29）"
      description: |
        部分 HarmonyOS 4 机型 ro.build.version.release=10，无原生无线调试。
        走 Hybrid 模式：USB 插一次 → `adb tcpip 5555` → 拔线 → `adb connect <IP>:5555`。
        手机重启后失效，需重插 USB。
```

- [ ] **Step 4: Loader smoke**

```bash
cd cli && python -c "
from fleet.guidance import load_guidance_yaml
for n in ['android_dev_options.yaml','android_usb_debug.yaml','android_wireless_pair.yaml']:
    s = load_guidance_yaml(n)
    print(n, '->', s.title, 'variants:', list(s.variants.keys()))
"
```
Expected: 3 lines, dev_options has 7 variants, usb_debug has 3, wireless has 2.

- [ ] **Step 5: Commit**

```bash
git add cli/src/fleet/guidance/android_*.yaml
git commit -m "feat(cli): Android guidance YAMLs (dev options × 7 OEMs, USB debug, wireless pair)"
```

---

### Task 17: Windows guidance YAML

**Files:**
- Create: `cli/src/fleet/guidance/windows_postinstall.yaml`

- [ ] **Step 1: Write `windows_postinstall.yaml`**

```yaml
step:
  title: "Windows 部署后注意事项"
  default_description: |
    winpc-gui 一般不需要额外权限授权，但提醒：
    1. 测试期间用户会话必须解锁（屏幕锁定时 take_screenshot 拿到的是锁屏图）。
       如果是远程部署 / 长期 unattended，建议配置 autologon。
    2. Windows Defender SmartScreen 可能在首次启动 python.exe 时弹窗，点"仍要运行"即可。
    3. Tailscale 接口防火墙规则已自动创建（端口 8766 / 8768）；
       如果改了端口需重建规则。
  variant_label: "Windows 版本"
  variants:
    win11:
      label: "Windows 11"
      description: "Settings → System → For developers → Developer Mode（一般不需要打开，除非有 sideload 场景）"
    win10:
      label: "Windows 10"
      description: "Settings → Update & Security → For developers → Developer Mode"
```

- [ ] **Step 2: Loader smoke**

```bash
cd cli && python -c "from fleet.guidance import load_guidance_yaml; print(load_guidance_yaml('windows_postinstall.yaml').title)"
```
Expected: title prints.

- [ ] **Step 3: Commit**

```bash
git add cli/src/fleet/guidance/windows_postinstall.yaml
git commit -m "feat(cli): Windows post-install guidance YAML"
```

---

## Phase 5 — Verify subsystem

### Task 18: Server verification

**Files:**
- Create: `cli/src/fleet/verify.py`
- Create: `cli/tests/test_verify.py`

- [ ] **Step 1: Write test**

```python
# cli/tests/test_verify.py
import socket
from unittest.mock import patch, MagicMock
from fleet.verify import probe_port_open, probe_mcp_server


def test_probe_port_open_localhost_closed():
    # Port that is definitely not in use
    assert probe_port_open("127.0.0.1", 1) is False


@patch("socket.socket")
def test_probe_port_open_yes(mock_sock_cls):
    s = MagicMock()
    s.connect_ex.return_value = 0
    mock_sock_cls.return_value = s
    assert probe_port_open("host", 8767) is True


@patch("socket.socket")
def test_probe_mcp_server_port_closed_returns_fail(mock_sock_cls):
    s = MagicMock()
    s.connect_ex.return_value = 1
    mock_sock_cls.return_value = s
    r = probe_mcp_server("host", 8767)
    assert r.ok is False
    assert "not listening" in (r.error or "").lower()
```

- [ ] **Step 2: Run, fail**

```bash
pytest cli/tests/test_verify.py -v
```

- [ ] **Step 3: Write `cli/src/fleet/verify.py`**

```python
from __future__ import annotations

import asyncio
import socket

from .types import VerifyResult


def probe_port_open(host: str, port: int, timeout: float = 1.5) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        return s.connect_ex((host, port)) == 0
    except OSError:
        return False
    finally:
        s.close()


def probe_mcp_server(host: str, port: int) -> VerifyResult:
    """Probe an MCP streamable-http server. Returns VerifyResult with tool count."""
    if not probe_port_open(host, port):
        return VerifyResult(ok=False, error=f"port {port} on {host} not listening")
    url = f"http://{host}:{port}/mcp"
    try:
        tool_count = asyncio.run(_list_tools_count(url))
    except Exception as e:
        return VerifyResult(ok=False, error=f"MCP probe failed: {type(e).__name__}: {e}", details={"url": url})
    return VerifyResult(ok=True, tool_count=tool_count, details={"url": url})


async def _list_tools_count(url: str) -> int:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client
    async with streamablehttp_client(url) as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()
            tools = await s.list_tools()
            return len(tools.tools)
```

- [ ] **Step 4: Run, pass**

```bash
pytest cli/tests/test_verify.py -v
```
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add cli/src/fleet/verify.py cli/tests/test_verify.py
git commit -m "feat(cli): server verification (port probe + MCP list_tools)"
```

---

## Phase 6 — Wizard interactive flow

### Task 19: Wizard core orchestration (non-interactive parts)

**Files:**
- Create: `cli/src/fleet/wizard.py`
- Create: `cli/tests/test_wizard.py`

- [ ] **Step 1: Write test**

```python
# cli/tests/test_wizard.py
from unittest.mock import patch, MagicMock
from fleet.wizard import build_install_context, render_install_summary
from fleet.types import OSInfo, ServerRole


def test_build_install_context_macos():
    osi = OSInfo(system="Darwin", version="22", arch="x86_64", is_apple_silicon=False)
    ctx = build_install_context(repo_root="/tmp/repo", os_info=osi, dry_run=False,
                                 network="tailscale", tailscale_hostname="mac-test")
    assert ctx.repo_root == "/tmp/repo"
    assert ctx.tailscale_hostname == "mac-test"
    assert ctx.dry_run is False


def test_render_install_summary():
    roles = [
        ServerRole(role_id="macbox-gui", display_name="macOS desktop", hostname="mac-test", port=8767),
        ServerRole(role_id="android-gui", display_name="Android bridge", hostname="mac-test", port=8768),
    ]
    out = render_install_summary(tailscale_hostname="mac-test", deployed_roles=roles)
    assert "mac-test" in out
    assert "http://mac-test:8767/mcp" in out
    assert "http://mac-test:8768/mcp" in out
```

- [ ] **Step 2: Run, fail**

```bash
pytest cli/tests/test_wizard.py -v
```

- [ ] **Step 3: Write `cli/src/fleet/wizard.py`**

```python
"""Wizard orchestration. Interactive prompts are isolated in cli.py for testability."""
from __future__ import annotations

from typing import Literal

from .types import InstallContext, OSInfo, ServerRole


def build_install_context(
    *, repo_root: str, os_info: OSInfo, dry_run: bool,
    network: Literal["lan", "tailscale"], tailscale_hostname: str | None,
) -> InstallContext:
    return InstallContext(
        repo_root=repo_root,
        os_info=os_info,
        dry_run=dry_run,
        selected_network=network,
        tailscale_hostname=tailscale_hostname,
    )


def render_install_summary(*, tailscale_hostname: str | None, deployed_roles: list[ServerRole]) -> str:
    lines = ["🎉 Done!", "", "  This machine"]
    if tailscale_hostname:
        lines.append(f"    Tailscale hostname : {tailscale_hostname}")
    lines.append("    Endpoints:")
    for r in deployed_roles:
        lines.append(f"      {r.role_id:<13} →  {r.url}")
    lines.append("")
    lines.append("  Re-run wizard to modify: uvx agent-fleet setup")
    return "\n".join(lines)
```

- [ ] **Step 4: Run, pass**

```bash
pytest cli/tests/test_wizard.py -v
```
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add cli/src/fleet/wizard.py cli/tests/test_wizard.py
git commit -m "feat(cli): wizard core (build_install_context + render_install_summary)"
```

---

### Task 20: Interactive CLI (questionary) + main entry

**Files:**
- Create: `cli/src/fleet/cli.py`
- Create: `cli/tests/test_cli_smoke.py`

- [ ] **Step 1: Write test**

```python
# cli/tests/test_cli_smoke.py
from fleet.cli import main


def test_cli_no_args_prints_help(capsys):
    rc = main(["--help"])
    captured = capsys.readouterr()
    assert "agent-fleet" in captured.out.lower() or "setup" in captured.out.lower()
    assert rc == 0


def test_cli_version_flag(capsys):
    import fleet
    rc = main(["--version"])
    captured = capsys.readouterr()
    assert fleet.__version__ in captured.out
    assert rc == 0
```

- [ ] **Step 2: Run, fail**

```bash
pytest cli/tests/test_cli_smoke.py -v
```

- [ ] **Step 3: Write `cli/src/fleet/cli.py`**

```python
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

import questionary
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax

import fleet
from .detect import detect_os, detect_tailscale, detect_uv
from .frameworks import FRAMEWORK_REGISTRY
from .installers import filter_for_os
from .types import ServerRole
from .wizard import build_install_context, render_install_summary
from .frameworks.base import ServerRoleEntry

console = Console()


def _banner():
    osi = detect_os()
    uv = detect_uv()
    ts = detect_tailscale()
    lines = [
        f"agent-fleet v{fleet.__version__}",
        f"  OS         : {osi.system} {osi.version} ({osi.arch})",
        f"  uv         : {'ok' if uv else 'missing'}",
        f"  Tailscale  : {'logged in as ' + ts.hostname if ts else 'not detected'}",
    ]
    console.print(Panel("\n".join(lines), title="🚢 agent-fleet"))
    return osi, ts


def _select_roles(osi):
    candidates = filter_for_os(osi)
    if not candidates:
        console.print("[red]No supported roles for this OS.[/red]")
        return []
    answer = questionary.checkbox(
        f"Roles for this {osi.kind} machine to host:",
        choices=[questionary.Choice(f"{i.role_id}  ({i.display_name}, :{i.port})", value=i) for i in candidates],
    ).ask()
    return answer or []


def _select_network(ts):
    default = "tailscale" if ts else "lan"
    choice = questionary.select(
        "Network mode:",
        choices=[
            questionary.Choice("LAN / same WiFi", value="lan"),
            questionary.Choice("Tailscale (recommended)" + (" [logged in]" if ts else " [not detected]"), value="tailscale"),
        ],
        default="LAN / same WiFi" if default == "lan" else "Tailscale (recommended)",
    ).ask()
    return choice or "lan"


def _select_frameworks():
    return questionary.checkbox(
        "Which agent frameworks to generate config for?",
        choices=[questionary.Choice(f"{fw.framework_id}  ({fw.display_name})", value=fw) for fw in FRAMEWORK_REGISTRY],
    ).ask() or []


def _print_framework_snippets(frameworks, server_roles):
    entries = [ServerRoleEntry(role=r) for r in server_roles]
    for fw in frameworks:
        snippet = fw.render_full_snippet(entries)
        lang = "json" if fw.config_format == "json" else "yaml"
        console.print(Panel(Syntax(snippet, lang, line_numbers=False), title=f"{fw.display_name} → {fw.config_path_template}"))
        if fw.notes():
            console.print(f"[dim]Notes: {fw.notes()}[/dim]\n")
        if fw.cli_alternative():
            console.print(f"[cyan]CLI alternative:[/cyan]\n{fw.cli_alternative()}\n")


def _run_install(roles, ctx, role_objs):
    for r in roles:
        console.print(f"\n[bold]Installing {r.role_id}…[/bold]")
        for ev in r.install(ctx):
            color = "red" if ev.level == "error" else ("yellow" if ev.level == "warn" else "white")
            console.print(f"  [{color}]{ev.message}[/{color}]")
    # Verify each
    deployed = []
    for r in roles:
        result = r.verify()
        if result.ok:
            console.print(f"  [green]✓[/green] {r.role_id} verified ({result.tool_count} tools)")
            deployed.append(ServerRole(role_id=r.role_id, display_name=r.display_name,
                                       hostname=ctx.tailscale_hostname or "127.0.0.1", port=r.port))
        else:
            console.print(f"  [red]✗[/red] {r.role_id} verify failed: {result.error}")
    return deployed


def _run_guidance(roles):
    for r in roles:
        steps = r.guidance_steps()
        if not steps:
            continue
        console.print(f"\n[bold magenta]🔓 Operation guidance for {r.role_id}[/bold magenta]")
        for i, s in enumerate(steps, 1):
            console.print(f"\n  [bold]Step {i}/{len(steps)}: {s.title}[/bold]")
            console.print(f"  {s.default_description}")
            if s.variants:
                console.print(f"\n  [dim]{s.variant_label} 变体：[/dim]")
                for vid, v in s.variants.items():
                    console.print(f"    [cyan]{v.label}[/cyan]: {v.description}")
            questionary.press_any_key_to_continue("  ↩ 完成后回车继续").ask()


def cmd_setup(args: argparse.Namespace) -> int:
    osi, ts = _banner()
    roles = _select_roles(osi)
    if not roles:
        console.print("[yellow]No roles selected — exiting.[/yellow]")
        return 0
    network = _select_network(ts)
    hostname = ts.hostname if ts else None

    ctx = build_install_context(
        repo_root=str(Path.cwd()),
        os_info=osi,
        dry_run=args.dry_run,
        network=network,
        tailscale_hostname=hostname,
    )

    deployed = _run_install(roles, ctx, [])
    _run_guidance(roles)

    frameworks = _select_frameworks()
    if frameworks:
        _print_framework_snippets(frameworks, deployed)

    console.print(Panel(render_install_summary(tailscale_hostname=hostname, deployed_roles=deployed)))
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="agent-fleet", description="agent-fleet: install MCP servers and generate agent-client config")
    parser.add_argument("--version", action="version", version=fleet.__version__)
    sub = parser.add_subparsers(dest="cmd")

    p_setup = sub.add_parser("setup", help="Run the interactive setup wizard")
    p_setup.add_argument("--dry-run", action="store_true", help="Show actions without writing")
    p_setup.set_defaults(func=cmd_setup)

    args = parser.parse_args(argv)
    if not getattr(args, "cmd", None):
        parser.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run smoke test, pass**

```bash
pytest cli/tests/test_cli_smoke.py -v
```
Expected: 2 passed.

- [ ] **Step 5: Run uvx-style end-to-end (uvx not yet but local install)**

```bash
cd cli && pip install -e .[dev]
agent-fleet --version
agent-fleet --help
```
Expected: version prints; help lists `setup` subcommand.

- [ ] **Step 6: Commit**

```bash
git add cli/src/fleet/cli.py cli/tests/test_cli_smoke.py
git commit -m "feat(cli): CLI entry + interactive wizard (questionary + rich)"
```

---

## Phase 7 — One-shot install scripts

### Task 21: install.sh + install.ps1

**Files:**
- Create: `install.sh`
- Create: `install.ps1`

- [ ] **Step 1: Write `install.sh`**

```bash
#!/usr/bin/env bash
# One-shot installer for agent-fleet.
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/metahub-tech/agent-fleet/main/install.sh | bash
set -e

echo "🚢 agent-fleet one-shot installer"

if ! command -v uv >/dev/null 2>&1; then
    echo "uv 未安装，正在装..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
fi

if ! command -v uv >/dev/null 2>&1; then
    echo "ERROR: uv install completed but uv still not on PATH."
    echo "Open a new shell and run: uv tool run agent-fleet setup"
    exit 1
fi

echo "Running: uv tool run agent-fleet setup"
exec uv tool run agent-fleet setup "$@"
```

- [ ] **Step 2: Write `install.ps1`**

```powershell
# One-shot installer for agent-fleet (Windows).
# Usage:
#   powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/metahub-tech/agent-fleet/main/install.ps1 | iex"

Write-Host "🚢 agent-fleet one-shot installer"

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "uv 未安装，正在装..."
    powershell -ExecutionPolicy Bypass -c "irm https://astral.sh/uv/install.ps1 | iex"
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
}

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "ERROR: uv install completed but uv still not on PATH."
    Write-Host "Open a new shell and run: uv tool run agent-fleet setup"
    exit 1
}

Write-Host "Running: uv tool run agent-fleet setup"
uv tool run agent-fleet setup
```

- [ ] **Step 3: Lint both scripts**

```bash
chmod +x install.sh
bash -n install.sh && echo "install.sh OK"
bash scripts/check-ps-syntax.sh install.ps1 2>&1 | tail -3
```
Expected: `install.sh OK` and PS syntax check passes.

- [ ] **Step 4: Commit**

```bash
git add install.sh install.ps1
git commit -m "feat: one-shot install scripts (install.sh + install.ps1)"
```

---

## Phase 8 — Migration & polish

### Task 22: Deprecate `install-agent-side.py`

**Files:**
- Modify: `scripts/install-agent-side.py`

- [ ] **Step 1: Add deprecation banner at top of script body**

Find the `def main()` function and insert at the very top of its body (after argparse parsing):

```python
def main() -> None:
    args = parse_args()
    # --- DEPRECATION NOTICE (v0.5.0+) ---
    print("=" * 72, file=sys.stderr)
    print(" DEPRECATION NOTICE", file=sys.stderr)
    print("   scripts/install-agent-side.py is deprecated as of v0.5.0.", file=sys.stderr)
    print("   Use the new wizard instead:", file=sys.stderr)
    print("     uvx agent-fleet setup", file=sys.stderr)
    print("   or, with the one-shot bootstrap:", file=sys.stderr)
    print("     curl -fsSL https://raw.githubusercontent.com/metahub-tech/agent-fleet/main/install.sh | bash", file=sys.stderr)
    print("   This script will be removed in v0.6.0.", file=sys.stderr)
    print("=" * 72, file=sys.stderr)
    print(file=sys.stderr)
    # --- end ---

    spec = PLATFORMS[args.platform]
    # ... rest of existing function unchanged
```

- [ ] **Step 2: Smoke check deprecation banner appears**

```bash
TMPCFG=$(mktemp /tmp/c-XXXX.json); echo '{}' > "$TMPCFG"
TMPSKILLS=$(mktemp -d /tmp/s-XXXX)
python3 scripts/install-agent-side.py --platform macbox-gui --hostname x \
    --config "$TMPCFG" --skills-dir "$TMPSKILLS" --dry-run 2>&1 | head -10
rm -f "$TMPCFG" "$TMPCFG".bak-*; rm -rf "$TMPSKILLS"
```
Expected: banner appears in output.

- [ ] **Step 3: Commit**

```bash
git add scripts/install-agent-side.py
git commit -m "chore: deprecate install-agent-side.py in favor of uvx agent-fleet setup"
```

---

### Task 23: README front-matter updates

**Files:**
- Modify: `README.md` (top section — replace 快速开始 block)

- [ ] **Step 1: Read current README quick-start to know exact replacement**

```bash
sed -n '40,75p' README.md
```

- [ ] **Step 2: Replace the 快速开始 section with new wizard-first flow**

Replace the entire `## 快速开始` block (lines ≈ 40–65) with:

```markdown
## 快速开始

**新手 / 一键流**：在被控设备（PC / 接了手机的 PC）上：

```bash
# macOS / Linux
curl -fsSL https://raw.githubusercontent.com/metahub-tech/agent-fleet/main/install.sh | bash

# Windows
powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/metahub-tech/agent-fleet/main/install.ps1 | iex"
```

或，如果已经有 uv：

```bash
uvx agent-fleet setup
```

wizard 会带你走完：选角色 → 装 MCP server → 配 Tailscale → GUI 权限 / ADB 授权交互式引导 → 自动健康检测 → 输出 6 个 agent 框架的配置片段。

**老手**：仍可直接调底层脚本——`docs/install-pattern.md` 仍有效（"高级用户手册"）。

| 你是 | 看哪个 |
|---|---|
| **新手**（让 wizard 带你走） | 跑上面那行命令，跟着提示选 |
| **设备管理员，要自己写脚本编排部署** | [`docs/install-pattern.md`](docs/install-pattern.md)（底层脚本契约）|
| **Agent 操作员** | wizard 输出的 snippet 直接 paste 到对应 agent 配置；也可参考 [`docs/agent-host-setup.md`](docs/agent-host-setup.md) |
| **设计文档**（贡献者） | [`docs/design/2026-05-11-agent-fleet-cli.md`](docs/design/2026-05-11-agent-fleet-cli.md) |
```

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs(README): wizard-first 快速开始 (uvx agent-fleet setup)"
```

---

### Task 24: pyproject.toml root + repo restructure prep

**Files:**
- Create: `pyproject.toml` (repo root)

- [ ] **Step 1: Write repo-root `pyproject.toml`**

Note: this is a *thin* pointer at repo root that delegates to the real one in `cli/`. Or alternatively, make `cli/pyproject.toml` the canonical one and skip this step.

Decision: keep canonical at `cli/pyproject.toml`. Skip creating a duplicate root one for v0.5.0-alpha. Document the choice in CHANGELOG.

- [ ] **Step 2: Run the full test suite**

```bash
cd cli && pytest -v
```
Expected: all tests from Tasks 1-20 pass.

- [ ] **Step 3: Commit (if any test fixes needed)**

```bash
git add -A
git commit -m "chore(cli): full pytest suite green at v0.5.0-alpha"
```

---

## Phase 9 — End-to-end validation on real devices

### Task 25: Manual end-to-end smoke (no checkbox in plan — operator-driven)

This task is **manual**. Document the procedure but no automated test.

**Procedure (run on each of 3 host OSes)**:

1. From a fresh `git clone` of `agent-fleet` repo:
   ```bash
   cd cli && pip install -e .
   agent-fleet --version
   agent-fleet setup --dry-run   # walk through wizard prompts in dry-run mode
   ```
2. Confirm wizard:
   - Shows correct OS in banner
   - Filters role choices to OS-supported only
   - All 6 framework snippets render without exception
   - Summary lists correct URLs
3. Without `--dry-run`, run an actual install for one role on a clean VM. Confirm:
   - setup script executes
   - service starts (port listens)
   - `verify()` returns ok with non-zero tool count
   - Guidance steps render with variants
4. Take a screenshot of the wizard output and attach to the v0.5.0-alpha release notes.

No commit needed (manual validation).

---

## Self-Review

### Spec coverage

| Spec section | Plan task(s) |
|---|---|
| § 2 命名与分发 | Task 1 (pyproject.toml name = agent-fleet) |
| § 3 架构 | Tasks 1, 13 (registry), 19, 20 |
| § 4 wizard 流程 | Tasks 19 (orchestration), 20 (interactive flow), 21 (one-shot) |
| § 4 [6] 操作引导 | Tasks 14 (loader), 15 (macOS YAMLs), 16 (Android YAMLs), 17 (Windows YAML), 20 (renderer) |
| § 5 内部抽象 | Tasks 4 (FrameworkConfig), 8 (Installer), 14 (GuidanceStep) |
| § 6 variants schema | Tasks 14, 15, 16 |
| § 7 install.sh / .ps1 | Task 21 |
| § 8 迁移 | Task 22 (deprecation), Task 25 (manual) |
| § 9 测试策略 | Tasks 2-20 (unit tests), Task 25 (e2e manual) |
| § 11 milestones | Tasks 1-20 = v0.5.0-alpha; Tasks 21-24 = v0.5.0-beta/rc/GA |
| § 12 不破坏现有部署 | Task 22 (deprecation, keeps script working with warning), no edits to existing setup scripts, no MCP server / port / label changes |

✓ All spec sections have a task.

### Placeholder scan

- No `TBD`, `TODO`, "implement later", "add appropriate error handling" anywhere.
- Each step has complete code or commands.
- No "similar to task N" without repeating the content.

### Type consistency

- `OSInfo`, `ServerRole`, `VerifyResult`, `InstallContext`, `InstallEvent`, `GuidanceStep`, `GuidanceVariant`: defined in Task 2, used consistently across Tasks 3-20.
- `BaseInstaller` (Task 8) methods: `is_supported_on`, `preflight`, `install`, `verify`, `guidance_steps` — all 5 subclasses (Tasks 9-12) implement same signatures.
- `BaseFrameworkConfig` (Task 4) methods: `render_entry`, `render_full_snippet`, `cli_alternative`, `notes` — all 6 subclasses (Tasks 5-6) match.
- `INSTALLER_REGISTRY` and `FRAMEWORK_REGISTRY` naming consistent (Tasks 7, 13).

### Scope check

Plan covers v0.5.0-alpha through approximately v0.5.0-beta. The final tag-and-publish step (private PyPI, GitHub repo rename) is left to operational milestones (not coded). v0.5.1 (public PyPI, docs reorg) is explicitly out of scope of this plan.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-11-agent-fleet-cli.md`. Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans; batch execution with checkpoints for review.

Which approach?
