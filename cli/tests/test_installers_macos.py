from unittest.mock import patch, MagicMock
from fleet.installers.macos import MacosDesktop
from fleet.types import OSInfo, InstallContext


def test_macos_desktop_supported_only_on_macos():
    m = MacosDesktop()
    assert m.is_supported_on(OSInfo(system="Darwin", version="22", arch="x86_64", is_apple_silicon=False))
    assert not m.is_supported_on(OSInfo(system="Windows", version="11", arch="AMD64", is_apple_silicon=False))
    assert not m.is_supported_on(OSInfo(system="Linux", version="6.5", arch="x86_64", is_apple_silicon=False))


def test_macos_desktop_metadata():
    m = MacosDesktop()
    assert m.role_id == "macbox-gui"
    assert m.port == 8767


def test_install_dry_run_skips_subprocess():
    m = MacosDesktop()
    ctx = InstallContext(
        repo_root="/tmp/repo",
        os_info=OSInfo(system="Darwin", version="22", arch="x86_64", is_apple_silicon=False),
        dry_run=True,
    )
    with patch("subprocess.Popen") as mock_popen:
        list(m.install(ctx))
        assert not mock_popen.called
