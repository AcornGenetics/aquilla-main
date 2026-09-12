from pathlib import Path

SCRIPT = Path("scripts/deploy/deployment2.sh").read_text()
SECURITY = Path("scripts/setup/security.sh").read_text()


def test_meerstetter_xml_downloaded() -> None:
    assert "MEERSTETTER_XMLS" in SCRIPT
    assert "config/meerstetter" in SCRIPT
    assert "config_files/meerstetter" in SCRIPT


def test_meerstetter_xml_default_filename() -> None:
    assert "24NOV25.SN1.Config.w.PT1000.cal.1.xml" in SCRIPT


def test_meerstetter_xml_not_overwritten() -> None:
    assert "cp -n" in SCRIPT


def test_meerstetter_tuning_active() -> None:
    assert "MeerStetter.find_meer" in SCRIPT
    assert "Meerstetter device not found" in SCRIPT
    assert "Meerstetter tuning applied" in SCRIPT
    assert "# meer.set_parid_long" not in SCRIPT


def test_meerstetter_tuning_fails_phase() -> None:
    assert "phase_fail" in SCRIPT
    assert "Meerstetter tuning failed" in SCRIPT


def test_security_script_downloaded() -> None:
    assert "security.sh" in SCRIPT


# --- Tailscale skip flag (Phase 12) ------------------------------------------
# SKIP_TAILSCALE=1 bypasses Phase 12 so a device can be provisioned without
# joining the tailnet (or when interactive Tailscale auth is failing).

def test_tailscale_skip_flag_guards_phase_12() -> None:
    assert 'SKIP_TAILSCALE:-' in SCRIPT
    assert "Tailscale skipped (SKIP_TAILSCALE=1)" in SCRIPT


def test_tailscale_skip_documented_in_usage() -> None:
    assert "SKIP_TAILSCALE=1" in SCRIPT


# --- Fleet DNS forwarder (dnsmasq), #314 -------------------------------------
# Container DNS freezes to the resolver captured at network-creation time; a
# dnsmasq forwarder on the docker bridge gateway lets containers follow the
# host's live resolver so a network move doesn't break in-container sync/OTA.

def test_dnsmasq_installed() -> None:
    assert "apt-get install -y dnsmasq" in SCRIPT


def test_dnsmasq_listens_on_bridge_gateway() -> None:
    # containers reach the host at the docker bridge gateway 172.18.0.1
    assert "listen-address=172.18.0.1" in SCRIPT


def test_dnsmasq_binds_dynamically_for_late_bridge() -> None:
    # the bridge gateway interface only exists after the compose network is up,
    # so bind-dynamic lets dnsmasq bind it when it appears instead of failing
    assert "bind-dynamic" in SCRIPT


def test_dnsmasq_forwarder_is_loop_safe() -> None:
    # the forwarder must never point upstream at itself or Docker's embedded DNS
    assert "server=172.18.0.1" not in SCRIPT
    assert "server=127.0.0.11" not in SCRIPT


def test_dnsmasq_service_enabled_and_started() -> None:
    # enable so it survives reboot, restart so the new config takes effect now
    assert "systemctl enable dnsmasq" in SCRIPT
    assert "systemctl restart dnsmasq" in SCRIPT


# ═════════════════════════════════════════════════════════════════════════════
# Clean-startup parity with deployment3_greengrass.sh
# ─────────────────────────────────────────────────────────────────────────────
# These port the visible-artifact fixes (#418/#426/#428/#431/#437) onto the
# main-branch provisioner so devices built with deployment2.sh get the same
# clean boot as the Greengrass fleet. #424 (legacy console-autologin teardown)
# is deliberately NOT ported: deployment2 already uses LightDM autologin
# (Phase 4), never the getty+startx console path #424 removed — see the
# test_no_legacy_console_autologin_needed assertion below.
# ═════════════════════════════════════════════════════════════════════════════

SPLASH = Path("aquila_web/static/splash.html").read_text()
COMPOSE = Path("fleet-config/docker-compose.yml").read_text()


# --- Display rotation at X startup, #437 --------------------------------------
# The panel is portrait, the display comes up landscape. Rotation used to be
# applied by `xrandr --rotate right` from the Openbox autostart — after X,
# LightDM and Chromium had painted — so Chromium laid the splash out against a
# landscape viewport and re-laid it out when the geometry changed (logo jump).

def test_rotation_configured_at_x_startup() -> None:
    assert "/etc/X11/xorg.conf.d/99-rotate.conf" in SCRIPT
    assert 'Option "Rotate" "right"' in SCRIPT


def test_rotation_covers_both_connectors() -> None:
    # The panel is not always on the same connector — sn10 reports HDMI-2. Xorg
    # ignores a Monitor section matching no output, so writing both is safe.
    assert 'Identifier "HDMI-1"' in SCRIPT
    assert 'Identifier "HDMI-2"' in SCRIPT


