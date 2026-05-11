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


def test_loader_populates_id_from_yaml():
    from fleet.guidance import load_guidance_yaml
    # macos_accessibility.yaml is updated to have id: "macos_accessibility"
    step = load_guidance_yaml("macos_accessibility.yaml")
    assert step.id == "macos_accessibility"


def test_loader_id_defaults_to_empty_when_yaml_missing():
    """Backward-compat: YAMLs that haven't been migrated yet (android, windows)
    must still load and just return an empty string for id."""
    from fleet.guidance import load_guidance_yaml
    # android_dev_options.yaml has not been migrated to have an `id:` field
    step = load_guidance_yaml("android_dev_options.yaml")
    assert step.id == ""
