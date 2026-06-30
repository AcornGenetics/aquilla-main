"""Unit test for kiosk-control's host-reboot helper (issue #183).

The endpoint itself drives a real `systemctl reboot` on the Pi (hardware), but the
command-construction logic is testable with subprocess mocked — no real reboot.
"""
import importlib.util
import pathlib
from unittest import mock

_KC_PATH = (
    pathlib.Path(__file__).resolve().parents[2]
    / "scripts" / "kiosk-control" / "kiosk_control.py"
)


def _load_kiosk_control():
    spec = importlib.util.spec_from_file_location("kiosk_control", _KC_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_reboot_host_invokes_systemctl_reboot():
    kc = _load_kiosk_control()
    with mock.patch.object(kc.subprocess, "run") as run:
        run.return_value = mock.Mock(returncode=0)
        ok, msg = kc._reboot_host()
    assert ok is True
    run.assert_called_once_with(["systemctl", "reboot"], capture_output=True)


def test_reboot_host_falls_back_to_sudo_when_systemctl_fails():
    kc = _load_kiosk_control()
    with mock.patch.object(kc.subprocess, "run") as run:
        run.side_effect = [mock.Mock(returncode=1), mock.Mock(returncode=0)]
        ok, _ = kc._reboot_host()
    assert ok is True
    assert run.call_args_list[1][0][0] == ["sudo", "reboot"]
