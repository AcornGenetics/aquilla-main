"""
Unit tests for the optical read plan (#288, review follow-up).

READS_PER_CYCLE (blinks per pass) must derive from the actual capture pattern
so the optics completeness math can never drift from what read_wells fires.
"""
from aq_lib.geometry import PlateGeometry
from aq_lib.optics_read_plan import (
    OPTICS_READ_PLAN,
    READS_PER_CYCLE,
    optics_read_tasks,
    read_plan,
    reads_per_cycle,
)


def test_reads_per_cycle_derives_per_geometry():
    # Derived from the generated plan (ADR-023 / #514), not a hardcoded 21:
    # 4-well fires 8 captures/pass; 15-well (phased) fires 15 tubes x 2 dyes = 30.
    assert reads_per_cycle(PlateGeometry(rows=1, cols=4)) == READS_PER_CYCLE == 8
    assert reads_per_cycle(PlateGeometry(rows=3, cols=5)) == 30


def test_read_plan_single_row_reproduces_the_legacy_four_well_pattern():
    # The 4-well device is the degenerate 1-row case. Dropping the (constant)
    # row index from the generated plan must yield the legacy hardcoded pattern
    # byte-for-byte: rox in columns 0-3, fam offset by the 2-stop sensor gap
    # into 2-5, both captured at the overlap (stops 2-3).
    plan = read_plan(PlateGeometry(rows=1, cols=4))
    assert [(stop, dyes) for _row, stop, dyes in plan] == OPTICS_READ_PLAN


def test_read_plan_capture_count_stays_in_sync_with_reads_per_cycle():
    # The generated 4-well plan fires exactly READS_PER_CYCLE (8) captures —
    # the completeness math can't drift from what the generator emits.
    plan = read_plan(PlateGeometry(rows=1, cols=4))
    captures = sum(len(dyes) for _row, _stop, dyes in plan)
    assert captures == READS_PER_CYCLE == 8


def test_read_plan_fifteen_well_sweeps_three_serpentine_rows_of_seven_stops():
    # 5 columns + a 2-stop sensor gap = 7 carriage stops per row; every stop
    # captures at least one dye (gap <= cols), so 7 entries/row x 3 rows.
    geo = PlateGeometry(rows=3, cols=5)
    plan = read_plan(geo)
    assert [r for r, _s, _d in plan] == [0] * 7 + [1] * 7 + [2] * 7
    assert [s for r, s, _d in plan if r == 0] == [0, 1, 2, 3, 4, 5, 6]
    # Row B serpentines back so the axis never doubles back to the row start.
    assert [s for r, s, _d in plan if r == 1] == [6, 5, 4, 3, 2, 1, 0]


def test_reads_per_cycle_derives_from_the_plan():
    # Standard rox/fam profile: rox phases 0-3 + fam phases 2-5 = 8 blinks/pass.
    assert READS_PER_CYCLE == 8
    captures = sum(len(dyes) for _, dyes in OPTICS_READ_PLAN)
    assert READS_PER_CYCLE == captures


def test_optics_read_tasks_preserves_the_original_sequence():
    # Behaviour-preservation: identical to read_wells' previous hardcoded list.
    cycle = 7
    assert optics_read_tasks(cycle) == [
        {"goto_position": 0}, {"capture": "rox", "cycle": cycle, "position": 0},
        {"goto_position": 1}, {"capture": "rox", "cycle": cycle, "position": 1},
        {"goto_position": 2}, {"capture": "rox", "cycle": cycle, "position": 2},
                              {"capture": "fam", "cycle": cycle, "position": 2},
        {"goto_position": 3}, {"capture": "rox", "cycle": cycle, "position": 3},
                              {"capture": "fam", "cycle": cycle, "position": 3},
        {"goto_position": 4}, {"capture": "fam", "cycle": cycle, "position": 4},
        {"goto_position": 5}, {"capture": "fam", "cycle": cycle, "position": 5},
        {"home": 0},
        {"goto_position": 0},
    ]


def test_task_list_capture_count_matches_reads_per_cycle():
    captures = [t for t in optics_read_tasks(1) if "capture" in t]
    assert len(captures) == READS_PER_CYCLE


def test_optics_read_tasks_for_fifteen_well_interleaves_drawer_moves_per_row():
    # Multi-row plates gain exactly one drawer_to per row (A, B, C) and drive
    # the axis across each row's stops; the pass still closes by re-homing.
    tasks = optics_read_tasks(cycle=1, geo=PlateGeometry(rows=3, cols=5))
    assert [t["drawer_to"] for t in tasks if "drawer_to" in t] == [0, 1, 2]
    assert len([t for t in tasks if "capture" in t]) == 30  # 15 tubes x 2 dyes
    assert len([t for t in tasks if "goto_position" in t]) == 21 + 1  # 3x7 + close
    assert tasks[-2:] == [{"home": 0}, {"goto_position": 0}]


def test_optics_read_tasks_single_row_emits_no_drawer_moves():
    # 4-well (1 row) must stay byte-identical: no drawer_to tasks at all.
    tasks = optics_read_tasks(cycle=1, geo=PlateGeometry(rows=1, cols=4))
    assert not any("drawer_to" in t for t in tasks)
