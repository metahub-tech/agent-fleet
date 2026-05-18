import json
import os
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DeviceInfo:
    serial: str
    brand: str | None
    model: str | None


def derive_alias(brand: str | None, model: str | None) -> str | None:
    if not brand or not model:
        return None
    raw = f"{brand}-{model}"
    slug = raw.lower()
    slug = re.sub(r"[_\s]+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    slug = slug.strip("-")
    return slug if slug else None


def assign_aliases(devices: list[DeviceInfo]) -> dict[str, str]:
    if not devices:
        return {}

    sorted_devices = sorted(devices, key=lambda d: d.serial)

    base_map: dict[str, list[str]] = {}
    fallback_serials: list[str] = []

    for d in sorted_devices:
        base = derive_alias(d.brand, d.model)
        if base is None:
            fallback_serials.append(d.serial)
        else:
            base_map.setdefault(base, []).append(d.serial)

    result: dict[str, str] = {}

    for base, serials in base_map.items():
        if len(serials) == 1:
            result[serials[0]] = base
        else:
            for i, serial in enumerate(serials, start=1):
                result[serial] = f"{base}-{i}"

    for i, serial in enumerate(fallback_serials, start=1):
        result[serial] = f"phone-{i}"

    return result


def load_aliases(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Malformed JSON in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"Expected a JSON object in {path}, got {type(data).__name__}")
    for k, v in data.items():
        if not isinstance(v, str):
            raise ValueError(
                f"All values must be strings in {path}; key {k!r} has type {type(v).__name__}"
            )
    return data


def save_aliases(path: Path, aliases: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    content = json.dumps(aliases, indent=2, sort_keys=True) + "\n"
    tmp_path.write_text(content, encoding="utf-8")
    os.replace(tmp_path, path)


def resolve_aliases(devices: list[DeviceInfo], overrides: dict[str, str]) -> dict[str, str]:
    if not devices:
        return {}

    device_serials = {d.serial for d in devices}
    valid_overrides = {s: a for s, a in overrides.items() if s in device_serials and a}

    non_overridden = [d for d in devices if d.serial not in valid_overrides]
    base_result = assign_aliases(non_overridden)

    result = {}
    for d in devices:
        if d.serial in valid_overrides:
            result[d.serial] = valid_overrides[d.serial]
        else:
            result[d.serial] = base_result[d.serial]

    return result
