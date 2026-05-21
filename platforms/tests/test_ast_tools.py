import sys, textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _ast_tools import extract_mcp_tools


def test_extracts_bare_and_called_decorator(tmp_path):
    src = textwrap.dedent('''
        @mcp.tool
        def tap(x, y, device=None, ctx=None): ...

        @mcp.tool()
        def type_text(text, device=None): ...

        def not_a_tool(z): ...
    ''')
    f = tmp_path / "s.py"; f.write_text(src)
    tools = extract_mcp_tools(f)
    assert set(tools) == {"tap", "type_text"}
    assert tools["tap"] == ["x", "y", "device", "ctx"]
    assert tools["type_text"] == ["text", "device"]
