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
    assert "docker exec" not in SCRIPT  # no exec into the app during provisioning


def test_retains_deployment2_device_build():
    # Everything else from deployment2 is kept (spot-check across phases).
    for marker in ("I2C", "Tailscale", "aquila-cert-renew", "security.sh", "Plymouth"):
        assert marker in SCRIPT, f"deployment3 dropped a shared step: {marker}"


# --- Openbox window decorations, #428 ----------------------------------------
# Openbox decorates every window by default and --kiosk does not survive a window
# being re-mapped, so Chromium's window briefly wears a title bar reading
# "Untitled — Chromium" at startup. Verified on sn03.

def test_disables_window_decorations():
    assert "aquila-kiosk-no-decor" in SCRIPT
    assert "<decor>no</decor>" in SCRIPT


def test_rc_xml_copied_from_distro_not_written_from_scratch():
    # Openbox needs a complete rc.xml; hand-writing one would drop every other
    # distro default (theme, keybinds, mouse behaviour).
    assert "cp /etc/xdg/openbox/rc.xml" in SCRIPT


def test_rc_xml_rule_inserted_inside_applications_block():
    # A second top-level <applications> element is invalid and silently ignored,
    # so the rule must go inside the existing one.
    assert "s|</applications>|" in SCRIPT


def test_rc_xml_validated_before_reboot():
    # A malformed rc.xml leaves Openbox unable to start — blank screen on a
    # device that may not be physically reachable. Validate and roll back.
    assert "xml.etree.ElementTree" in SCRIPT
    assert "restoring stock file" in SCRIPT
    assert 'run_test "rc.xml is valid XML"' in SCRIPT


def test_rc_xml_edit_is_idempotent():
    # Re-running deployment3 must not stack duplicate rules into rc.xml.
    assert "grep -q 'aquila-kiosk-no-decor'" in SCRIPT


def test_kiosk_window_mapped_fullscreen():
    """
    Without this, Chromium's window is mapped small and then resized up, and the
    growth is visible on screen — the "quadrant fill" on #428, which was mistaken
    for a slow repaint until frame-by-frame capture on sn09 showed a part-sized
    decorated window rather than a partially painted one.
    """
    assert "<fullscreen>yes</fullscreen>" in SCRIPT
    assert "<maximized>yes</maximized>" in SCRIPT


def test_kiosk_window_background_is_dark():
    """
    Chromium's window background — visible after the window is mapped but before
    the page paints — comes from GTK, not Chromium, and is bright white by
    default. That makes every seam around it obvious against the black either
    side.

    No Chromium flag reaches it: --default-background-color and
    --cast-app-background-color both govern the page area and were verified in
    the running process on sn09 with no effect on this surface.
    """
    assert "GTK_THEME=Adwaita:dark" in SCRIPT
    assert ".config/gtk-3.0/gtk.css" in SCRIPT
    assert "background-color: #000000" in SCRIPT
