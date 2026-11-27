"""`_clipboard` 策略层单测：句柄所有权、失败路径 free、关闭时机、整轮重试。

用假后端把 Win32 的三条坑变成可断言的判据（真机只需验证 API 名字没写错）：
1. Set 成功 ⇒ **绝不** GlobalFree；
2. Set 失败 ⇒ 必须 GlobalFree（否则每次 clipboard_busy 漏一块）；
3. Close 只在 Open 成功后调用；
4. 重试是**整轮重来**（重新 alloc，不复用上一轮失败的句柄）。
"""
from _clipboard import read_clipboard_html, set_clipboard_html
from _cf_html import CLIPBOARD_FORMAT, build_cf_html


class FakeApi:
    def __init__(self, *, opens=(True,), empty=True, alloc=True, lock=True,
                 set_ok=(True,), formats=None, data=b"", size=None, get_handle=2000):
        self._opens = list(opens)
        self._empty = empty
        self._alloc = alloc
        self._lock = lock
        self._set_ok = list(set_ok)
        self._formats = formats if formats is not None else [CLIPBOARD_FORMAT]
        self._data = data
        self._size = size
        self._get_handle = get_handle
        self.calls: list[str] = []
        self.freed: list[int] = []
        self.closed = 0
        self.alloc_count = 0
        self.error = 5  # ERROR_ACCESS_DENIED

    # lifecycle
    def open_clipboard(self):
        self.calls.append("open")
        return self._opens.pop(0) if self._opens else False

    def close_clipboard(self):
        self.calls.append("close")
        self.closed += 1

    def empty_clipboard(self):
        self.calls.append("empty")
        return self._empty

    def last_error(self):
        return self.error

    def register_format(self, name):
        self.calls.append(f"register:{name}")
        return 49348  # 任意非零 id

    def format_names(self):
        return list(self._formats)

    # memory
    def global_alloc(self, size):
        self.calls.append(f"alloc:{size}")
        self.alloc_count += 1
        return self._alloc and 1000 + self.alloc_count

    def global_lock(self, handle):
        self.calls.append(f"lock:{handle}")
        return self._lock and 0x5000

    def global_unlock(self, handle):
        self.calls.append(f"unlock:{handle}")

    def global_free(self, handle):
        self.calls.append(f"free:{handle}")
        self.freed.append(handle)

    def global_size(self, handle):
        return self._size if self._size is not None else len(self._data)

    def write_memory(self, ptr, data):
        self.calls.append(f"write:{len(data)}")

    def read_memory(self, ptr, size):
        return self._data

    def set_clipboard_data(self, fmt, handle):
        self.calls.append(f"set:{fmt}:{handle}")
        return self._set_ok.pop(0) if self._set_ok else False

    def get_clipboard_data(self, fmt):
        self.calls.append(f"get:{fmt}")
        return self._get_handle


def test_success_transfers_ownership_and_does_not_free():
    api = FakeApi()
    payload = build_cf_html("<p>hi</p>")
    result = set_clipboard_html(payload, api=api)
    assert result["ok"] is True and result["attempts"] == 1
    assert api.freed == []                      # 所有权已转移，绝不能 free
    assert api.closed == 1                      # Open 成功 ⇒ Close 一次
    assert any(c.startswith("set:") for c in api.calls)
    set_idx = next(i for i, c in enumerate(api.calls) if c.startswith("set:"))
    assert api.calls.index("open") < api.calls.index("empty") < set_idx


def test_failed_set_frees_the_handle():
    api = FakeApi(set_ok=[False])
    result = set_clipboard_html(build_cf_html("<p>x</p>"), api=api)
    assert result["ok"] is False and result["reason"] == "clipboard_write_failed"
    assert len(api.freed) == 1                  # 失败路径必须回收，否则漏内存
    assert api.closed == 1


