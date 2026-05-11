import pytest
from fleet.types import OSInfo
from fleet.installers.base import BaseInstaller


class DummyInstaller(BaseInstaller):
    role_id = "dummy"
    display_name = "Dummy"
    port = 9999

    def is_supported_on(self, os_info):
        return os_info.kind == "macos"

    def preflight(self):
        return []

    def install(self, ctx):
        yield "starting"

    def verify(self):
        from fleet.types import VerifyResult
        return VerifyResult(ok=True, tool_count=0)

    def guidance_steps(self):
        return []


def test_abstract_class_cannot_instantiate():
    with pytest.raises(TypeError):
        BaseInstaller()


def test_concrete_subclass_works():
    d = DummyInstaller()
    mac = OSInfo(system="Darwin", version="22", arch="x86_64", is_apple_silicon=False)
    win = OSInfo(system="Windows", version="11", arch="AMD64", is_apple_silicon=False)
    assert d.is_supported_on(mac)
    assert not d.is_supported_on(win)