def test_session_does_not_rotate_again() -> None:
    # Rotating in the session would undo the X-level rotation, and rotating late
    # is the original bug.
    for line in SCRIPT.splitlines():
        if line.strip().startswith("xrandr --output"):
            assert "--rotate" not in line, (
                f"session still rotates the display: {line.strip()}"
            )


def test_kiosk_window_opens_at_panel_size() -> None:
    # Without this Chromium maps its window at its default 748x561 and holds it
    # ~1s before the WM fullscreens it; a page painting in that second lays out
    # for a 561px window and shifts when it grows to 1024 — the logo jump (#437).
    assert "--window-size=768,1024" in SCRIPT
    assert "--window-position=0,0" in SCRIPT


# --- Bootloader setup screen (EEPROM), #418 ----------------------------------
# Newer factory bootloaders ship NET_INSTALL_AT_POWER_ON=1, which paints a
# "Configure this Raspberry Pi" panel over the display on every cold boot. The
# bootloader draws it pre-kernel, so the piwiz/cmdline/Plymouth suppression all
# runs too late to hide it.

def test_disables_power_on_network_install_ui() -> None:
    assert "NET_INSTALL_AT_POWER_ON" in SCRIPT
    assert "NET_INSTALL_ENABLED=0" in SCRIPT
    assert "rpi-eeprom-config --apply" in SCRIPT


def test_eeprom_write_is_skipped_when_already_correct() -> None:
    # The risk is the flash, not the setting: a power cut mid-write needs
    # physical recovery. Re-running must not reflash a correct chip.
    assert "diff -q" in SCRIPT
    assert "already correct" in SCRIPT


def test_eeprom_phase_degrades_instead_of_writing_blind() -> None:
    # No rpi-eeprom-config, or an unreadable config, must skip the phase rather
    # than apply a config built from nothing.
    assert "command -v rpi-eeprom-config" in SCRIPT
    assert "writing blind" in SCRIPT


def test_eeprom_asserts_against_staged_config_not_live_chip() -> None:
    # rpi-eeprom-config reads the CURRENT EEPROM, which still holds the old
    # values until the flashing reboot — asserting there fails on an affected
    # device. The run_tests must check the staged file instead.
    assert "EEPROM_CONF_DESIRED" in SCRIPT
    assert 'run_test "power-on setup screen off"' in SCRIPT
    assert 'run_test "network install disabled"' in SCRIPT


# --- Legacy system-wide Openbox autostart teardown, #426 ---------------------
# Openbox runs /etc/xdg/openbox/autostart BEFORE the per-user file and runs
# BOTH. deployment1.sh put the legacy WebKit kiosk (kiosk.py) there, so devices
# provisioned before this existed start two browsers; kiosk.py loads
# localhost:8090 with no retry, painting WebKit's "Connection reset by peer"
# error page over the splash.

def test_neutralises_system_wide_openbox_autostart() -> None:
    assert "/etc/xdg/openbox/autostart" in SCRIPT


def test_system_autostart_overwritten_not_deleted() -> None:
    # openbox ships this path as a dpkg conffile: a deleted file can return on
    # package upgrade, a modified one is kept.
    assert "rm -f /etc/xdg/openbox/autostart" not in SCRIPT
    assert "rm -rf /etc/xdg/openbox" not in SCRIPT


def test_legacy_kiosk_launchers_asserted_gone() -> None:
    assert 'run_test "no legacy kiosk.py launch"' in SCRIPT
    assert 'run_test "one kiosk launcher only"' in SCRIPT


def test_legacy_rotation_and_unclutter_asserted_gone() -> None:
    assert 'run_test "no system-wide unclutter"' in SCRIPT
    assert 'run_test "no system-wide xrandr"' in SCRIPT


# --- Openbox window decorations, #428 ----------------------------------------
# Openbox decorates every window by default and --kiosk does not survive a
# window being re-mapped, so Chromium's window briefly wears a title bar reading
# "Untitled — Chromium" at startup, and the window visibly grows to fullscreen.

def test_disables_window_decorations() -> None:
    assert "aquila-kiosk-no-decor" in SCRIPT
    assert "<decor>no</decor>" in SCRIPT


def test_rc_xml_copied_from_distro_not_written_from_scratch() -> None:
    # Openbox needs a complete rc.xml; hand-writing one would drop every other
    # distro default (theme, keybinds, mouse behaviour).
    assert "cp /etc/xdg/openbox/rc.xml" in SCRIPT


def test_rc_xml_rule_inserted_inside_applications_block() -> None:
    # A second top-level <applications> element is invalid and silently ignored.
    assert "s|</applications>|" in SCRIPT


