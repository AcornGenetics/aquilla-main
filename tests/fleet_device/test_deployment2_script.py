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
