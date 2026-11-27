"""`_mcp_transport` 的兼容性单测（MCP SDK 1.x 用 streamablehttp_client，2.x 用 streamable_http_client）。"""
from fleet._mcp_transport import load_transport, require_transport


def test_load_transport_prefers_something_callable():
    transport = load_transport()
    assert transport is not None, "测试环境应至少装有一个 MCP SDK 版本"
    assert callable(transport)


def test_require_transport_matches_load_transport():
    assert require_transport() is load_transport()


def test_require_transport_raises_with_install_hint(monkeypatch):
    import fleet._mcp_transport as mod

    monkeypatch.setattr(mod, "load_transport", lambda: None)
    try:
        mod.require_transport()
    except RuntimeError as exc:
        assert "mcp" in str(exc).lower()
    else:  # pragma: no cover
        raise AssertionError("应当抛 RuntimeError")