def test_rc_xml_validated_before_reboot() -> None:
    # A malformed rc.xml leaves Openbox unable to start — blank screen on a
    # device that may not be physically reachable. Validate and roll back.
    assert "xml.etree.ElementTree" in SCRIPT
    assert "restoring stock file" in SCRIPT
    assert 'run_test "rc.xml is valid XML"' in SCRIPT


def test_rc_xml_edit_is_idempotent() -> None:
    # Re-running must not stack duplicate rules into rc.xml.
    assert "grep -q 'aquila-kiosk-no-decor'" in SCRIPT


def test_kiosk_window_mapped_fullscreen() -> None:
    # Mapping the window fullscreen at map time removes the visible grow.
    assert "<fullscreen>yes</fullscreen>" in SCRIPT
    assert "<maximized>yes</maximized>" in SCRIPT


def test_kiosk_window_background_is_dark() -> None:
    # Chromium's pre-paint window background comes from GTK and is white by
    # default; a dark GTK theme + black gtk.css removes the white flash.
    assert "GTK_THEME=Adwaita:dark" in SCRIPT
    assert ".config/gtk-3.0/gtk.css" in SCRIPT
    assert "background-color: #000000" in SCRIPT


# --- Same-origin splash via host nginx, #431 ---------------------------------
# The splash used to load from file:// and redirect to http://localhost:8090.
# That crosses an origin boundary, so Chromium discards the warm renderer and
# builds a second one for the app — the visible blank between splash and app.
# Host nginx serves both from one origin (:8080).

def test_kiosk_opens_the_splash_path() -> None:
    # /splash always serves the splash; / would serve the app directly whenever
    # the backend happens to be up, skipping the splash entirely.
    assert "--kiosk http://localhost:8080/splash" in SCRIPT


def test_no_file_url_splash() -> None:
    # The kiosk must not open the splash as a local file — that is the origin
    # boundary this change removes. (Excludes the negative-assertion run_test.)
    assert "file:///opt/aquila/splash.html" not in SCRIPT.replace(
        "! grep -q 'file:///opt/aquila/splash.html'", ""
    )


def test_web_security_no_longer_disabled() -> None:
    # A file:// page fetching localhost:8090/health is cross-origin, so the old
    # splash only worked with web security off, on a device holding device
    # certificates. Same-origin needs neither flag.
    launch = SCRIPT.split("chromium \\")[1] if "chromium \\" in SCRIPT else ""
    assert "--disable-web-security" not in launch
    assert "--allow-file-access-from-files" not in launch


def test_nginx_runs_on_the_host_not_in_docker() -> None:
    assert "apt-get install -y nginx" in SCRIPT
    assert "/etc/nginx/conf.d/aquila-kiosk.conf" in SCRIPT
    assert "systemctl enable nginx" in SCRIPT


def test_nginx_restarted_not_just_enabled() -> None:
    # The package starts nginx on install, before the config exists, and
    # `enable --now` does nothing to a running service — so the config would
    # never load.
    assert "systemctl restart nginx" in SCRIPT


def test_nginx_proxies_to_backend_on_loopback() -> None:
    # Host-side, so the backend is reached via its published host port, not a
    # Docker service name.
    assert "proxy_pass http://127.0.0.1:8090" in SCRIPT


def test_nginx_falls_back_to_splash() -> None:
    assert "error_page 502 503 504 = @splash" in SCRIPT
    assert "location @splash" in SCRIPT
    assert "no-store" in SCRIPT


def test_nginx_phase_frees_port_8080_on_rerun() -> None:
    # A previous deployment's aquila-ui may still hold :8080; nginx cannot bind
    # until it is stopped. The compose file moves it to :8082, but the running
    # one predates that.
    assert "docker stop aquila-ui" in SCRIPT
    assert "Address already in use" in SCRIPT or ":8080 already held" in SCRIPT


def test_ui_container_does_not_claim_8080() -> None:
    # Host nginx owns 8080; both publishing it would leave them fighting for the
    # port and the stack failing to start.
    assert '"8080:80"' not in COMPOSE
    assert '"8082:80"' in COMPOSE


def test_splash_is_same_origin() -> None:
    # The splash polls /health and navigates to / relatively — no absolute
    # localhost:8090 URL that would re-cross the origin boundary.
    assert "localhost:8090" not in SPLASH
    assert "fetch('/health'" in SPLASH
    assert "window.location.href = '/'" in SPLASH


# --- #424 is intentionally not ported ----------------------------------------

def test_no_legacy_console_autologin_needed() -> None:
    # deployment2 uses LightDM autologin (Phase 4), not the getty override +
    # `startx` console path that deployment3's #424 fix tore down. The legacy
    # path never existed here, so there is nothing to remove — assert deployment2
    # drives the display through LightDM, not a console startx.
    assert "autologin-session=openbox" in SCRIPT
    assert "do_boot_behaviour B4" in SCRIPT
    # No console startx handoff in this provisioner.
    assert "exec startx" not in SCRIPT
