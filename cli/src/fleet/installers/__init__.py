"""Per-(OS, role) installers."""
from .base import BaseInstaller
from .macos import MacosDesktop, MacosAndroidBridge
from .windows import WindowsDesktop, WindowsDesktop, WindowsAndroidBridge
from .linux import LinuxAndroidBridge
from ..types import OSInfo


INSTALLER_REGISTRY: list[BaseInstaller] = [
    MacosDesktop(),
    MacosAndroidBridge(),
    WindowsDesktop(),
    WindowsAndroidBridge(),
    LinuxAndroidBridge(),
]


def filter_for_os(os_info: OSInfo) -> list[BaseInstaller]:
    return [i for i in INSTALLER_REGISTRY if i.is_supported_on(os_info)]


__all__ = [
    "BaseInstaller", "INSTALLER_REGISTRY", "filter_for_os",
    "MacosDesktop", "MacosAndroidBridge",
    "WindowsDesktop", "WindowsDesktop", "WindowsAndroidBridge",
    "LinuxAndroidBridge",
]
