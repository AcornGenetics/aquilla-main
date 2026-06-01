import os
import re
import pytest
from aq_curve.curve import Curve
from aq_curve import pcr_curve_config as config
from aq_curve.pcr_curve_helpers import get_curve_data, resolve_log_path


CURVE_RESULTS = {}


@pytest.fixture(scope="session")
def log_path():
    path = resolve_log_path()
    if not os.path.exists(path):
        pytest.skip(f"PCR log not found: {path}")
    return path


@pytest.fixture(scope="session")
def curve(log_path):
    return Curve(src_basedir=os.path.dirname(log_path))


@pytest.fixture(scope="session")
def log_name(log_path):
    return os.path.basename(log_path)


def _resolve_dyes():
    dyes = config.get_list("PCR_CURVE_DYES")
    if dyes is not None:
        return [dye.lower() for dye in dyes]
    dye = os.getenv("PCR_CURVE_DYE")
    if dye:
        return [dye.lower()]
    return list(config.DEFAULT_CURVE_DYES)


def _resolve_wells():
    wells = config.get_list("PCR_CURVE_WELLS")
    if wells is not None:
        return [int(well) for well in wells]
    well = os.getenv("PCR_CURVE_WELL")
    if well:
        return [int(well)]
    return list(config.DEFAULT_CURVE_WELLS)


def _curve_cases():
    dyes = _resolve_dyes()
    wells = _resolve_wells()
    return [(dye, well) for dye in dyes for well in wells]


@pytest.fixture(
    scope="session",
    params=_curve_cases(),
    ids=lambda case: f"{case[0]}-well{case[1]}",
)
def curve_case(request):
    return request.param


@pytest.fixture(scope="session")
def dye(curve_case):
    return curve_case[0]


@pytest.fixture(scope="session")
def well(curve_case):
    return curve_case[1]


@pytest.fixture
def curve_data(curve, log_name, dye, well):
    return get_curve_data(curve, log_name, dye, well)


def _get_curve_id(nodeid):
    match = re.search(r"\[(.+)\]$", nodeid)
    if not match:
        return None
    return match.group(1)


def _format_curve_label(curve_id):
    match = re.match(r"(.+)-well(\d+)", curve_id)
    if not match:
        return curve_id
    dye, well = match.groups()
    return f"{dye.upper()} {well}"


def pytest_runtest_logreport(report):
    if report.when != "call":
        return
    curve_id = _get_curve_id(report.nodeid)
    if curve_id is None:
        return
    entry = CURVE_RESULTS.setdefault(
        curve_id,
        {"threshold_pass": None, "other_fail": False},
    )
    if "test_threshold_crossing" in report.nodeid:
        if report.outcome == "passed":
            entry["threshold_pass"] = True
        elif report.outcome == "failed":
            entry["threshold_pass"] = False
        return
    if report.outcome == "failed":
        entry["other_fail"] = True


def pytest_terminal_summary(terminalreporter):
    if not CURVE_RESULTS:
        return
    terminalreporter.write_sep("=", "PCR Curve Summary")
    for curve_id in sorted(CURVE_RESULTS):
        entry = CURVE_RESULTS[curve_id]
        threshold_pass = entry["threshold_pass"]
        if threshold_pass is False:
            status = "undetected"
        elif threshold_pass is True and entry["other_fail"]:
            status = "inconclusive"
        elif threshold_pass is True:
            status = "detected"
        else:
            status = "inconclusive"
        label = _format_curve_label(curve_id)
        terminalreporter.write_line(f"{label} {status}")
