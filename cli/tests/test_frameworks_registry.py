from fleet.frameworks import FRAMEWORK_REGISTRY


def test_six_frameworks_registered():
    ids = {fw.framework_id for fw in FRAMEWORK_REGISTRY}
    assert ids == {"claude-code", "cursor", "cline", "openclaw", "antigravity", "hermes"}


def test_each_has_display_name_and_path():
    for fw in FRAMEWORK_REGISTRY:
        assert fw.display_name
        assert fw.config_path_template
