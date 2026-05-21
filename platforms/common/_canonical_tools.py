"""Canonical Universal Tool Set — the single code-level source of truth.

Param specs list the canonical parameter NAMES; a trailing "?" marks an optional
param. `device`/`ctx` are multi-device plumbing allowed on any tool and never
required. P0 conformance checks tool COVERAGE + required-arity (not exact param
names — name canonicalization lands in P3 with the renames).
"""

CORE: dict[str, list[str]] = {
    "get_screen_size": [],
    "take_screenshot": ["region?"],
    "tap": ["x", "y"],
    "swipe": ["x1", "y1", "x2", "y2", "duration_ms?"],
    "type_text": ["text"],
    "press_key": ["key"],
    "dump_ui": ["max_depth?"],
    "current_app": [],
    "terminate_app": ["target"],
    "list_devices": [],
    "set_default_device": ["device?"],  # NB: substantive arg named `device`, same as the plumbing param the conformance check strips; mark optional so P0 arity stays correct. P3 may rename to `target_device`.
    "get_default_device": [],
    "acquire": ["holder_name?"],
    "release": [],
    "get_status": [],
}

OPTIONAL: dict[str, list[str]] = {
    "launch_app": ["target"],
    "find_elements": ["query"],
    "tap_element": ["query"],
    "run_shell": ["script", "timeout?"],
    "long_press": ["x", "y", "duration_ms?"],
    "install_app": ["path"],
    "uninstall_app": ["target"],
}

# Plumbing params that may appear on any tool and are never counted/required.
ALLOWED_EXTRA: set[str] = {"device", "ctx"}


def required_params(spec: list[str]) -> set[str]:
    """Return the set of required param names (those NOT ending with `?`)."""
    return {p for p in spec if not p.endswith("?")}


def required_arity(spec: list[str]) -> int:
    """Count of required (non-optional) params."""
    return len(required_params(spec))
