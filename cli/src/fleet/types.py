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
    role_id: str               # "mac-device" / "win-device" / "android-device"
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
    android_mode: Optional[str] = None        # "usb"/"wireless"/"hybrid", collected by wizard
    android_reuse_config: bool = False        # True = reuse existing ~/.atb-android/config.toml


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
    id: str = ""               # YAML key; used to dispatch primers (e.g. "macos_accessibility")
