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
        # encoding="utf-8" + errors="replace" — Tailscale always emits UTF-8
        # JSON, but on Chinese Windows the subprocess default decode is GBK
        # (locale.getpreferredencoding()) which crashes on UTF-8 bytes >0x7f
        # (e.g. Tailscale node names with ™ / ® / 中文 / em-dash).  Reading
        # thread dies with UnicodeDecodeError, r.stdout becomes None, then
        # `r.stdout.strip()` blows up with AttributeError.
        r = subprocess.run(
            ["tailscale", "status", "--json"],
            capture_output=True, timeout=5,
            encoding="utf-8", errors="replace",
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0 or not r.stdout or not r.stdout.strip():
        return None
    try:
        data = json.loads(r.stdout)
        self_node = data.get("Self") or {}
        # Self.HostName is the OS hostname (e.g. "Yi的MacBook Pro") which is
        # non-routable when it has spaces / non-ASCII.  Self.DNSName has the
        # Tailscale-admin-assigned routable name as its first label, e.g.
        # "test-macpro-12.tail-XXX.ts.net.".  Prefer that.
        raw_host = self_node.get("HostName") or ""
        fqdn = (self_node.get("DNSName") or "").rstrip(".")
        if fqdn and "." in fqdn:
            host = fqdn.split(".", 1)[0]
        else:
            host = raw_host
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
