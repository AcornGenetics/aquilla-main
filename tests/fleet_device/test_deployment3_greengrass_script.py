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


def test_splash_installed_on_host_for_nginx():
    # Host nginx serves the splash in the first seconds of boot, before Docker
    # exists, so the file must be on the host filesystem.
    assert "-o /opt/aquila/splash.html" in SCRIPT


def test_web_security_no_longer_disabled():
    # A file:// page fetching http://localhost:8090/health is cross-origin, so
    # the old splash only worked because Chromium ran with web security off, on
    # a device holding device certificates. Same-origin needs neither flag.
    launch = SCRIPT.split("chromium \\")[1] if "chromium \\" in SCRIPT else ""
    assert "--disable-web-security" not in launch
    assert "--allow-file-access-from-files" not in launch


# --- Host nginx front door, #431 ---------------------------------------------
# The kiosk opens http://localhost:8080/ and never navigates away, so that
# address must answer from the first seconds of boot. Measured on sn09: the
# compose stack takes ~30-40s while Chromium launches at ~8s, so a containerised
# front door is not listening when the kiosk asks.

def test_nginx_runs_on_the_host_not_in_docker():
    assert "apt-get install -y nginx" in SCRIPT
    assert "/etc/nginx/conf.d/aquila-kiosk.conf" in SCRIPT
    assert "systemctl enable nginx" in SCRIPT


def test_nginx_restarted_not_just_enabled():
    # The package starts nginx on install, before the config exists, and
    # `enable --now` does nothing to a running service — so the config would
    # never load. Cost an hour on sn09.
    assert "systemctl restart nginx" in SCRIPT


def test_nginx_proxies_to_backend_on_loopback():
    # Host-side, so the backend is reached via its published host port, not a
    # Docker service name.
    assert "proxy_pass http://127.0.0.1:8090" in SCRIPT


def test_nginx_falls_back_to_splash():
    assert "error_page 502 503 504 = @splash" in SCRIPT
    assert "location @splash" in SCRIPT
    assert "no-store" in SCRIPT


def test_ui_container_does_not_claim_8080():
    # Host nginx owns 8080; both publishing it would leave them fighting for the
    # port and the stack failing to start.
    compose = Path("fleet-config/greengrass-compose.yaml").read_text()
    assert '"8080:80"' not in compose
    assert '"8082:80"' in compose


def test_nginx_phase_frees_port_8080_on_rerun():
    """
    On a re-run, a previous deployment's aquila-ui may still be publishing :8080,
    and nginx fails with `bind() to 0.0.0.0:8080 failed (98: Address already in
    use)` — observed on sn09. The compose file moves that container to :8082, but
    the already-running one predates it.
    """
    assert "docker stop aquila-ui" in SCRIPT
    assert "Address already in use" in SCRIPT or ":8080 already held" in SCRIPT
