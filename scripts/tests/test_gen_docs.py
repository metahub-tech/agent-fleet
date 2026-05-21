"""Tests for scripts/gen_docs.py.

Task 1 state:
  - test_render_port_table_contains_all_manifest_ports: PASSES now (render_port_table works)
  - test_check_passes_on_fresh_docs: xfail (Task 2 fixes counts + adds markers; remove xfail then)
"""
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
import gen_docs


def test_render_port_table_contains_all_manifest_ports():
    table = gen_docs.render_port_table()
    for port in (8766, 8767, 8768, 8769):
        assert str(port) in table, f"Port {port} missing from port table:\n{table}"
    # HarmonyOS planned row
    assert "8770" in table, f"Port 8770 (HarmonyOS planned) missing from port table:\n{table}"


# Task 2 removes this xfail once it:
#   1. Adds <!-- gen:port-table --> markers to docs/architecture.md and writes the table
#   2. Fixes README win-device 33→38 and mac-device 34→39
@pytest.mark.xfail(reason="Task 2 fixes counts + adds markers to architecture.md", strict=False)
def test_check_passes_on_fresh_docs():
    r = subprocess.run(
        [sys.executable, "scripts/gen_docs.py", "--check"],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stdout + r.stderr
