import sys
from pathlib import Path

import pytest

_here = Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))  # platforms/
from common._manifest import discover_manifests

MANIFESTS = discover_manifests(_here.parent)
VALID_HOST_OS = {"windows", "macos", "linux"}


def test_at_least_four_platforms():
    assert len(MANIFESTS) >= 4


def test_ports_are_unique():
    ports = [m.port for m in MANIFESTS]
    assert len(ports) == len(set(ports)), f"port collision: {ports}"


def test_ports_in_expected_band():
    for m in MANIFESTS:
        assert 8766 <= m.port <= 8799, f"{m.id} port {m.port} out of band"


def test_host_os_values_valid():
    for m in MANIFESTS:
        assert set(m.host_os) <= VALID_HOST_OS, f"{m.id} bad host_os {m.host_os}"
        assert m.host_os, f"{m.id} empty host_os"


def test_status_values_valid():
    for m in MANIFESTS:
        assert m.status in {"released", "beta", "planned"}, f"{m.id} status {m.status}"


def test_setup_script_exists():
    for m in MANIFESTS:
        if m.setup_script:
            assert (m.dir / m.setup_script).exists(), f"{m.id} missing {m.setup_script}"
