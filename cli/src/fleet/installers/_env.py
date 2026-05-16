"""Environment variables passed from the wizard to platform setup scripts.

The wizard captures all interactive choices (ADB mode, config reuse) up front
via questionary, then hands them to the setup scripts as env vars so the
scripts never block on Read-Host/read inside the wizard's piped stdout.

See docs/internal/specs/2026-05-14-wizard-zero-interaction-setup-scripts-design.md
"""
from __future__ import annotations

import os

from ..types import InstallContext


def setup_env(ctx: InstallContext, role_id: str) -> dict[str, str]:
    """Build the env dict for a setup-script subprocess.

    ATB_WIZARD_MANAGED=1 is always set so scripts skip every Read-Host/read
    pause point. android-device additionally gets the mode / reuse choice.
    Built on top of os.environ so PATH and friends survive.
    """
    env = {**os.environ, "ATB_WIZARD_MANAGED": "1"}
    if role_id == "android-device":
        if ctx.android_reuse_config:
            env["ATB_ANDROID_REUSE_CONFIG"] = "1"
        elif ctx.android_mode:
            env["ATB_ANDROID_MODE"] = ctx.android_mode
    return env
