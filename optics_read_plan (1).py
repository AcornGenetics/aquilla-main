"""Optical read pattern for one read pass (device capture config).

``read_wells`` drives exactly this pattern each optical pass, and
``READS_PER_CYCLE`` (blinks per pass) is *derived* from it — never hardcoded —
so the optics completeness math stays in sync if the pattern ever changes
(acorn-analytics#45: reads_per_cycle is a property of the capture pattern, not a
magic 8/480). Kept hardware-free so both read_wells and the tests import it.
"""

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

OPTICS_READ_PLAN_2ADC = [
    (0, ("both",)),
    (1, ("both",)),
    (2, ("both",)),
    (3, ("both",)),
    (4, ("both",)),
    (5, ("both",)),
]

OPTICS_READ_PLAN_15 = [] # positions here are tuples of two values, where the first value is axis position, and the second value - drawer position
OPTICS_READ_PLAN_15.extend( ((i-1, -1), ("both",)) for i in range(7) )
OPTICS_READ_PLAN_15.extend( ((5-i, 0), ("both",)) for i in range(7) )
OPTICS_READ_PLAN_15.extend( ((i-1, 1), ("both",)) for i in range(7) )

# Blinks fired per read pass = number of captures in the plan.
READS_PER_CYCLE = sum(len(dyes) for _, dyes in OPTICS_READ_PLAN)
READS_PER_CYCLE_15 = sum(len(dyes) for _, dyes in OPTICS_READ_PLAN_15)


def optics_read_tasks(cycle, well_15_mode = False, updated4 = False):
    """Executor tasks for one optical read pass: goto + capture per position,
    then re-home for the next pass. read_wells enqueues exactly these."""
    tasks = []
    plan = OPTICS_READ_PLAN
    if well_15_mode: 
        plan = OPTICS_READ_PLAN_15
    elif updated4:
        plan = OPTICS_READ_PLAN_2ADC
    for position, dyes in plan:
        tasks.append({"goto_position": position})
        for dye in dyes:
            tasks.append({"capture": dye, "cycle": cycle, "position": position})
    # in future iterations the following two tasks will be moved to after thermal tasks or in parallel with them
    # extra task can be checking and logging ambient temperature (w14)
    tasks.append({"home": 0})
    tasks.append({"goto_position": 0})
    return tasks
