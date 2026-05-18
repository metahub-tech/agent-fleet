#!/usr/bin/env python3
"""Interactive alias setup for the Android MCP wizard.

Runs `adb devices -l` + `getprop ro.product.brand` to detect attached phones,
derives default aliases via the server's _aliases module, prompts the user
to confirm or override each, and writes ~/.agent-fleet/android-aliases.json.

Usage:
    python3 setup_aliases.py [--adb /path/to/adb] [--non-interactive]

Exit code 0 on success (even with zero devices -- saves an empty config).
Exit code 2 on user-cancelled or unrecoverable adb error.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Make the server module importable: _aliases.py lives one directory up in
# ../server/.  We add that dir to sys.path so `import _aliases` resolves
# without installing anything.
# ---------------------------------------------------------------------------
_SCRIPT_DIR = Path(__file__).resolve().parent
_SERVER_DIR = _SCRIPT_DIR.parent / "server"
if str(_SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(_SERVER_DIR))

from _aliases import DeviceInfo, assign_aliases, load_aliases, resolve_aliases, save_aliases  # noqa: E402


# ---------------------------------------------------------------------------
# ADB helpers (intentionally self-contained; do NOT import android_device_mcp
# which has FastMCP / Pillow dependencies not present at wizard run time)
# ---------------------------------------------------------------------------

def _resolve_adb(adb_flag: str | None) -> str:
    """Return adb binary path or exit 2."""
    if adb_flag:
        if Path(adb_flag).is_file():
            return adb_flag
        # Treat as a plain command name too
    if adb_flag and shutil.which(adb_flag):
        return adb_flag
    if shutil.which("adb"):
        return "adb"
    print("adb not in PATH; pass --adb /path/to/adb", file=sys.stderr)
    sys.exit(2)


def _run(args: list[str], timeout: int) -> tuple[int, str, str]:
    """Run a subprocess. Returns (returncode, stdout, stderr)."""
    try:
        r = subprocess.run(args, capture_output=True, timeout=timeout)
        return (
            r.returncode,
            r.stdout.decode("utf-8", errors="replace"),
            r.stderr.decode("utf-8", errors="replace"),
        )
    except subprocess.TimeoutExpired:
        return (-1, "", f"timed out after {timeout}s")
    except FileNotFoundError as exc:
        return (-2, "", str(exc))


# ---------------------------------------------------------------------------
# Device detection
# ---------------------------------------------------------------------------

def parse_devices_output(text: str) -> list[tuple[str, str | None]]:
    """Parse `adb devices -l` stdout.

    Returns list of (serial, model_or_None) for *authorized* devices only.
    Lines where state != "device" (e.g. "unauthorized", "offline") are skipped.
    """
    result: list[tuple[str, str | None]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("List of devices"):
            continue
        parts = line.split()
        # Must have at least <serial> <state>
        if len(parts) < 2:
            continue
        # Only authorized, online devices
        if parts[1] != "device":
            continue
        serial = parts[0]
        model: str | None = None
        for kv in parts[2:]:
            if kv.startswith("model:"):
                model = kv[len("model:"):]
                break
        result.append((serial, model))
    return result


def detect_devices(adb: str) -> list[DeviceInfo]:
    """Run adb devices -l and enrich each authorized serial with brand/model."""
    rc, stdout, stderr = _run([adb, "devices", "-l"], timeout=10)
    if rc != 0:
        print(f"ERROR: adb devices -l failed (rc={rc}): {stderr}", file=sys.stderr)
        sys.exit(2)

    parsed = parse_devices_output(stdout)

    devices: list[DeviceInfo] = []
    for serial, model in parsed:
        # Brand via getprop
        brc, bstdout, _ = _run([adb, "-s", serial, "shell", "getprop", "ro.product.brand"], timeout=5)
        brand: str | None = bstdout.strip() if brc == 0 else None
        brand = brand or None  # empty string -> None

        if model is None:
            mrc, mstdout, _ = _run([adb, "-s", serial, "shell", "getprop", "ro.product.model"], timeout=5)
            if mrc == 0:
                model = mstdout.strip() or None

        devices.append(DeviceInfo(serial=serial, brand=brand, model=model))

    devices.sort(key=lambda d: d.serial)
    return devices


# ---------------------------------------------------------------------------
# Alias config path
# ---------------------------------------------------------------------------

ALIAS_CONFIG_PATH = Path.home() / ".agent-fleet" / "android-aliases.json"


# ---------------------------------------------------------------------------
# Interactive prompt
# ---------------------------------------------------------------------------
# NOTE: The interactive prompt loop is tested manually by running the wizard
# with attached phones.  Automated unit tests cover the pure-logic helpers
# (parse_devices_output, detect_devices via mocked subprocess, file write).
# Mocking stdin in tests for this loop adds complexity without proportional
# value, so it is intentionally left out of the test suite.

def prompt_aliases(
    devices: list[DeviceInfo],
    proposed: dict[str, str],
    non_interactive: bool,
) -> dict[str, str]:
    """For each device, confirm or override the proposed alias.

    In non-interactive mode all defaults are accepted silently.
    Returns {serial: chosen_alias} for every detected device.
    """
    chosen: dict[str, str] = {}
    for i, dev in enumerate(devices, start=1):
        default_alias = proposed[dev.serial]
        if non_interactive:
            print(f"  [{i}] {default_alias:<30}  ({dev.serial})  -> accepted (non-interactive)")
            chosen[dev.serial] = default_alias
            continue
        # Interactive
        while True:
            try:
                raw = input(f"  [{i}] {default_alias:<30}  ({dev.serial})    alias [{default_alias}]: ")
            except EOFError:
                # stdin closed (e.g. piped /dev/null in tests) -- accept default
                chosen[dev.serial] = default_alias
                break
            alias = raw.strip()
            if alias == "":
                chosen[dev.serial] = default_alias
                break
            if not alias:
                print("  (alias cannot be blank; press Enter to keep the default)")
                continue
            chosen[dev.serial] = alias
            break
    return chosen


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Detect Android devices and configure friendly aliases."
    )
    parser.add_argument("--adb", default=None, help="Path to adb binary (default: adb on PATH)")
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Accept all defaults without prompting (CI use)",
    )
    args = parser.parse_args(argv)

    adb = _resolve_adb(args.adb)

    # --- Detect ---
    devices = detect_devices(adb)

    if not devices:
        print(
            "No Android devices attached. "
            "Plug one via USB and re-run setup, or skip this step "
            "(the server will work once a device appears later)."
        )
        return 0

    # --- Load existing overrides ---
    try:
        existing = load_aliases(ALIAS_CONFIG_PATH)
    except Exception as exc:  # noqa: BLE001
        print(f"  WARNING: could not read existing aliases ({exc}); starting fresh.")
        existing = {}

    # --- Compute proposed aliases (existing overrides respected) ---
    proposed = resolve_aliases(devices, existing)

    print(f"\n  Detected {len(devices)} device(s).  Press Enter to keep the default alias, or type a new one.\n")

    # --- Prompt ---
    chosen = prompt_aliases(devices, proposed, args.non_interactive)

    # --- Save ---
    try:
        save_aliases(ALIAS_CONFIG_PATH, chosen)
        print(f"\n  Saved alias config: {ALIAS_CONFIG_PATH}")
        for serial, alias in sorted(chosen.items()):
            print(f"    {serial}  ->  {alias}")
    except Exception as exc:  # noqa: BLE001
        print(f"  ERROR: could not save alias config: {exc}", file=sys.stderr)
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
