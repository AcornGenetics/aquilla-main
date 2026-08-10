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


# --- Same-origin splash via nginx, #431 --------------------------------------
# The splash used to load from file:// and redirect to http://localhost:8090.
# That crosses an origin boundary, so Chromium discards the renderer it just
# warmed up and builds a second one for the app — the visible blank between
# splash and app. Measured A/B on sn11: same-origin is seamless, file:// is not.

def test_kiosk_opens_the_nginx_origin():
    assert "--kiosk http://localhost:8080/" in SCRIPT


def test_no_file_url_splash():
    # The kiosk must not open the splash as a local file — that is the origin
    # boundary this change removes.
    assert "file:///opt/aquila/splash.html" not in SCRIPT.replace(
        "! grep -q 'file:///opt/aquila/splash.html'", ""
    )


def test_splash_not_installed_on_host():
    # It ships in the UI image (Dockerfile.ui copies aquila_web/static/), so a
    # host copy would be a second file drifting from the repo — how #424 and
    # #426 happened.
    assert "-o /opt/aquila/splash.html" not in SCRIPT


def test_web_security_no_longer_disabled():
    # A file:// page fetching http://localhost:8090/health is cross-origin, so
    # the old splash only worked because Chromium ran with web security off, on
    # a device holding device certificates. Same-origin needs neither flag.
    launch = SCRIPT.split("chromium \\")[1] if "chromium \\" in SCRIPT else ""
    assert "--disable-web-security" not in launch
    assert "--allow-file-access-from-files" not in launch
