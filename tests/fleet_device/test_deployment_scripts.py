from pathlib import Path


def test_update_script_has_watchtower_support() -> None:
    script_text = Path("scripts/deploy/update.sh").read_text()

    assert "WATCHTOWER_ENABLE" in script_text
    assert "WATCHTOWER_INTERVAL" in script_text
    assert "containrrr/watchtower" in script_text


def test_update_script_does_not_silently_ignore_wifi_apply_failures() -> None:
    script_text = Path("scripts/deploy/update.sh").read_text()

    assert "Skipping Wi-Fi config" in script_text
    assert "WARNING: Wi-Fi config apply failed" in script_text
    assert 'scripts/apply_wifi.py" || true' not in script_text


def test_deployment1_script_has_docker_support() -> None:
    script_text = Path("scripts/deploy/deployment1.sh").read_text()

    assert "INSTALL_DOCKER" in script_text
    assert "curl -fsSL https://get.docker.com" in script_text
    assert "docker-compose-plugin" in script_text


def test_deployment2_locks_down_device_env() -> None:
    script_text = Path("scripts/deploy/deployment2.sh").read_text()

    assert "chown root:root /opt/aquila/config/device.env" in script_text
    assert "chmod 600 /opt/aquila/config/device.env" in script_text


def test_kiosk_control_installer_installs_python_entrypoint() -> None:
    script_text = Path("scripts/kiosk-control/install.sh").read_text()
    service_text = Path("scripts/kiosk-control/kiosk-control.service").read_text()

    assert "/usr/local/bin/kiosk_control.py" in service_text
    assert "/usr/local/bin/kiosk_control.py" in script_text
    assert "kiosk_control.py" in script_text
    assert "chmod +x" in script_text


def test_kiosk_control_update_script_supports_repo_less_devices() -> None:
    script_text = Path("scripts/kiosk-control/update_host_service.sh").read_text()

    assert "raw.githubusercontent.com/AcornGenetics/aquilla-main" in script_text
    assert "BRANCH=" in script_text
    assert "kiosk_control.py" in script_text
    assert "kiosk-control.service" in script_text
    assert "/wifi/status" in script_text
    assert "/wifi/scan" in script_text
