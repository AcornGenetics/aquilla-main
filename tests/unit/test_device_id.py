import os
import pytest

from aq_lib.device_id import inject_hw_serial_env, read_rpi_serial

CPUINFO_WITH_SERIAL = (
    "processor\t: 0\n"
    "model name\t: ARMv7 Processor rev 4 (v7l)\n"
    "Hardware\t: BCM2711\n"
    "Revision\t: b03115\n"
    "Serial\t\t: 10000000a6b7d43e\n"
    "Model\t: Raspberry Pi 4 Model B Rev 1.5\n"
)

CPUINFO_NO_SERIAL = (
    "processor\t: 0\n"
    "model name\t: x86_64\n"
    "vendor_id\t: GenuineIntel\n"
)

CPUINFO_ZERO_SERIAL = "Serial\t\t: 0000000000000000\n"


class TestReadRpiSerial:
    def test_parses_serial_from_cpuinfo(self, tmp_path):
        f = tmp_path / "cpuinfo"
        f.write_text(CPUINFO_WITH_SERIAL)
        assert read_rpi_serial(str(f)) == "10000000a6b7d43e"

    def test_returns_none_when_serial_line_absent(self, tmp_path):
        f = tmp_path / "cpuinfo"
        f.write_text(CPUINFO_NO_SERIAL)
        assert read_rpi_serial(str(f)) is None

    def test_returns_none_for_all_zero_serial(self, tmp_path):
        f = tmp_path / "cpuinfo"
        f.write_text(CPUINFO_ZERO_SERIAL)
        assert read_rpi_serial(str(f)) is None

    def test_returns_none_when_file_missing(self, tmp_path):
        assert read_rpi_serial(str(tmp_path / "nonexistent")) is None


class TestInjectHwSerialEnv:
    def test_sets_aq_sync_device_id_from_hardware_serial(self, tmp_path, monkeypatch):
        monkeypatch.delenv("AQ_SYNC_DEVICE_ID", raising=False)
        f = tmp_path / "cpuinfo"
        f.write_text(CPUINFO_WITH_SERIAL)
        inject_hw_serial_env(str(f))
        assert os.environ["AQ_SYNC_DEVICE_ID"] == "10000000a6b7d43e"

    def test_does_not_overwrite_existing_env_var(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AQ_SYNC_DEVICE_ID", "manually-set-id")
        f = tmp_path / "cpuinfo"
        f.write_text(CPUINFO_WITH_SERIAL)
        inject_hw_serial_env(str(f))
        assert os.environ["AQ_SYNC_DEVICE_ID"] == "manually-set-id"

    def test_noop_when_serial_cannot_be_read(self, tmp_path, monkeypatch):
        monkeypatch.delenv("AQ_SYNC_DEVICE_ID", raising=False)
        inject_hw_serial_env(str(tmp_path / "nonexistent"))
        assert "AQ_SYNC_DEVICE_ID" not in os.environ
