import re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from capabilities.human_dom._ident import human_dom_profile_id

def test_empty_is_default():
    assert human_dom_profile_id("") == "default"
    assert human_dom_profile_id("   ") == "default"
    assert human_dom_profile_id(None) == "default"

def test_filesystem_safe_and_idempotent():
    a = human_dom_profile_id("~/.fleet/wechat-pub")
    assert a == human_dom_profile_id("~/.fleet/wechat-pub")
    assert re.fullmatch(r"[a-z0-9-]+", a)
    assert a.startswith("wechat-pub-")

def test_distinct_profiles_distinct_id():
    assert human_dom_profile_id("~/.fleet/a") != human_dom_profile_id("~/.fleet/b")

def test_profile_directory_dimension_distinct():
    # 同一 user-data-dir, 不同 dir@Name (profile_directory) 也必须区分。
    work = human_dom_profile_id("~/.fleet/x@Work")
    personal = human_dom_profile_id("~/.fleet/x@Personal")
    assert work != personal
    assert work.startswith("x-") and personal.startswith("x-")

def test_unsluggable_basename_still_safe():
    # basename 全是非 [a-z0-9] 字符时, slug 兜底为 "p", 仍满足文件系统安全。
    pid = human_dom_profile_id("~/.fleet/____")
    assert re.fullmatch(r"[a-z0-9-]+", pid)
    assert pid.startswith("p-")
