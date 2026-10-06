"""FAM/ROX sensor offset derives from geo.sensor_gap, not a hardcoded +-1
(#523 / Phase B, ADR-023). Byte-identical for 4-well (gap=2)."""
import hashlib
import json
from pathlib import Path

import pytest

from aq_curve.curve import Curve, _dye_position
from aq_lib.geometry import PlateGeometry

OPTICS_LOG = Path(__file__).parents[3] / "tests" / "fixtures" / "optics" / "sample_run.log"

# sha256 of the current 4-well extract_data output (wells 1-4 x fam/rox),
# captured before the sensor-gap reconciliation. The refactor must not change it.
FOUR_WELL_GOLDEN_SHA = "011264b08b4f3f9510bad9e43e358e51d7c508fff0b459c8cc1d451a7d0c17ed"


@pytest.mark.unit
def test_dye_position_derives_from_sensor_gap():
    # ROX reads the tube's 0-origin column; FAM sits sensor_gap stops further.
    assert _dye_position(2, "rox", sensor_gap=2) == 1
    assert _dye_position(2, "fam", sensor_gap=2) == 3          # 1 + gap
    # legacy 4-well mapping (gap=2) == ROX well-1 / FAM well+1
    assert _dye_position(1, "rox", sensor_gap=2) == 0
    assert _dye_position(4, "fam", sensor_gap=2) == 5
    # a wider gap shifts only FAM
    assert _dye_position(2, "fam", sensor_gap=4) == 5


@pytest.mark.unit
def test_four_well_extract_is_byte_identical_after_reconciliation():
    """Against the real 4-well optics file, the sensor_gap-derived offset
    reproduces the legacy dpos=+-1 extraction exactly (golden sha)."""
    c = Curve(src_basedir=str(OPTICS_LOG.parent))
    four_well = PlateGeometry(rows=1, cols=4)
    golden = {}
    for dye in ("fam", "rox"):
        for well in (1, 2, 3, 4):
            x, y0, y1 = c.extract_data(OPTICS_LOG.name, dye, well, geo=four_well)
            golden[f"{dye}{well}"] = [list(x), [float(v) for v in y0], [float(v) for v in y1]]
    blob = json.dumps(golden, sort_keys=True)
    assert hashlib.sha256(blob.encode()).hexdigest() == FOUR_WELL_GOLDEN_SHA
