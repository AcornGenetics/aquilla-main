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

# Blinks fired per read pass = number of captures in the plan.
READS_PER_CYCLE = sum(len(dyes) for _, dyes in OPTICS_READ_PLAN)


def optics_read_tasks(cycle):
    """Executor tasks for one optical read pass: goto + capture per position,
    then re-home for the next pass. read_wells enqueues exactly these."""
    tasks = []
    for position, dyes in OPTICS_READ_PLAN:
        tasks.append({"goto_position": position})
        for dye in dyes:
            tasks.append({"capture": dye, "cycle": cycle, "position": position})
    tasks.append({"home": 0})
    tasks.append({"goto_position": 0})
    return tasks
