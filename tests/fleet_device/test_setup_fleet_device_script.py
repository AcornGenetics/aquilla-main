from pathlib import Path


def test_setup_fleet_device_copies_config() -> None:
    script_text = Path("scripts/setup_fleet_device.sh").read_text()

    assert "fleet-config/docker-compose.yml" in script_text
    assert "fleet-config/vmagent.yaml" in script_text
    assert "fleet-config/vector.yaml" in script_text
    assert "config_files/device.env" in script_text
    assert "config_files/grafana.env" in script_text


def test_setup_fleet_device_generates_watchtower_token() -> None:
    script_text = Path("scripts/setup_fleet_device.sh").read_text()

    assert "openssl rand -hex 32" in script_text
    assert "WATCHTOWER_HTTP_API_TOKEN" in script_text


def test_setup_fleet_device_starts_compose() -> None:
    script_text = Path("scripts/setup_fleet_device.sh").read_text()

    assert "docker compose" in script_text
    assert "/opt/fleet/docker-compose.yml" in script_text


def test_ring_setup_scripts_exist() -> None:
    assert Path("scripts/setup/device_dev.sh").exists()
    assert Path("scripts/setup/device_pilot.sh").exists()
    assert Path("scripts/setup/device_prod.sh").exists()
