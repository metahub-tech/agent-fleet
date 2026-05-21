import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # platforms/
from common._manifest import load_manifest, discover_manifests, PlatformManifest


def _write(tmp_path, pid, body):
    d = tmp_path / pid
    (d / "server").mkdir(parents=True)
    (d / "server" / "demo_mcp.py").write_text("# stub\n")
    toml = d / "platform.toml"
    toml.write_text(body)
    return toml


def test_loads_all_fields(tmp_path):
    toml = _write(tmp_path, "demo", textwrap.dedent('''
        [platform]
        id = "demo-device"
        display_name = "Demo"
        port = 8799
        status = "released"
        multi_device = true
        host_os = ["linux"]

        [server]
        module = "demo_mcp"

        [install]
        setup_script = "scripts/setup.sh"
        guidance = ["a.yaml", "b.yaml"]

        [tools.aliases]
        acquire = "acquire_demo"
        tap = "click"
    '''))
    m = load_manifest(toml)
    assert isinstance(m, PlatformManifest)
    assert m.id == "demo-device"
    assert m.port == 8799
    assert m.multi_device is True
    assert m.host_os == ["linux"]
    assert m.server_module == "demo_mcp"
    assert m.aliases == {"acquire": "acquire_demo", "tap": "click"}
    assert m.server_path.name == "demo_mcp.py"
    assert m.server_path.exists()
    assert m.dir == toml.parent


def test_defaults_for_optional_sections(tmp_path):
    toml = _write(tmp_path, "min", textwrap.dedent('''
        [platform]
        id = "min-device"
        display_name = "Min"
        port = 8798
        status = "beta"
        host_os = ["macos"]

        [server]
        module = "demo_mcp"
    '''))
    m = load_manifest(toml)
    assert m.multi_device is False
    assert m.aliases == {}
    assert m.guidance == []
    assert m.setup_script == ""


def test_discover_finds_manifests(tmp_path):
    _write(tmp_path, "aa", textwrap.dedent('''
        [platform]
        id = "aa-device"
        display_name = "aa"
        port = 8790
        status = "released"
        host_os = ["linux"]
        [server]
        module = "demo_mcp"
    '''))
    _write(tmp_path, "bb", textwrap.dedent('''
        [platform]
        id = "bb-device"
        display_name = "bb"
        port = 8791
        status = "released"
        host_os = ["linux"]
        [server]
        module = "demo_mcp"
    '''))
    ms = discover_manifests(tmp_path)
    assert {m.id for m in ms} == {"aa-device", "bb-device"}
