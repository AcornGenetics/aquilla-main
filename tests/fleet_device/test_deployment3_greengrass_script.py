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
import re
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


def test_pins_greengrass_dataplane_endpoint_to_account_endpoint():
    # Manual provisioning must pin the Greengrass data-plane endpoint to the
    # account's IoT data endpoint. Left unset, the nucleus SDK defaults to the
    # shared greengrass-ats.iot.<region>.amazonaws.com endpoint, which completes
    # mTLS then refuses this device (closes with no HTTP response) -- so every
    # deployment wedges at ListThingGroupsForCoreDevice, IN_PROGRESS forever
    # (#442; regressed by a re-provision that regenerated nucleus config).
    data_ep = re.search(r'iotDataEndpoint:\s*"([^"]+)"', SCRIPT)
    dp_ep = re.search(r'greengrassDataPlaneEndpoint:\s*"([^"]*)"', SCRIPT)
    assert dp_ep is not None, "greengrassDataPlaneEndpoint is not set in the nucleus config"
    assert dp_ep.group(1), "greengrassDataPlaneEndpoint must not be empty (empty => greengrass-ats default)"
    assert data_ep is not None and dp_ep.group(1) == data_ep.group(1), (
        "greengrassDataPlaneEndpoint must be pinned to the same account endpoint as iotDataEndpoint"
    )


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
    assert "docker exec" not in SCRIPT  # no exec into the app during provisioning


def test_retains_deployment2_device_build():
    # Everything else from deployment2 is kept (spot-check across phases).
    for marker in ("I2C", "Tailscale", "aquila-cert-renew", "security.sh", "Plymouth"):
        assert marker in SCRIPT, f"deployment3 dropped a shared step: {marker}"


# --- host_config matches the merged plate-geometry shape (#526) --------------
#
# The app reads axis.stops (list or per-row dict) and drawer.rows (per-row map)
# via aq_lib.plate_positions; the stale axis.positions / drawer.read_steps keys
# are no longer consumed, so a template that still writes them produces a
# host_config that fails loud at motor load. The template must also be
# well-count aware: 4-well = 6 shared axis stops + 1 drawer row; 15-well (3x5) =
# 7 axis stops per row + 3 drawer rows (A/B/C).

def test_host_config_axis_uses_stops_key_not_stale_positions():
    assert '"stops":' in SCRIPT
    assert '"positions": [320' not in SCRIPT  # stale 4-well axis literal removed


def test_host_config_drawer_uses_rows_mapping_not_read_steps_key():
    assert '"rows":' in SCRIPT
    assert '"read_steps":' not in SCRIPT      # stale drawer JSON key removed


def test_host_config_is_well_count_aware():
    # Template branches on DEVICE_WELLS to pick the shape.
    assert re.search(r'DEVICE_WELLS.*==.*"?15"?', SCRIPT)
    # 4-well shared 6-stop list retained byte-for-byte.
    assert "[320, 675, 1030, 1380, 1740, 2080]" in SCRIPT


def test_host_config_15well_has_seven_stops_and_three_rows():
    # 15-well placeholders (bench-calibrated via #530) but the COUNT must be
    # right: a 7th axis stop and a row C exist only in the 15-well form.
    assert "2450" in SCRIPT     # 7th axis stop (cols 5 + sensor_gap 2)
    assert '"C":' in SCRIPT     # per-row axis + 3rd drawer row


def test_verify_checks_drawer_rows_shape_not_read_steps():
    assert "['drawer']['read_steps']" not in SCRIPT
    assert "['drawer']['rows']" in SCRIPT
