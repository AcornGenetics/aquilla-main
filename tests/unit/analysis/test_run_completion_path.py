"""
Safety-net tests for the two functions called in main.py's run-completion path:
  - Curve.results_to_json  (line 390 of sentri_web/main.py)
  - generate_optics_plot   (line 393 of sentri_web/main.py)

These use the real optics fixture (no stubs) to catch regressions introduced
when the AnalysisService refactor moves these calls through a new layer.
"""
import json
from pathlib import Path

import pytest

from sentri_curve.curve import Curve
from sentri_curve.plot_utils import generate_optics_plot

OPTICS_LOG = (
    Path(__file__).parents[3] / "tests" / "fixtures" / "optics" / "sample_run.log"
)

VALID_STATUSES = {"Detected", "Not Detected", "Inconclusive"}


# ---------------------------------------------------------------------------
# Curve.results_to_json — called as: Curve(src_basedir=str(RESULTS_DIR))
#                                        .results_to_json(str(optics_path), results_file.name)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestResultsToJsonWithRealLog:

    def test_creates_results_file(self, tmp_path):
        curve = Curve(src_basedir=str(tmp_path))
        curve.results_to_json(str(OPTICS_LOG), "results.json")
        assert (tmp_path / "results.json").exists()

    def test_output_is_valid_json(self, tmp_path):
        curve = Curve(src_basedir=str(tmp_path))
        curve.results_to_json(str(OPTICS_LOG), "results.json")
        data = json.loads((tmp_path / "results.json").read_text())
        assert isinstance(data, dict)

    def test_output_has_dye_row_keys(self, tmp_path):
        """Top-level keys '1' (FAM) and '2' (ROX) must be present."""
        curve = Curve(src_basedir=str(tmp_path))
        curve.results_to_json(str(OPTICS_LOG), "results.json")
        data = json.loads((tmp_path / "results.json").read_text())
        assert "1" in data and "2" in data

    def test_all_values_are_valid_statuses(self, tmp_path):
        curve = Curve(src_basedir=str(tmp_path))
        curve.results_to_json(str(OPTICS_LOG), "results.json")
        data = json.loads((tmp_path / "results.json").read_text())
        for row_key in ("1", "2"):
            for col_key, value in data[row_key].items():
                assert value in VALID_STATUSES, (
                    f"row {row_key} col {col_key}: unexpected value {value!r}"
                )


# ---------------------------------------------------------------------------
# generate_optics_plot — called as: generate_optics_plot(str(optics_path),
#                                       str(plot_path), labels=labels)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGenerateOpticsPlot:

    def test_creates_output_file(self, tmp_path):
        out = tmp_path / "plot.png"
        generate_optics_plot(str(OPTICS_LOG), str(out))
        assert out.exists()

    def test_output_file_is_nonempty(self, tmp_path):
        out = tmp_path / "plot.png"
        generate_optics_plot(str(OPTICS_LOG), str(out))
        assert out.stat().st_size > 0

    def test_output_has_png_signature(self, tmp_path):
        out = tmp_path / "plot.png"
        generate_optics_plot(str(OPTICS_LOG), str(out))
        assert out.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"

    def test_accepts_channel_labels(self, tmp_path):
        """Custom dye labels must not raise."""
        out = tmp_path / "plot_labels.png"
        generate_optics_plot(str(OPTICS_LOG), str(out), labels={"fam": "COVID", "rox": "IC"})
        assert out.exists()

    def test_accepts_none_labels(self, tmp_path):
        """None labels must fall back to defaults without raising."""
        out = tmp_path / "plot_none.png"
        generate_optics_plot(str(OPTICS_LOG), str(out), labels=None)
        assert out.exists()
