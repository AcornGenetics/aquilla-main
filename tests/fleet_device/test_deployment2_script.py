from pathlib import Path

SCRIPT = Path("deployment2.sh").read_text()


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
