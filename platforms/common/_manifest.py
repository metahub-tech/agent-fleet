"""Load a platform's platform.toml into a PlatformManifest (SSOT)."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

try:
    import tomllib  # py3.11+
except ModuleNotFoundError:  # py3.10
    import tomli as tomllib  # type: ignore


@dataclass
class PlatformManifest:
    id: str
    display_name: str
    port: int
    status: str
    multi_device: bool
    host_os: list[str]
    server_module: str
    setup_script: str
    guidance: list[str]
    options: dict = field(default_factory=dict)        # [install.options]
    config_reuse: dict = field(default_factory=dict)   # [install.config_reuse]
    aliases: dict[str, str] = field(default_factory=dict)  # canonical -> current
    toml_path: Path = field(default=Path("."))

    @property
    def dir(self) -> Path:
        return self.toml_path.parent

    @property
    def server_path(self) -> Path:
        return self.dir / "server" / f"{self.server_module}.py"


def load_manifest(path: str | Path) -> PlatformManifest:
    path = Path(path)
    with path.open("rb") as f:
        data = tomllib.load(f)
    p = data["platform"]
    install = data.get("install", {})
    return PlatformManifest(
        id=p["id"],
        display_name=p["display_name"],
        port=int(p["port"]),
        status=p["status"],
        multi_device=bool(p.get("multi_device", False)),
        host_os=list(p["host_os"]),
        server_module=data["server"]["module"],
        setup_script=install.get("setup_script", ""),
        guidance=list(install.get("guidance", [])),
        options=install.get("options", {}),
        config_reuse=install.get("config_reuse", {}),
        aliases=dict(data.get("tools", {}).get("aliases", {})),
        toml_path=path.resolve(),
    )


def discover_manifests(platforms_dir: str | Path) -> list[PlatformManifest]:
    platforms_dir = Path(platforms_dir)
    return [load_manifest(p) for p in sorted(platforms_dir.glob("*/platform.toml"))]
