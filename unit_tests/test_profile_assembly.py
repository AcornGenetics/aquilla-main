"""
Unit tests for aquila_web/profile_assembly.py — assemble_steps(stages) -> steps.

Pure logic, no hardware or network (the module has no hardware imports, so unlike
test_estimated_completion.py this needs no RPi/serial stubbing). Marked ``unit``.
Spec: specs/backend/spec_profile_step_assembly.md (issue #198).
"""
import pytest

from aquila_web.profile_assembly import assemble_steps, validate_stages

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


# ---------------------------------------------------------------------------
# validate_stages (A2 / #199)
# ---------------------------------------------------------------------------


def test_valid_stages_has_no_errors():
    """A fully valid, all-stages-enabled profile produces no validation errors."""
    stages = _stages(
        incubation={"enabled": True, "temp": 37, "time": 600},
        denaturation={"enabled": True, "temp": 95, "time": 120},
        final_hold={"enabled": True, "temp": 25, "time": 60},
        cycles=40,
    )
    assert validate_stages(stages) == []


def test_temp_above_max_is_error():
    """A temperature above 100 °C on an enabled stage is flagged."""
    stages = _stages(incubation={"enabled": True, "temp": 150, "time": 600})
    errors = validate_stages(stages)
    assert any("incubation" in e for e in errors)


def test_time_above_max_is_error():
    """A duration above 600 s on an enabled stage is flagged."""
    stages = _stages(incubation={"enabled": True, "temp": 37, "time": 999})
    errors = validate_stages(stages)
    assert any("incubation.time" in e for e in errors)


def test_extension_substage_has_11s_floor_others_dont():
    """The extension-bearing (last) sub-stage needs time >= 11 so the optics split
    stays valid; a non-extension sub-stage may go as low as 1 s."""
    subs = [
        {"name": "Denaturation", "temp": 95, "time": 5},            # non-extension: 5 s OK
        {"name": "Annealing & Extension", "temp": 60, "time": 8},   # extension: 8 < 11 -> error
    ]
    errors = validate_stages(_stages(sub_stages=subs))
    assert any("subStages[1].time" in e for e in errors)
    assert not any("subStages[0].time" in e for e in errors)


def test_cycles_above_max_is_error():
    """A cycle count above 50 is flagged."""
    errors = validate_stages(_stages(cycles=51))
    assert any("cycles" in e for e in errors)


def test_substage_count_below_two_is_error():
    """Amplification must have 2 or 3 sub-stages; 1 is flagged."""
    one = [{"name": "Denaturation", "temp": 95, "time": 11}]
    errors = validate_stages(_stages(sub_stages=one))
    assert any("subStages: Invalid Value" in e for e in errors)


def test_disabled_stage_with_bad_values_is_skipped():
    """A disabled optional Stage is not validated even if its values are out of range."""
    stages = _stages(incubation={"enabled": False, "temp": 999, "time": -5})
    assert validate_stages(stages) == []


def test_non_numeric_value_is_error():
    """A blank/non-numeric value on an enabled field is flagged, not raised."""
    stages = _stages(incubation={"enabled": True, "temp": "", "time": 600})
    errors = validate_stages(stages)
    assert any("incubation.temp" in e for e in errors)


def test_malformed_substages_returns_error_not_exception():
    """A non-list subStages is reported as an error, never raised (trust boundary)."""
    stages = _stages()
    stages["amplification"]["subStages"] = None
    errors = validate_stages(stages)  # must not raise
    assert any("subStages" in e for e in errors)


def test_substages_with_non_dict_elements_returns_error_not_exception():
    """Non-dict sub-stage elements are reported, never raised."""
    stages = _stages()
    stages["amplification"]["subStages"] = [1, 2]
    errors = validate_stages(stages)  # must not raise
    assert errors


def test_missing_amplification_returns_error_not_exception():
    """A stages object missing the amplification key is reported, never raised."""
    stages = _stages()
    del stages["amplification"]
    errors = validate_stages(stages)  # must not raise
    assert any("amplification" in e for e in errors)


def test_missing_optional_stage_key_does_not_raise():
    """A stages object missing an optional stage key is tolerated (no crash)."""
    stages = _stages()
    del stages["incubation"]
    errors = validate_stages(stages)  # must not raise
    assert isinstance(errors, list)


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
