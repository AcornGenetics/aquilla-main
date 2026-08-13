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


# --- Bootloader setup screen (EEPROM), #418 ----------------------------------
# Newer factory bootloaders ship NET_INSTALL_AT_POWER_ON=1, which paints a
# "Configure this Raspberry Pi" panel over the display on every cold boot. The
# bootloader draws it pre-kernel, so the piwiz/cmdline/Plymouth suppression in
# Phases 6, 14 and 14b all run too late to hide it.

def test_disables_power_on_network_install_ui():
    # Both keys are stripped, then network install is pinned off.
    assert "NET_INSTALL_AT_POWER_ON" in SCRIPT
    assert "NET_INSTALL_ENABLED=0" in SCRIPT
    assert "rpi-eeprom-config --apply" in SCRIPT


def test_eeprom_write_is_skipped_when_already_correct():
    # The risk is the flash, not the setting: a power cut mid-write needs
    # physical recovery. Re-running deployment3 must not reflash a correct chip.
    assert "diff -q" in SCRIPT
    assert "already correct" in SCRIPT


def test_eeprom_phase_degrades_instead_of_writing_blind():
    # No rpi-eeprom-config, or an unreadable config, must skip the phase rather
    # than apply a config built from nothing.
    assert "command -v rpi-eeprom-config" in SCRIPT
    assert "writing blind" in SCRIPT


def test_eeprom_asserts_against_staged_config_not_live_chip():
    # rpi-eeprom-config reads the CURRENT EEPROM, which still holds the old
    # values until the flashing reboot — asserting there fails on an affected
    # device. The run_tests must check the staged file instead.
    assert "EEPROM_CONF_DESIRED" in SCRIPT
    assert 'run_test "power-on setup screen off"' in SCRIPT
    assert 'run_test "network install disabled"' in SCRIPT

# --- Legacy console autologin teardown ---------------------------------------
# deployment1.sh set up console autologin (agetty --autologin on tty1) plus
# `startx` in ~/.bash_profile. Phase 4 configures LightDM autologin but never
# removed the old path, so devices provisioned before it carried both: agetty
# printed the login banner, MOTD and X.Org block on the display before LightDM
# took the screen, and .bash_profile raced it to start a second X on VT1.
# Confirmed on sn03.

def test_removes_legacy_console_autologin_override():
    assert "rm -rf /etc/systemd/system/getty@tty1.service.d" in SCRIPT
    assert "systemctl daemon-reload" in SCRIPT


def test_removes_startx_from_bash_profile():
    assert "grep -q startx" in SCRIPT


def test_bash_profile_rewritten_not_filtered():
    # Deleting only the startx line leaves `if ... then / fi` with an empty body,
    # which is a bash syntax error on every login shell. Must rewrite the file.
    assert "sed -i '/startx/d'" not in SCRIPT
    assert "grep -v startx" not in SCRIPT


def test_console_autologin_teardown_is_asserted():
    assert 'run_test "no console autologin override"' in SCRIPT
    assert 'run_test "no startx in .bash_profile"' in SCRIPT
    assert 'run_test ".bash_profile is valid bash"' in SCRIPT

# --- Legacy system-wide Openbox autostart teardown ---------------------------
# Openbox runs /etc/xdg/openbox/autostart BEFORE the per-user file and runs BOTH.
# deployment1.sh put the legacy WebKit kiosk (kiosk.py) there, so devices
# provisioned before Phase 9b existed start two browsers. kiosk.py loads
# localhost:8090 with no retry, painting WebKit's default error page over the
# splash before the backend is listening. Confirmed on sn03.

def test_neutralises_system_wide_openbox_autostart():
    assert "/etc/xdg/openbox/autostart" in SCRIPT


def test_system_autostart_overwritten_not_deleted():
    # openbox ships this path as a dpkg conffile: a deleted file can return on
    # package upgrade, a modified one is kept.
    assert "rm -f /etc/xdg/openbox/autostart" not in SCRIPT
    assert "rm -rf /etc/xdg/openbox" not in SCRIPT


def test_legacy_kiosk_launchers_asserted_gone():
    assert 'run_test "no legacy kiosk.py launch"' in SCRIPT
    assert 'run_test "one kiosk launcher only"' in SCRIPT


def test_legacy_rotation_and_unclutter_asserted_gone():
    # The legacy file also ran `xrandr --rotate left` against this phase's
    # `--rotate right`, and unclutter, which Phase 9b deliberately avoids.
    assert 'run_test "no system-wide unclutter"' in SCRIPT
    assert 'run_test "no system-wide xrandr"' in SCRIPT

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