def test_busy_clipboard_does_not_close_unopened():
    api = FakeApi(opens=[False])
    result = set_clipboard_html(build_cf_html("<p>x</p>"), api=api)
    assert result["ok"] is False and result["reason"] == "clipboard_busy"
    assert api.closed == 0                      # 没 Open 就不能 Close
    assert api.freed == []


def test_retry_is_a_fresh_round():
    api = FakeApi(opens=[False, True], set_ok=[True])
    result = set_clipboard_html(build_cf_html("<p>x</p>"), attempts=2, retry_delay_s=0, api=api)
    assert result["ok"] is True and result["attempts"] == 2
    assert api.alloc_count == 1                 # 第一轮没开成功，不该 alloc
    assert result["attempts_detail"][0]["reason"] == "clipboard_busy"
    assert result["attempts_detail"][0]["winerror"] == 5


def test_retry_reallocs_after_failed_set():
    api = FakeApi(opens=[True, True], set_ok=[False, True])
    result = set_clipboard_html(build_cf_html("<p>x</p>"), attempts=2, retry_delay_s=0, api=api)
    assert result["ok"] is True and api.alloc_count == 2   # 每轮重新 alloc
    assert len(api.freed) == 1                              # 只有失败那轮被 free
    assert api.closed == 2                                   # 每轮都关了


def test_alloc_and_lock_failures_are_classified():
    assert set_clipboard_html(b"x", api=FakeApi(alloc=False))["reason"] == "clipboard_alloc_failed"
    assert set_clipboard_html(b"x", api=FakeApi(lock=False))["reason"] == "clipboard_lock_failed"


def test_exhausted_attempts_reports_detail():
    api = FakeApi(opens=[False, False], set_ok=[True])
    result = set_clipboard_html(b"x", attempts=2, retry_delay_s=0, api=api)
    assert result["ok"] is False and result["attempts"] == 2
    assert len(result["attempts_detail"]) == 2


# --- 读回 -----------------------------------------------------------------

def test_read_returns_formats_and_bytes():
    payload = build_cf_html("<p>中文</p>")
    api = FakeApi(data=payload, formats=[CLIPBOARD_FORMAT])
    result = read_clipboard_html(api=api)
    assert result["ok"] is True and result["data"] == payload
    assert result["formats"] == [CLIPBOARD_FORMAT]
    assert api.closed == 1


def test_read_reports_extra_formats_for_the_negative_test():
    api = FakeApi(data=b"", formats=["CF_UNICODETEXT", CLIPBOARD_FORMAT])
    result = read_clipboard_html(api=api)
    assert result["formats"] == ["CF_UNICODETEXT", CLIPBOARD_FORMAT]


def test_read_without_html_format():
    api = FakeApi(formats=["CF_UNICODETEXT"], get_handle=0)
    result = read_clipboard_html(api=api)
    assert result["ok"] is False and result["reason"] == "no_html_format"
    assert result["formats"] == ["CF_UNICODETEXT"]
    assert api.closed == 1


def test_read_busy():
    api = FakeApi(opens=[False])
    result = read_clipboard_html(api=api)
    assert result["ok"] is False and result["reason"] == "clipboard_busy"
    assert api.closed == 0

def test_retry_actually_waits_between_attempts():
    """回归：失败路径用 continue 会跳过 sleep，重试等于空转（实测曾如此）。"""
    slept: list[float] = []
    api = FakeApi(opens=[False, False, True], set_ok=[True])
    result = set_clipboard_html(build_cf_html("<p>x</p>"), attempts=3,
                                retry_delay_s=0.25, api=api, sleep=slept.append)
    assert result["ok"] is True and result["attempts"] == 3
    assert slept == [0.25, 0.25]          # 两轮失败 → 两次间隔；成功那轮之后不再睡


def test_no_sleep_after_last_attempt():
    slept: list[float] = []
    api = FakeApi(opens=[False, False])
    result = set_clipboard_html(b"x", attempts=2, retry_delay_s=0.5,
                                api=api, sleep=slept.append)
    assert result["ok"] is False
    assert slept == [0.5]                 # 只有第一次失败后睡，最后一轮之后不睡
