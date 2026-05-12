import platform
from unittest.mock import patch
from fleet.detect import detect_os, detect_uv, detect_tailscale


@patch("platform.system", return_value="Darwin")
@patch("platform.release", return_value="22.0.0")
@patch("platform.machine", return_value="x86_64")
def test_detect_os_macos(m1, m2, m3):
    o = detect_os()
    assert o.kind == "macos"
    assert o.arch == "x86_64"
    assert o.is_apple_silicon is False


@patch("platform.system", return_value="Darwin")
@patch("platform.release", return_value="23.0.0")
@patch("platform.machine", return_value="arm64")
def test_detect_os_apple_silicon(m1, m2, m3):
    o = detect_os()
    assert o.is_apple_silicon is True


@patch("shutil.which", return_value="/usr/local/bin/uv")
def test_detect_uv_present(m):
    found = detect_uv()
    assert found is not None
    assert "uv" in found


@patch("shutil.which", return_value=None)
def test_detect_uv_absent(m):
    found = detect_uv()
    assert found is None


@patch("subprocess.run")
def test_detect_tailscale_logged_in(mock_run):
    class R:
        returncode = 0
        stdout = '{"Self": {"HostName": "mac-test", "DNSName": "mac-test.tailb15936.ts.net."}}'
    mock_run.return_value = R()
    ts = detect_tailscale()
    assert ts is not None
    assert ts.hostname == "mac-test"


@patch("subprocess.run", side_effect=FileNotFoundError)
def test_detect_tailscale_missing(mock_run):
    assert detect_tailscale() is None


@patch("subprocess.run")
def test_detect_tailscale_handles_none_stdout_gracefully(mock_run):
    """Regression for v0.6.7 Chinese-Windows crash: when subprocess's reader
    thread dies on UnicodeDecodeError (GBK can't decode UTF-8 bytes from
    Tailscale JSON), `r.stdout` becomes None and the old `r.stdout.strip()`
    raised `AttributeError: 'NoneType' object has no attribute 'strip'`.
    The fixed code must short-circuit to None instead of crashing."""
    class R:
        returncode = 0
        stdout = None  # simulate post-encoding-crash state
    mock_run.return_value = R()
    assert detect_tailscale() is None


@patch("subprocess.run")
def test_detect_tailscale_prefers_dnsname_over_hostname(mock_run):
    """Regression: when HostName is the non-routable OS computer name (spaces,
    non-ASCII) but DNSName has the admin-assigned routable Tailscale name as
    its first label, use the DNSName label.  Empirical case: a Mac with OS
    HostName "Yi的MacBook Pro" but Tailscale name "test-macpro-12"."""
    class R:
        returncode = 0
        stdout = (
            '{"Self": {"HostName": "Yi的MacBook Pro", '
            '"DNSName": "test-macpro-12.tail-XXXXX.ts.net."}}'
        )
    mock_run.return_value = R()
    ts = detect_tailscale()
    assert ts is not None
    assert ts.hostname == "test-macpro-12"
    assert ts.fqdn == "test-macpro-12.tail-XXXXX.ts.net"
