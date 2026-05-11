import socket
from unittest.mock import patch, MagicMock
from fleet.verify import probe_port_open, probe_mcp_server


def test_probe_port_open_localhost_closed():
    # Port that is definitely not in use
    assert probe_port_open("127.0.0.1", 1) is False


@patch("socket.socket")
def test_probe_port_open_yes(mock_sock_cls):
    s = MagicMock()
    s.connect_ex.return_value = 0
    mock_sock_cls.return_value = s
    assert probe_port_open("host", 8767) is True


@patch("socket.socket")
def test_probe_mcp_server_port_closed_returns_fail(mock_sock_cls):
    s = MagicMock()
    s.connect_ex.return_value = 1
    mock_sock_cls.return_value = s
    r = probe_mcp_server("host", 8767)
    assert r.ok is False
    assert "not listening" in (r.error or "").lower()
