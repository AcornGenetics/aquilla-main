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


def test_retains_deployment2_device_build():
    # Everything else from deployment2 is kept (spot-check across phases).
    for marker in ("I2C", "Tailscale", "aquila-cert-renew", "security.sh", "Plymouth"):
        assert marker in SCRIPT, f"deployment3 dropped a shared step: {marker}"
