from pathlib import Path


def test_update_script_has_watchtower_support() -> None:
    script_text = Path("update.sh").read_text()

    assert "WATCHTOWER_ENABLE" in script_text
    assert "WATCHTOWER_INTERVAL" in script_text
    assert "containrrr/watchtower" in script_text


def test_deployment1_script_has_docker_support() -> None:
    script_text = Path("deployment1.sh").read_text()

    assert "INSTALL_DOCKER" in script_text
    assert "curl -fsSL https://get.docker.com" in script_text
    assert "docker-compose-plugin" in script_text
