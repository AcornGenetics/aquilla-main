"""TEMPORARY hardware-variant switch (bench experiment, remove when done).

When ``AQ_DEVICE_VARIANT=12well`` is set in the device environment, the runtime
loads the ``*_12well`` duplicates of the motor / optics-read-plan / ADC modules
instead of the standard ones. This lets a single unit (sn03, for a day) be poked
into a 12-well configuration in isolation -- edit ``motor_class_12well.py``,
``optics_read_plan_12well.py``, ``adc_class_12well.py`` freely without touching
the 4-well fleet's code. Every other device leaves ``AQ_DEVICE_VARIANT`` unset
and gets the standard modules, byte-for-byte unchanged.

Throwaway scaffolding: to revert, point ``state_run_assay`` back at the concrete
modules and delete this file plus the three ``*_12well`` duplicates.
"""
import logging
import os

logger = logging.getLogger(__name__)

_VARIANT = os.getenv("AQ_DEVICE_VARIANT", "").strip().lower()

if _VARIANT == "12well":
    logger.warning("AQ_DEVICE_VARIANT=12well -- loading *_12well hardware modules")
    from aq_lib.motor_class_12well import Axis, Drawer
    from aq_lib.adc_class_12well import OpticalRead
    from aq_lib.optics_read_plan_12well import READS_PER_CYCLE, optics_read_tasks
else:
    from aq_lib.motor_class import Axis, Drawer
    from aq_lib.adc_class import OpticalRead
    from aq_lib.optics_read_plan import READS_PER_CYCLE, optics_read_tasks

__all__ = ["Axis", "Drawer", "OpticalRead", "READS_PER_CYCLE", "optics_read_tasks"]
