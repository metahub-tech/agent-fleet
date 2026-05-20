"""WebDriverAgent HTTP client + per-device USB port forward.

WDA exposes a WebDriver REST API on the iOS device's localhost:8100. To talk to
it from the mac host we run a USB-tunnel forwarder per device:
  device:8100  --(pymobiledevice3 usbmux forward)-->  host:18100+N

This module wraps two concepts:

  WdaForwarder(udid, local_port)
      Long-lived subprocess that keeps the tunnel alive. start() / stop().

  WdaClient(udid, base_url)
      HTTP client to the WDA REST endpoint reachable at base_url. Lazily
      creates a session on demand, refreshes if stale.

The MCP server (ios_device_mcp.py) owns one (WdaForwarder, WdaClient) per
detected device, keyed by UDID. Tools resolve a UDID via _resolve_device()
then dispatch to the corresponding client.
"""
from __future__ import annotations

import base64
import socket
import subprocess
import sys
import time
from typing import Any

import httpx


# ---------------------------------------------------------------------------
# USB port forward
# ---------------------------------------------------------------------------

class WdaForwarder:
    """pymobiledevice3-based TCP forwarder for device:8100 -> host:local_port.

    Implemented as a subprocess of `pymobiledevice3 usbmux forward`, which
    keeps the tunnel alive until terminate(). We watch the local port to
    confirm the tunnel is actually serving before returning from start().
    """

    def __init__(self, udid: str, local_port: int):
        self.udid = udid
        self.local_port = local_port
        self._proc: subprocess.Popen | None = None

    def is_alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def start(self, wait_seconds: float = 5.0) -> None:
        if self.is_alive():
            return
        self._proc = subprocess.Popen(
            [
                sys.executable, "-m", "pymobiledevice3",
                "usbmux", "forward", str(self.local_port), "8100",
                "--udid", self.udid,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        # Wait until the forward port becomes reachable, or wait_seconds elapses.
        deadline = time.monotonic() + wait_seconds
        while time.monotonic() < deadline:
            if not self.is_alive():
                raise RuntimeError(
                    f"forwarder for {self.udid} exited prematurely (rc={self._proc.returncode}); "
                    "is pymobiledevice3 installed and the device paired?"
                )
            try:
                with socket.create_connection(("127.0.0.1", self.local_port), timeout=0.3):
                    return
            except OSError:
                time.sleep(0.2)
        # Tunnel never bound. Reap subprocess and surface error.
        self.stop()
        raise RuntimeError(
            f"forwarder for {self.udid} did not bind 127.0.0.1:{self.local_port} within {wait_seconds}s"
        )

    def stop(self) -> None:
        if self._proc is None:
            return
        try:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        finally:
            self._proc = None


# ---------------------------------------------------------------------------
# WDA HTTP client
# ---------------------------------------------------------------------------

# All WDA REST endpoints we use. Reference: appium/WebDriverAgent docs.
class WdaClient:
    """HTTP wrapper around one device's WebDriverAgent endpoint.

    Lazily creates a WDA session on first call needing it; refreshes if the
    session has expired (WDA tears down idle sessions after ~60s by default).
    Each method maps directly to the corresponding WDA REST endpoint and
    returns the JSON `value` (or a normalized error dict).
    """

    def __init__(self, udid: str, base_url: str, http_timeout: float = 20.0):
        self.udid = udid
        self.base_url = base_url
        self.session_id: str | None = None
        self._client = httpx.Client(base_url=base_url, timeout=http_timeout)

    def close(self) -> None:
        try:
            self._client.close()
        except Exception:
            pass

    # ---- low-level HTTP

    def _post(self, path: str, json: dict | None = None) -> dict:
        r = self._client.post(path, json=json if json is not None else {})
        r.raise_for_status()
        return r.json()

    def _get(self, path: str) -> dict:
        r = self._client.get(path)
        r.raise_for_status()
        return r.json()

    def _delete(self, path: str) -> dict:
        r = self._client.delete(path)
        r.raise_for_status()
        return r.json()

    # ---- session lifecycle

    def status(self) -> dict:
        """GET /status — WDA process health, no session required."""
        return self._get("/status").get("value", {})

    def ensure_session(self, bundle_id: str | None = None) -> str:
        if self.session_id:
            try:
                self._get(f"/session/{self.session_id}")
                return self.session_id
            except httpx.HTTPError:
                self.session_id = None
        caps: dict[str, Any] = {"capabilities": {"alwaysMatch": {}}}
        if bundle_id:
            caps["capabilities"]["alwaysMatch"]["bundleId"] = bundle_id
        r = self._post("/session", caps)
        self.session_id = r["value"]["sessionId"]
        return self.session_id

    def close_session(self) -> None:
        if not self.session_id:
            return
        try:
            self._delete(f"/session/{self.session_id}")
        except httpx.HTTPError:
            pass
        self.session_id = None

    # ---- screen + window

    def window_size(self) -> dict:
        sid = self.ensure_session()
        r = self._get(f"/session/{sid}/window/size")
        return r.get("value", {})

    def screenshot_png_bytes(self) -> bytes:
        # /screenshot works without an active session
        r = self._get("/screenshot")
        b64 = r.get("value", "")
        return base64.b64decode(b64)

    # ---- input

    def tap(self, x: float, y: float) -> dict:
        sid = self.ensure_session()
        return self._post(f"/session/{sid}/wda/tap", {"x": x, "y": y})

    def swipe(self, x1: float, y1: float, x2: float, y2: float, duration_ms: int) -> dict:
        sid = self.ensure_session()
        return self._post(
            f"/session/{sid}/wda/dragfromtoforduration",
            {"fromX": x1, "fromY": y1, "toX": x2, "toY": y2, "duration": duration_ms / 1000.0},
        )

    def touch_and_hold(self, x: float, y: float, duration_ms: int) -> dict:
        sid = self.ensure_session()
        return self._post(
            f"/session/{sid}/wda/touchAndHold",
            {"x": x, "y": y, "duration": duration_ms / 1000.0},
        )

    def press_button(self, name: str) -> dict:
        sid = self.ensure_session()
        return self._post(f"/session/{sid}/wda/pressButton", {"name": name})

    def type_keys(self, text: str) -> dict:
        sid = self.ensure_session()
        return self._post(f"/session/{sid}/wda/keys", {"value": list(text)})

    # ---- UI hierarchy + elements

    def page_source(self, fmt: str = "json") -> Any:
        sid = self.ensure_session()
        params = {"format": fmt}
        r = self._client.get(f"/session/{sid}/source", params=params)
        r.raise_for_status()
        return r.json().get("value")

    def find_elements(self, using: str, value: str) -> list[dict]:
        sid = self.ensure_session()
        r = self._post(f"/session/{sid}/elements", {"using": using, "value": value})
        return r.get("value", [])

    def click_element(self, element_id: str) -> dict:
        sid = self.ensure_session()
        return self._post(f"/session/{sid}/element/{element_id}/click")

    # ---- app lifecycle

    def active_app_info(self) -> dict:
        # activeAppInfo is unscoped (device-level)
        return self._get("/wda/activeAppInfo").get("value", {})

    def launch_app(self, bundle_id: str, arguments: list[str] | None = None) -> dict:
        # App lifecycle endpoints are session-scoped in WDA.
        sid = self.ensure_session()
        return self._post(
            f"/session/{sid}/wda/apps/launch",
            {"bundleId": bundle_id, **({"arguments": arguments} if arguments else {})},
        )

    def terminate_app(self, bundle_id: str) -> dict:
        sid = self.ensure_session()
        return self._post(f"/session/{sid}/wda/apps/terminate", {"bundleId": bundle_id})

    def activate_app(self, bundle_id: str) -> dict:
        sid = self.ensure_session()
        return self._post(f"/session/{sid}/wda/apps/activate", {"bundleId": bundle_id})
