"""
Static structure checks for the Greengrass provisioning script
(deployment3_greengrass.sh, am#361).

Like the deployment2 tests, these read the shell script and assert its shape —
no device, no AWS. deployment3 is deployment2 with the watchtower/GHCR OTA path
swapped for Greengrass: same hardware/OS/Docker/kiosk setup, but Greengrass owns
image delivery and updates.

Run with:
    pytest tests/fleet_device/test_deployment3_greengrass_script.py -v
"""
from pathlib import Path

SCRIPT = Path("scripts/deploy/deployment3_greengrass.sh").read_text()


def test_installs_greengrass_nucleus():
    # Installs the Greengrass v2 nucleus in place (no reflash).
    assert "greengrass-nucleus" in SCRIPT
    assert "greengrass/v2" in SCRIPT


def test_provisions_with_existing_device_cert():
    # Manual provisioning — reuse the on-device acorn-ca cert, mint no new keys.
    assert "--provision false" in SCRIPT
    assert "certificateFilePath" in SCRIPT
    assert "/opt/aquila/config/device.crt" in SCRIPT
    assert "/opt/aquila/config/device.key" in SCRIPT


def test_configures_role_alias_region_and_holding_ring():
    assert "acorn-sentri-tes" in SCRIPT   # Token Exchange role alias (ECR pulls)
    assert "us-east-2" in SCRIPT
    assert "holding" in SCRIPT            # JITP lands the Thing here


def test_configures_iot_endpoints():
    # Manual provisioning must be told the account's IoT data + credential
    # endpoints — the Pi has no AWS creds to look them up itself.
    assert "iotDataEndpoint" in SCRIPT
    assert "iotCredEndpoint" in SCRIPT


def test_watchtower_ota_path_removed():
    # No Watchtower updater, no manual GHCR compose pull for delivery.
    assert "fleet-update.sh" not in SCRIPT
    assert "aquila-watchtower running" not in SCRIPT
    assert "RUNNING_IMAGE_DIGEST=$(docker inspect" not in SCRIPT


def test_no_host_compose_service_conflicts_with_greengrass():
    # The component owns the stack; the host must not also register a compose svc.
    assert "cat > /etc/systemd/system/aquila-stack.service" not in SCRIPT


def test_is_reversible():
    assert "--revert" in SCRIPT
    assert "rm -rf /greengrass/v2" in SCRIPT


def test_grants_ggc_user_docker_and_config_access():
    # The Greengrass component runs as ggc_user; without Docker-socket access +
    # readable device.env the component goes BROKEN ("permission denied").
    assert "usermod -aG docker ggc_user" in SCRIPT
    assert "chgrp ggc_group /opt/aquila/config/device.env" in SCRIPT


def test_no_meerstetter_tuning_in_provisioning():
    # Meerstetter first-time tuning needs the running app container (owned by the
    # Greengrass component), so it is not a provisioning-time step. Check the
    # tuning CODE is gone (not the word, which may appear in explanatory comments).
    assert "find_meer" not in SCRIPT
    assert "MeerStetter(" not in SCRIPT

    # No exec into the app *as a provisioning step*. Narrowed from a blanket
    # "docker exec" not in SCRIPT (#401): the cert-renew unit's ExecStart now execs
    # into the running backend, but that is a systemd unit written here and run
    # daily afterwards — not something provisioning does to a container.
    provisioning_execs = [
        line for line in SCRIPT.splitlines()
        if line.strip().startswith(("docker exec", "sudo docker exec"))
    ]
    assert not provisioning_execs, f"exec run during provisioning: {provisioning_execs}"


def test_retains_deployment2_device_build():
    # Everything else from deployment2 is kept (spot-check across phases).
    for marker in ("I2C", "Tailscale", "aquila-cert-renew", "security.sh", "Plymouth"):
        assert marker in SCRIPT, f"deployment3 dropped a shared step: {marker}"


# ── Certificate renewal (#401) ────────────────────────────────────────────────
# The renewal timer used to launch a throwaway container from a GHCR image. On a
# Greengrass device that tag is frozen at provisioning, the registry is the wrong
# one, and nothing holds the image — so any cleanup could delete it and renewal
# would fail silently until the certificate expired.


def _cert_renew_unit() -> str:
    """The aquila-cert-renew.service heredoc, as deployment3 writes it."""
    start = SCRIPT.index("cat > /etc/systemd/system/aquila-cert-renew.service")
    body = SCRIPT[SCRIPT.index("\n", start):]      # skip the heredoc opener line
    return body[:body.index("\nEOF")]


def test_cert_renewal_execs_into_the_running_backend():
    """No new container, so no image to keep alive and no registry to reach."""
    unit = _cert_renew_unit()

    assert "docker exec aquila-backend" in unit
    assert "docker run" not in unit


def test_cert_renewal_does_not_depend_on_a_registry():
    """A device that has migrated to ECR may no longer hold working GHCR
    credentials; the failure would be silent until the certificate expired."""
    unit = _cert_renew_unit()

    assert "ghcr.io" not in unit
    assert "IMAGE_TAG" not in unit


def test_cert_renewal_uses_the_backends_config_path():
    """Regression, and an easy one to get wrong: the old form bind-mounted
    /opt/aquila/config to /config inside a throwaway container. The backend has it
    at /opt/aquila/config, so carrying the old argument over would point the
    renewer at a directory that does not exist inside that container."""
    unit = _cert_renew_unit()

    assert "aq_lib.renew /opt/aquila/config" in unit
    assert "aq_lib.renew /config" not in unit


def test_cert_rotation_still_restarts_greengrass():
    """Greengrass holds a long-lived MQTT connection and won't pick up a renewed
    cert on its own (#363). The marker-driven restart must survive this change."""
    unit = _cert_renew_unit()

    assert ".cert-rotated" in unit
    assert "systemctl restart greengrass" in unit
