#!/usr/bin/env python3
"""Thin shim: delegates to gen_docs.py (importable underscore name).

Design docs reference this as gen-docs.py; the real implementation lives
in gen_docs.py so it is importable by tests.
"""
import os
import sys
from pathlib import Path

target = Path(__file__).resolve().parent / "gen_docs.py"
os.execv(sys.executable, [sys.executable, str(target)] + sys.argv[1:])
