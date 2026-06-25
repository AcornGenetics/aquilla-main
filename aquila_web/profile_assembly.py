"""Assemble a structured `stages` object into the runnable `steps` array.

Pure functions only — no HTTP, disk, or hardware imports — so this module is
unit-testable in isolation. See specs/backend/spec_profile_step_assembly.md
(#198) and ADR-018 for the fixed Boilerplate constants and ordering.
"""

# Seconds held at the extension temperature after the optics read fires; the
# extension-bearing sub-stage is split into (time - tail) -> optics -> tail (ADR-018).
OPTICS_TAIL_SECONDS = 10


def assemble_steps(stages: dict) -> list:
    """Expand a structured `stages` object into the full `steps` array.

    Weaves the fixed Boilerplate (head/tail, ramps, optics read) together with
    the user's enabled Stages. Assumes well-formed input (validation is A2/#199).
    """
    steps = [
        {"disable": 0, "duration": 1, "description": "Record equilibration without power."},
        {"ramp_rate": 1.6},
        {"pcr_fanon": 1},
        {"enable": 0, "duration": 1, "description": "Turn on and record temperature for a little bit"},
        {"optics": ""},
        {"setpoint": 25, "duration": 1, "description": "Presetting temperature"},
    ]

    # Incubation (optional): one setpoint between the head and amplification.
    incubation = stages["incubation"]
    if incubation["enabled"]:
        steps.append(
            {"setpoint": incubation["temp"], "duration": incubation["time"], "description": "Incubation"}
        )

    # Initial Denaturation (optional): one setpoint before amplification.
    denaturation = stages["denaturation"]
    if denaturation["enabled"]:
        steps.append(
            {"setpoint": denaturation["temp"], "duration": denaturation["time"], "description": "Initial Denaturation"}
        )

    # Amplification (always present): mid ramp, then the cycled repeat block.
    amplification = stages["amplification"]
    sub_stages = amplification["subStages"]
    repeat_steps = []
    for index, sub in enumerate(sub_stages):
        is_extension = index == len(sub_stages) - 1
        if is_extension:
            # The optics read fires mid-hold on the extension-bearing sub-stage:
            # hold (time - tail) -> read -> hold tail (ADR-018).
            repeat_steps.append(
                {"setpoint": sub["temp"], "duration": sub["time"] - OPTICS_TAIL_SECONDS, "description": sub["name"]}
            )
            repeat_steps.append({"optics": ""})
            repeat_steps.append(
                {"setpoint": sub["temp"], "duration": OPTICS_TAIL_SECONDS, "description": sub["name"]}
            )
        else:
            repeat_steps.append(
                {"setpoint": sub["temp"], "duration": sub["time"], "description": sub["name"]}
            )
    steps.append({"ramp_rate": 1.75})
    steps.append({"repeat": repeat_steps, "cycles": amplification["cycles"]})

    # Final Temp Hold (optional): one setpoint after amplification, before the tail.
    final_hold = stages["finalHold"]
    if final_hold["enabled"]:
        steps.append(
            {"setpoint": final_hold["temp"], "duration": final_hold["time"], "description": "Final Temp Hold"}
        )

    steps += [
        {"ramp_rate": 1.6},
        {"setpoint": 40, "duration": 20, "description": "Initial cooling"},
        {"setpoint": 25, "duration": 10, "description": "Restoring setpoint to RT"},
        {"disable": 0, "duration": 5, "description": "Turn off and record temperature for a little bit"},
        {"pcr_fanoff": 0},
    ]
    return steps
