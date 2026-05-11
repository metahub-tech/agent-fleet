from fleet.guidance import load_guidance_yaml
import pytest


def test_load_android_dev_options(tmp_path, monkeypatch):
    yaml_text = '''
step:
  title: "开启开发者选项"
  default_description: '设置 → 关于手机 → 连按"版本号" 7 次'
  variant_label: "Android 品牌"
  variants:
    huawei:
      label: "华为 / HarmonyOS / EMUI"
      description: '设置 → 关于手机 → 连按"版本号"'
    pixel:
      label: "Pixel / 原生 AOSP"
      description: 'Settings → About phone → tap "Build number" 7×'
'''
    f = tmp_path / "android_dev_options.yaml"
    f.write_text(yaml_text)
    monkeypatch.setenv("ATB_GUIDANCE_DIR", str(tmp_path))

    s = load_guidance_yaml("android_dev_options.yaml")
    assert s.title == "开启开发者选项"
    assert "版本号" in s.default_description
    assert s.variant_label == "Android 品牌"
    assert "huawei" in s.variants
    assert s.variants["huawei"].label == "华为 / HarmonyOS / EMUI"


def test_load_missing_file_raises(monkeypatch, tmp_path):
    monkeypatch.setenv("ATB_GUIDANCE_DIR", str(tmp_path))
    with pytest.raises(FileNotFoundError):
        load_guidance_yaml("does_not_exist.yaml")


def test_loader_populates_id_from_yaml_when_present(tmp_path, monkeypatch):
    yaml_text = '''
step:
  id: "some_perm"
  title: "Some title"
  default_description: "some description"
'''
    f = tmp_path / "with_id.yaml"
    f.write_text(yaml_text)
    monkeypatch.setenv("ATB_GUIDANCE_DIR", str(tmp_path))
    step = load_guidance_yaml("with_id.yaml")
    assert step.id == "some_perm"


def test_loader_id_defaults_to_empty_when_yaml_lacks_id_key(tmp_path, monkeypatch):
    """Backward-compat: YAMLs without an `id:` key must still load and yield
    an empty string for the id attribute, so callers can safely dispatch
    against the field without KeyError."""
    yaml_text = '''
step:
  title: "Some title"
  default_description: "no id key here"
'''
    f = tmp_path / "no_id.yaml"
    f.write_text(yaml_text)
    monkeypatch.setenv("ATB_GUIDANCE_DIR", str(tmp_path))
    step = load_guidance_yaml("no_id.yaml")
    assert step.id == ""
