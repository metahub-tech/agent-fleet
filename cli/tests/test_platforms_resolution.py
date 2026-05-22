"""Regression: the CLI must locate platforms/ (and thus the `common` package +
the platform manifests) both in a dev checkout and when pip/uvx-installed
out-of-tree.

Bug (pre-v0.8.4-era): installers/__init__.py resolved platforms/ via
Path(__file__).parents[4], which points into site-packages once installed — so
`from common._manifest import ...` and the manifest scan both blew up with
`ModuleNotFoundError: No module named 'common'` on the one-shot installer. The
fix falls back to the current working directory (the installer always runs the
CLI from the repo root), so these tests exercise both resolution paths.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from fleet.installers import _resolve_platforms_dir

REPO = Path(__file__).resolve().parents[2]
REAL_INIT = REPO / "cli" / "src" / "fleet" / "installers" / "__init__.py"


def test_resolves_via_file_in_dev_checkout(tmp_path):
    # __file__-relative (parents[4]) finds platforms/ in a dev tree even when cwd
    # is unrelated.
    got = _resolve_platforms_dir(start=REAL_INIT, cwd=tmp_path)
    assert got == REPO / "platforms"
    assert (got / "common" / "_manifest.py").is_file()


def test_resolves_via_cwd_when_installed_out_of_tree(tmp_path):
    # Simulate the installed layout: __file__ deep in a venv with no platforms/
    # above it. Must fall back to cwd (= repo root, how the installer runs it).
    fake = (tmp_path / "venv" / "lib" / "python3.10" / "site-packages"
            / "fleet" / "installers" / "__init__.py")
    fake.parent.mkdir(parents=True)
    fake.write_text("")
    got = _resolve_platforms_dir(start=fake, cwd=REPO)
    assert got == REPO / "platforms"


def test_resolves_from_repo_subdir(tmp_path):
    # Run from a subdir of the repo (e.g. cwd=cli): walk up to find platforms/.
    fake = tmp_path / "x" / "y" / "z" / "a" / "b" / "__init__.py"
    got = _resolve_platforms_dir(start=fake, cwd=REPO / "cli")
    assert got == REPO / "platforms"


def test_raises_clear_error_when_not_found(tmp_path):
    fake = tmp_path / "a" / "b" / "c" / "d" / "e" / "f" / "__init__.py"
    fake.parent.mkdir(parents=True)
    fake.write_text("")
    with pytest.raises(ModuleNotFoundError, match="platforms/"):
        _resolve_platforms_dir(start=fake, cwd=tmp_path)
