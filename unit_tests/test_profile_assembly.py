"""
Unit tests for aquila_web/profile_assembly.py — assemble_steps(stages) -> steps.

Pure logic, no hardware or network (the module has no hardware imports, so unlike
test_estimated_completion.py this needs no RPi/serial stubbing). Marked ``unit``.
Spec: specs/backend/spec_profile_step_assembly.md (issue #198).
"""
import pytest

from aquila_web.profile_assembly import assemble_steps

pytestmark = pytest.mark.unit


def _stages(*, incubation=None, denaturation=None, final_hold=None,
            cycles=40, sub_stages=None):
    """Build a valid stages dict. Optional stages default to disabled;
    amplification defaults to the 2-sub-stage shape."""
    if sub_stages is None:
        sub_stages = [
            {"name": "Denaturation", "temp": 95, "time": 11},
            {"name": "Annealing & Extension", "temp": 60.5, "time": 38},
        ]
    return {
        "incubation": incubation or {"enabled": False, "temp": 37, "time": 600},
        "denaturation": denaturation or {"enabled": False, "temp": 95, "time": 120},
        "amplification": {"cycles": cycles, "subStages": sub_stages},
        "finalHold": final_hold or {"enabled": False, "temp": 25, "time": 60},
    }


HEAD = [
    {"disable": 0, "duration": 1, "description": "Record equilibration without power."},
    {"ramp_rate": 1.6},
    {"pcr_fanon": 1},
    {"enable": 0, "duration": 1, "description": "Turn on and record temperature for a little bit"},
    {"optics": ""},
    {"setpoint": 25, "duration": 1, "description": "Presetting temperature"},
]


TAIL = [
    {"ramp_rate": 1.6},
    {"setpoint": 40, "duration": 20, "description": "Initial cooling"},
    {"setpoint": 25, "duration": 10, "description": "Restoring setpoint to RT"},
    {"disable": 0, "duration": 5, "description": "Turn off and record temperature for a little bit"},
    {"pcr_fanoff": 0},
]


def test_emits_fixed_head_first():
    """Every assembled profile begins with the fixed equilibration/fan/optics head."""
    steps = assemble_steps(_stages())
    assert steps[:len(HEAD)] == HEAD


def test_emits_fixed_tail_last():
    """Every assembled profile ends with the fixed cooldown/fan-off tail."""
    steps = assemble_steps(_stages())
    assert steps[-len(TAIL):] == TAIL


def test_amplification_emits_ramp_then_repeat_with_cycles():
    """Amplification is always present: a 1.75 ramp followed by a repeat block
    carrying the user's cycle count. With no optional stages enabled it sits
    immediately after the head."""
    steps = assemble_steps(_stages(cycles=42))
    assert steps[len(HEAD)] == {"ramp_rate": 1.75}
    repeat_step = steps[len(HEAD) + 1]
    assert "repeat" in repeat_step
    assert repeat_step["cycles"] == 42


def _repeat_of(steps):
    """The repeat block's inner step list (amplification sits after the head when
    no optional stages are enabled)."""
    return steps[len(HEAD) + 1]["repeat"]


def test_substage_maps_to_setpoint_with_name_description():
    """A (non-extension) sub-stage becomes one setpoint whose description is its name."""
    steps = assemble_steps(_stages())
    repeat = _repeat_of(steps)
    assert repeat[0] == {"setpoint": 95, "duration": 11, "description": "Denaturation"}


def test_optics_split_on_extension_substage_two_substage_case():
    """With 2 sub-stages, the 2nd (Annealing & Extension) carries the optics read,
    split as (time-10) -> optics -> 10."""
    steps = assemble_steps(_stages())  # extension sub-stage time = 38
    assert _repeat_of(steps) == [
        {"setpoint": 95, "duration": 11, "description": "Denaturation"},
        {"setpoint": 60.5, "duration": 28, "description": "Annealing & Extension"},
        {"optics": ""},
        {"setpoint": 60.5, "duration": 10, "description": "Annealing & Extension"},
    ]


def test_optics_split_on_extension_substage_three_substage_case():
    """With 3 sub-stages, the 3rd (Extension) carries the optics read; the 2nd
    (Annealing) is a plain hold."""
    three = [
        {"name": "Denaturation", "temp": 95, "time": 11},
        {"name": "Annealing", "temp": 60, "time": 20},
        {"name": "Extension", "temp": 72, "time": 30},
    ]
    steps = assemble_steps(_stages(sub_stages=three))
    assert _repeat_of(steps) == [
        {"setpoint": 95, "duration": 11, "description": "Denaturation"},
        {"setpoint": 60, "duration": 20, "description": "Annealing"},
        {"setpoint": 72, "duration": 20, "description": "Extension"},
        {"optics": ""},
        {"setpoint": 72, "duration": 10, "description": "Extension"},
    ]


def test_incubation_emitted_after_head_when_enabled():
    """An enabled Incubation Stage is one setpoint, right after the head."""
    steps = assemble_steps(_stages(incubation={"enabled": True, "temp": 37, "time": 600}))
    assert steps[len(HEAD)] == {"setpoint": 37, "duration": 600, "description": "Incubation"}


def test_initial_denaturation_emitted_when_enabled():
    """An enabled Initial Denaturation Stage is one setpoint with that description."""
    steps = assemble_steps(_stages(denaturation={"enabled": True, "temp": 95, "time": 120}))
    assert steps[len(HEAD)] == {"setpoint": 95, "duration": 120, "description": "Initial Denaturation"}


def test_final_temp_hold_emitted_before_tail_when_enabled():
    """An enabled Final Temp Hold is one setpoint placed after amplification,
    immediately before the cooldown tail."""
    steps = assemble_steps(_stages(final_hold={"enabled": True, "temp": 25, "time": 60}))
    assert steps[-len(TAIL) - 1] == {"setpoint": 25, "duration": 60, "description": "Final Temp Hold"}


def test_disabled_optional_stages_emit_nothing():
    """With Incubation/Denaturation/Final Hold all off, only head + amplification + tail remain."""
    steps = assemble_steps(_stages(cycles=40))
    assert steps == HEAD + [
        {"ramp_rate": 1.75},
        {"repeat": [
            {"setpoint": 95, "duration": 11, "description": "Denaturation"},
            {"setpoint": 60.5, "duration": 28, "description": "Annealing & Extension"},
            {"optics": ""},
            {"setpoint": 60.5, "duration": 10, "description": "Annealing & Extension"},
        ], "cycles": 40},
    ] + TAIL


def test_full_profile_ordering_all_stages_enabled():
    """End-to-end: head -> incubation -> denaturation -> amplification -> final hold -> tail."""
    steps = assemble_steps(_stages(
        incubation={"enabled": True, "temp": 37, "time": 600},
        denaturation={"enabled": True, "temp": 95, "time": 120},
        final_hold={"enabled": True, "temp": 25, "time": 60},
        cycles=40,
    ))
    assert steps == HEAD + [
        {"setpoint": 37, "duration": 600, "description": "Incubation"},
        {"setpoint": 95, "duration": 120, "description": "Initial Denaturation"},
        {"ramp_rate": 1.75},
        {"repeat": [
            {"setpoint": 95, "duration": 11, "description": "Denaturation"},
            {"setpoint": 60.5, "duration": 28, "description": "Annealing & Extension"},
            {"optics": ""},
            {"setpoint": 60.5, "duration": 10, "description": "Annealing & Extension"},
        ], "cycles": 40},
        {"setpoint": 25, "duration": 60, "description": "Final Temp Hold"},
    ] + TAIL
