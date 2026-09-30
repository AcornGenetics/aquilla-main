"""
Unit tests for sourcing Meerstetter tuning from the config XML instead of
hardcoded literals.

Covers the pure/orchestration logic added to aq_lib.meerstetter:
  - parse_config_xml: XML -> {(parid, inst): float}, skipping strings/NaN
  - writable_tuning_parids: reuse the register map, keep only the 3xxx block
  - apply_config_xml: write only allowlisted par-ids, per channel, from the XML
  - find_config_xml: glob the staged XML, fail loudly on 0 or >1 matches

No serial hardware is involved: apply_config_xml is exercised against a
duck-typed fake so the real method logic runs without opening a port.
"""
import pytest

from aq_lib.meerstetter import MeerStetter


SAMPLE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<root>
  <BasicPar>
    <Window Title="HR Input 1">
      <!-- read-only live measurement: numeric but NOT a tuning knob (1xxx) -->
      <Parameter MeParID="1000" MeParInst="1" Name="Object Temperature">26.3</Parameter>
      <!-- string-typed: must be skipped by the parser -->
      <Parameter MeParID="4034" MeParInst="1" Name="Sensor Type">PT1000</Parameter>
      <!-- NaN: must be skipped by the parser -->
      <Parameter MeParID="1046" MeParInst="1" Name="Differential Voltage">NaN</Parameter>
    </Window>
    <Window Title="Temperature Controller">
      <Parameter MeParID="3010" MeParInst="1" Name="Kp">80</Parameter>
      <Parameter MeParID="3010" MeParInst="2" Name="Kp">20</Parameter>
      <Parameter MeParID="3011" MeParInst="1" Name="Ti">5</Parameter>
      <Parameter MeParID="3011" MeParInst="2" Name="Ti">20</Parameter>
      <Parameter MeParID="3012" MeParInst="1" Name="Td">4</Parameter>
      <Parameter MeParID="3012" MeParInst="2" Name="Td">0</Parameter>
      <Parameter MeParID="3003" MeParInst="1" Name="Coarse Temp Ramp">1.6</Parameter>
    </Window>
  </BasicPar>
</root>
"""


class _FakeMeer:
    """Duck-typed stand-in for a MeerStetter that records writes instead of
    driving a serial port. Uses the real (unbound) methods under test."""

    def __init__(self):
        # A small slice of the real register map: a read-only 1xxx entry plus
        # 3xxx tuning entries, so we can prove the 1xxx one is excluded.
        self.registers = [
            ("ObjectTemperature", 1000),
            ("CoarseTempRamp", 3003),
            ("Kp", 3010),
            ("Ti", 3011),
            ("Td", 3012),
        ]
        self.float_writes = []  # (parid, value, inst)
        self.long_writes = []   # (parid, inst, value)

    def set_parid_float(self, parid, value, inst=None):
        self.float_writes.append((parid, value, inst))

    def set_parid_long(self, parid, inst, value):
        self.long_writes.append((parid, inst, value))

    def read(self, n):
        return b""

    # Bind the real implementations onto the fake.
    parse_config_xml = staticmethod(MeerStetter.parse_config_xml)
    writable_tuning_parids = MeerStetter.writable_tuning_parids
    apply_config_xml = MeerStetter.apply_config_xml


@pytest.fixture
def xml_file(tmp_path):
    p = tmp_path / "device.Config.xml"
    p.write_text(SAMPLE_XML)
    return str(p)


def test_parse_skips_strings_and_nan(xml_file):
    params = MeerStetter.parse_config_xml(xml_file)
    # numeric tuning values present
    assert params[(3010, 1)] == 80.0
    assert params[(3010, 2)] == 20.0
    assert params[(3003, 1)] == 1.6
    # the read-only numeric measurement is parsed (filtering happens on write)
    assert params[(1000, 1)] == 26.3
    # string- and NaN-valued params are dropped
    assert (4034, 1) not in params
    assert (1046, 1) not in params


def test_writable_tuning_parids_is_3xxx_only():
    fake = _FakeMeer()
    parids = fake.writable_tuning_parids()
    assert set(parids) == {3003, 3010, 3011, 3012}
    assert 1000 not in parids  # read-only measurement excluded


def test_apply_writes_per_channel_from_xml(xml_file):
    fake = _FakeMeer()
    written = fake.apply_config_xml(path=xml_file)

    # Per-channel values come straight from the XML — CH2 is NOT a copy of CH1.
    assert written[(3010, 1)] == 80.0
    assert written[(3010, 2)] == 20.0
    assert written[(3011, 2)] == 20.0
    assert written[(3012, 2)] == 0.0

    # The read-only 1xxx register present in the XML is never written.
    assert all(parid != 1000 for parid, _v, _i in fake.float_writes)

    # Each write targets an explicit instance (never the write-both default).
    assert all(inst in (1, 2) for _p, _v, inst in fake.float_writes)


def test_apply_default_does_not_touch_flash_gate(xml_file):
    fake = _FakeMeer()
    fake.apply_config_xml(path=xml_file)
    assert fake.long_writes == []  # no par-id 108 writes without flash_gate=True


def test_apply_flash_gate_brackets_writes(xml_file):
    fake = _FakeMeer()
    fake.apply_config_xml(path=xml_file, flash_gate=True)
    # 108 disabled before and re-enabled after the float writes.
    assert fake.long_writes[0] == (108, 1, 0)
    assert fake.long_writes[-1] == (108, 1, 1)


def test_find_config_xml_single(tmp_path):
    meer_dir = tmp_path / "meerstetter"
    meer_dir.mkdir()
    xml = meer_dir / "only.xml"
    xml.write_text(SAMPLE_XML)
    assert MeerStetter.find_config_xml(config_dir=str(tmp_path)) == str(xml)


def test_find_config_xml_missing(tmp_path):
    (tmp_path / "meerstetter").mkdir()
    with pytest.raises(FileNotFoundError):
        MeerStetter.find_config_xml(config_dir=str(tmp_path))


def test_find_config_xml_ambiguous(tmp_path):
    meer_dir = tmp_path / "meerstetter"
    meer_dir.mkdir()
    (meer_dir / "a.xml").write_text(SAMPLE_XML)
    (meer_dir / "b.xml").write_text(SAMPLE_XML)
    with pytest.raises(ValueError):
        MeerStetter.find_config_xml(config_dir=str(tmp_path))
