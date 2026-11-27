"""测试夹具保真度：CDP 错误对象必须带 `message`。

为什么需要这条"测测试"的用例：实现里 `classify_eval_error` 与
`should_retry_activation` 都会读 `error["message"]` 来区分
「真超时（`… timed out`）」与「链路故障（`send failed` / `recv failed`）」。
若夹具只写 `{"reason": "cdp_timeout"}`，两种失败就**无法区分**，错误实现会被验成对的
——这事在同一个文件里连续发生过三次（`choose_target` 夹具、`classify_eval_error`、
`should_retry_activation`）。

因此：测试里构造 CDP 错误时，必须带上真实文案形态的 `message`。
确有必要构造"无 message"的极端输入时，在该行加 `# noqa: fixture-no-message` 并写明原因。
"""
from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
TEST_DIRS = [
    REPO / "platforms" / "common" / "tests",
    REPO / "platforms" / "tests",
    REPO / "scripts" / "tests",
]

#: `{"reason": "cdp_timeout"}` 这种"只有 reason"的字面量
BARE_REASON = re.compile(r'\{\s*"reason"\s*:\s*"(cdp_timeout|cdp_error)"\s*[,}]')
NOQA = "fixture-no-message"


SELF = pathlib.Path(__file__).resolve()


def _iter_test_files():
    for directory in TEST_DIRS:
        for path in sorted(directory.glob("test_*.py")):
            if path.resolve() == SELF:      # 别扫自己：本文件的说明文字里就有这个字面量
                continue
            yield path


def test_cdp_error_fixtures_carry_a_message():
    offenders = []
    for path in _iter_test_files():
        lines = path.read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines):
            stripped = line.strip()
            previous = lines[index - 1] if index else ""
            if stripped.startswith("#") or NOQA in line or NOQA in previous:
                continue
            if not BARE_REASON.search(line):
                continue
            # 同一个 dict 里的 `"message"` 可能写在后续几行（多行字面量），一起看
            window = "\n".join(lines[index:index + 4])
            if '"message"' in window:
                continue
            offenders.append(f"{path.relative_to(REPO)}:{index + 1}: {line.strip()[:90]}")
    assert not offenders, (
        "这些夹具的 CDP 错误只有 reason、没有 message —— 实现无法区分"
        "「真超时」与「链路故障」，会把错误实现验成对的：\n  " + "\n  ".join(offenders)
    )
