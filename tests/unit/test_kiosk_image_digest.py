"""Unit tests for kiosk-control's running-image digest lookup (failed-update detection).

The real lookup shells out to `docker inspect` on the Pi host (hardware/host-only),
but the parsing logic is testable with subprocess mocked — no docker required.
See specs/backend/spec_ota_update_failed_detection.md.
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


def test_image_digest_parses_sha_from_repodigests():
    kc = _load_kiosk_control()
    with mock.patch.object(kc.subprocess, "run") as run:
        run.side_effect = [
            mock.Mock(returncode=0, stdout="sha256:imageid\n"),  # {{.Image}}
            mock.Mock(returncode=0, stdout="ghcr.io/acorn/aquilla-main-api@sha256:abc123\n"),
        ]
        digest = kc._image_digest("aquila-backend")
    assert digest == "sha256:abc123"


def test_image_digest_returns_none_on_docker_error():
    kc = _load_kiosk_control()
    with mock.patch.object(kc.subprocess, "run") as run:
        run.return_value = mock.Mock(returncode=1, stdout="")
        assert kc._image_digest("aquila-backend") is None
