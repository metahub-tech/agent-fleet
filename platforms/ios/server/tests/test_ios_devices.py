import sys
from pathlib import Path

_here = Path(__file__).resolve()
sys.path.insert(0, str(_here.parent.parent))                       # platforms/ios/server
sys.path.insert(0, str(_here.parent.parent.parent.parent / "common"))  # platforms/common

import _ios_devices as iod


def test_detect_parses_maps_and_sorts(monkeypatch):
    # Mirrors `pymobiledevice3 usbmux list` parsed JSON. Second entry exercises the
    # UniqueDeviceID-missing -> Identifier fallback in _udid_of().
    monkeypatch.setattr(iod, "_usbmux_list", lambda: [
        {"UniqueDeviceID": "00008120-BBB", "ProductType": "iPad15,7", "DeviceName": "iPad"},
        {"Identifier": "00008020-AAA", "ProductType": "iPhone11,8", "DeviceName": "iPhone"},
    ])
    devices = iod.detect_ios_devices()
    assert [d.serial for d in devices] == ["00008020-AAA", "00008120-BBB"]  # sorted by serial
    assert all(d.brand == "apple" for d in devices)
    assert devices[0].model == "iPhone11,8"
    assert devices[1].model == "iPad15,7"
