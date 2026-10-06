"""Optical read pattern for one read pass (device capture config).

``read_wells`` drives exactly this pattern each optical pass, and
``READS_PER_CYCLE`` (blinks per pass) is *derived* from it — never hardcoded —
so the optics completeness math stays in sync if the pattern ever changes
(acorn-analytics#45: reads_per_cycle is a property of the capture pattern, not a
magic 8/480). Kept hardware-free so both read_wells and the tests import it.
"""
from aq_lib.geometry import geometry

# position -> dyes captured at that carriage position, in capture order.
# rox at phases 0-3, fam at phases 2-5 (8 blinks per pass for this profile).
OPTICS_READ_PLAN = [
    (0, ("rox",)),
    (1, ("rox",)),
    (2, ("rox", "fam")),
    (3, ("rox", "fam")),
    (4, ("fam",)),
    (5, ("fam",)),
]

def capture_mode(geo):
    """Optics capture mode for a plate, derived from geometry (ADR-023 / #524).

    Multi-row plates are the dual-ADC builds that read ROX+FAM simultaneously
    (``'both'``); the 1-row 4-well is single-ADC and captures phased (separate
    rox/fam blinks). No flag — a 15-well device can never be mis-configured as
    single-ADC, nor a 4-well as dual."""
    return "both" if geo.rows > 1 else "phased"


def read_plan(geo):
    """Generate the optical capture pattern for one read pass from plate geometry.

    Hardware-free: yields LOGICAL ``(row_index, stop_index, dyes)`` triples in
    traversal order. The motor maps ``stop_index`` -> ``axis.stops[stop_index]``
    and ``row_index`` -> ``drawer.rows``; nothing here knows measured steps.

    The FAM/ROX sensors sit ``geo.sensor_gap`` carriage stops apart, so each row
    sweeps ``cols + sensor_gap`` stops: ROX reads columns ``[0, cols)``, FAM the
    gap-shifted window ``[sensor_gap, sensor_gap + cols)``, both captured where
    the windows overlap. Rows serpentine (alternate direction) so the axis never
    doubles back to the start of a row. The 4-well device is the degenerate
    1-row case and reproduces ``OPTICS_READ_PLAN`` exactly.

    Single-ADC sequential rox/fam model (#510). Dual-ADC simultaneous ``'both'``
    capture (Risk B) will later swap the per-stop dye set, not this traversal.
    """
    stops = geo.cols + geo.sensor_gap
    both = capture_mode(geo) == "both"
    plan = []
    for row in range(geo.rows):
        stop_order = range(stops) if row % 2 == 0 else reversed(range(stops))
        for stop in stop_order:
            if both:
                # Dual-ADC: ROX and FAM are read simultaneously, so one 'both'
                # capture fires at every stop. Overhang stops (where one sensor
                # sees no tube) still fire and are discarded downstream (§21c).
                plan.append(((stop, row), ("both",)))
                continue
            dyes = []
            if 0 <= stop < geo.cols:
                dyes.append("rox")
            if geo.sensor_gap <= stop < geo.sensor_gap + geo.cols:
                dyes.append("fam")
            if dyes:
                plan.append(((stop, row), tuple(dyes)))
    return plan

# Blinks fired per read pass = number of captures in the plan.
READS_PER_CYCLE = sum(len(dyes) for _, dyes in OPTICS_READ_PLAN)


def reads_per_cycle(geo):
    """Captures fired per read pass for a plate geometry, derived from the
    generated plan so the optics-completeness math can't drift from the real
    read pass (ADR-023, #514). The 4-well case equals ``READS_PER_CYCLE``."""
    return sum(len(channels) for _coord, channels in read_plan(geo))


def optics_read_tasks(cycle, geo=None):
    """Executor tasks for one optical read pass, generated from plate geometry.

    For each ``((axis_stop, drawer_row), channels)`` in ``read_plan(geo)``: move a
    motor only when its coordinate changes — a ``drawer_to`` when the drawer row
    changes (multi-row plates only; a 1-row 4-well emits none), a
    ``goto_position`` when the axis stop changes — then a ``capture`` per channel.
    The serpentine repeats the axis stop across a row boundary, so the axis
    skips the redundant re-goto there (only the drawer moves). The pass closes by
    re-homing the axis. ``geo`` defaults to the device's provisioned geometry.

    Capture-mode is derived from the plate (ADR-023): 4-well single-ADC phased,
    15-well dual-ADC ``both``. 4-well is byte-identical to the legacy sequence."""
    if geo is None:
        geo = geometry()

    tasks = []
    prev_stop = None
    prev_row = None
    for (stop, row), channels in read_plan(geo):
        if geo.rows > 1 and row != prev_row:
            tasks.append({"drawer_to": row})
            prev_row = row
        if stop != prev_stop:
            tasks.append({"goto_position": stop})
            prev_stop = stop
        for channel in channels:
            tasks.append({"capture": channel, "cycle": cycle, "position": stop})
    # in future iterations the following two tasks will be moved to after thermal tasks or in parallel with them
    # extra task can be checking and logging ambient temperature (w14)
    tasks.append({"home": 0})
    tasks.append({"goto_position": 0})
    return tasks
