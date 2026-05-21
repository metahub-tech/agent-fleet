import sys
from pathlib import Path

import pytest

_here = Path(__file__).resolve().parent
sys.path.insert(0, str(_here))          # platforms/tests (for _ast_tools)
sys.path.insert(0, str(_here.parent))   # platforms/ (for common)
from _ast_tools import extract_mcp_tools
from common import _canonical_tools as ct
from common._manifest import discover_manifests

PLATFORMS_DIR = _here.parent
MANIFESTS = discover_manifests(PLATFORMS_DIR)
IDS = [m.id for m in MANIFESTS]

# CORE tools not yet implemented on a platform, tracked explicitly so the gate stays
# green while the gap stays visible. P1b implemented all of win/mac's former gaps
# (swipe via click-drag + the single-device-state tools via DeviceStateRegistry), so
# this is now empty. Re-add an entry only with a documented reason + a removal plan.
KNOWN_P1_GAPS: dict[str, set[str]] = {}


def _covered(tools, m, canon, spec):
    impl_name = canon if canon in tools else m.aliases.get(canon)
    if impl_name is None or impl_name not in tools:
        return False, impl_name
    actual = [p for p in tools[impl_name] if p not in ct.ALLOWED_EXTRA]
    # NB: ALLOWED_EXTRA strips `device`/`ctx`. For set_default_device the substantive
    # arg is itself named `device`, so it gets stripped too -> arity check is vacuous
    # for that one tool (canonical spec is `["device?"]`, required_arity 0). Acceptable
    # in P0; P3 renames the param to `target_device` and tightens the spec to required.
    return len(actual) >= ct.required_arity(spec), impl_name


@pytest.mark.parametrize("m", MANIFESTS, ids=IDS)
def test_core_tools_covered(m):
    tools = extract_mcp_tools(m.server_path)
    gaps = KNOWN_P1_GAPS.get(m.id, set())
    missing = []
    for canon, spec in ct.CORE.items():
        covered, impl_name = _covered(tools, m, canon, spec)
        if canon in gaps:
            # A declared gap must be genuinely uncovered — otherwise it would mask a
            # tool that actually exists. Fail loudly so the gap list stays honest.
            assert not covered, (
                f"{m.id}: '{canon}' is in KNOWN_P1_GAPS but IS implemented "
                f"(as {impl_name!r}) — remove it from the gap list."
            )
            continue
        if not covered:
            detail = canon if (impl_name is None or impl_name not in tools) else (
                f"{canon} (arity: {impl_name} has "
                f"{[p for p in tools[impl_name] if p not in ct.ALLOWED_EXTRA]}, "
                f"needs {ct.required_arity(spec)})"
            )
            missing.append(detail)
    assert not missing, f"{m.id} missing/under-spec CORE tools: {missing}"


@pytest.mark.parametrize("m", MANIFESTS, ids=IDS)
def test_aliases_point_at_real_tools(m):
    tools = extract_mcp_tools(m.server_path)
    dangling = {canon: cur for canon, cur in m.aliases.items() if cur not in tools}
    assert not dangling, f"{m.id} aliases point at non-existent tools: {dangling}"


def test_known_gaps_shrink():
    # Tripwire: every platform now covers all CORE directly or via alias. Keep this at
    # {} — re-adding an entry must come with a documented reason + removal plan.
    assert KNOWN_P1_GAPS == {}
