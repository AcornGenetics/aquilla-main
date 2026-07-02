"""
Unit tests for the optical read plan (#288, review follow-up).

READS_PER_CYCLE (blinks per pass) must derive from the actual capture pattern
so the optics completeness math can never drift from what read_wells fires.
"""
from aq_lib.optics_read_plan import (
    OPTICS_READ_PLAN,
    READS_PER_CYCLE,
    optics_read_tasks,
)


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
