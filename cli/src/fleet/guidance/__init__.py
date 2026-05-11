"""Guidance YAML loading. YAML files live next to this module."""
from __future__ import annotations

import os
from pathlib import Path

import yaml

from ..types import GuidanceStep, GuidanceVariant


def _guidance_dir() -> Path:
    env = os.environ.get("ATB_GUIDANCE_DIR")
    if env:
        return Path(env)
    return Path(__file__).parent


def load_guidance_yaml(filename: str) -> GuidanceStep:
    path = _guidance_dir() / filename
    if not path.exists():
        raise FileNotFoundError(f"guidance YAML not found: {path}")
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    step = data["step"]
    variants = {}
    for vid, vdata in (step.get("variants") or {}).items():
        variants[vid] = GuidanceVariant(label=vdata["label"], description=vdata["description"])
    return GuidanceStep(
        title=step["title"],
        default_description=step["default_description"],
        variant_label=step.get("variant_label", ""),
        variants=variants,
    )


__all__ = ["load_guidance_yaml"]
