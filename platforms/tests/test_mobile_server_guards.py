"""移动端 server（android / ios）的静态契约测试（无法在 Linux 导入）。

两个 server 都依赖 adb / WDA 之类的运行时，Linux 上导入即失败；而它们的
`run_actions` / `wait_for` **没有任何真机执行记录**。这里用 AST 守住三件最容易
静默退化的事：

1. **ctx 注入**：移动端靠 `ctx` 取"会话级默认设备"。`run_actions` 调的是内层函数，
   FastMCP 不会替它们注入 ctx —— 丢了就会出现"set_default_device 设了但批量/等待里
   用不上"，单设备碰巧能用、多设备直接解析失败（且不报错，只是一直等到超时）；
2. **白名单**：`run_shell` / 安装 / 上传类工具不该被批处理；
3. **`*_gone`**：`wait_for` 的"等条件消失"能力不能静默丢。
"""
from __future__ import annotations

import ast
import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
SERVERS = {
    "android": REPO / "platforms" / "android" / "server" / "android_device_mcp.py",
    "ios": REPO / "platforms" / "ios" / "server" / "ios_device_mcp.py",
}
#: 各平台 batch 白名单里**不允许**出现的工具
FORBIDDEN_IN_BATCH = {
    "android": {"run_shell", "install_app", "uninstall_app", "upload_media",
                "stage_upload", "deliver_staged"},
    "ios": {"install_app", "uninstall_app", "upload_to_photos", "upload_to_app", "push_file_to_app"},
}


@pytest.fixture(scope="module", params=sorted(SERVERS))
def parsed(request):
    platform = request.param
    tree = ast.parse(SERVERS[platform].read_text(encoding="utf-8"))
    return platform, tree


def _func(tree: ast.Module, name: str) -> ast.FunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name}() not found")


def _calls(node: ast.AST) -> list[ast.Call]:
    return [n for n in ast.walk(node) if isinstance(n, ast.Call)]


def _called_names(node: ast.AST) -> set[str]:
    names = set()
    for call in _calls(node):
        func = call.func
        if isinstance(func, ast.Name):
            names.add(func.id)
        elif isinstance(func, ast.Attribute):
            names.add(func.attr)
    return names


def test_batch_registry_injects_ctx(parsed):
    platform, tree = parsed
    func = _func(tree, "_batch_registry")
    assert "make_caller" in _called_names(func), (
        f"{platform}: 批量执行没有走 _batch.make_caller —— ctx 会丢失，"
        "多设备场景下 set_default_device 静默失效"
    )
    source = ast.unparse(func)
    assert "ctx" in source, f"{platform}: _batch_registry 不再接收 ctx"


def test_run_actions_passes_ctx_to_registry(parsed):
    platform, tree = parsed
    func = _func(tree, "run_actions")
    registry_calls = [c for c in _calls(func)
                      if isinstance(c.func, ast.Name) and c.func.id == "_batch_registry"]
    assert registry_calls, f"{platform}: run_actions 没有调用 _batch_registry"
    assert any(ast.unparse(arg) == "ctx" for call in registry_calls for arg in call.args), (
        f"{platform}: run_actions 调 _batch_registry 时没有把 ctx 传下去"
    )


def test_wait_for_honours_session_default_device(parsed):
    """`wait_for` 不许丢掉"会话级默认设备"。

    两个平台的实现方式不同，但都要求同一条不变量：
    * android：进入 `wait_for` 先 `_resolve_device(device, _get_session_default(ctx))`
      解析出 serial，探测统一用它（比逐探测传 ctx 更省）；
    * ios：两个探测（text / app）各自把 ctx 传下去。

    判定方式：要么出现 `_get_session_default(ctx)`，要么两个探测都带 ctx。
    """
    platform, tree = parsed
    func = _func(tree, "wait_for")
    source = ast.unparse(func)
    ctx_kwargs = [kw for call in _calls(func) for kw in call.keywords if kw.arg == "ctx"]

    if "_get_session_default" in source:
        return                       # android：已显式解析会话默认设备
    assert len(ctx_kwargs) >= 2, (
        f"{platform}: wait_for 既没有解析会话默认设备，也没有让两个探测都带 ctx —— "
        "set_default_device 会静默失效"
    )


def test_wait_for_keeps_gone_variant(parsed):
    platform, tree = parsed
    func = _func(tree, "wait_for")
    assert "negate_probe" in _called_names(func), f"{platform}: *_gone 能力被移除"
    assert "_gone" in ast.unparse(func), f"{platform}: allowed_kinds 不再包含 *_gone"


def test_batch_allowlist_has_no_dangerous_tools(parsed):
    platform, tree = parsed
    name = "_ANDROID_BATCH_ALLOWLIST" if platform == "android" else "_IOS_BATCH_ALLOWLIST"
    allowlist = None
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == name for t in node.targets
        ):
            allowlist = [e.value for e in node.value.elts if isinstance(e, ast.Constant)]
    assert allowlist, f"{name} 不存在"
    leaked = set(allowlist) & FORBIDDEN_IN_BATCH[platform]
    assert not leaked, f"{platform}: 白名单混入了不该批处理的工具 {leaked}"


def test_android_wait_for_resolves_device_once(parsed):
    """android 的 wait_for 必须**先解析** serial，再拿它调用探测（不再逐探测传 device）。"""
    platform, tree = parsed
    if platform != "android":
        pytest.skip("android 专属")
    func = _func(tree, "wait_for")
    names = _called_names(func)
    assert "_resolve_device" in names, "wait_for 没有解析目标设备"
    assert "_get_session_default" in names, "解析时没有带上会话默认设备"
