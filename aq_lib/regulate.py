import json
import os
import RPi.GPIO as GPIO
import threading
import time
import logging
import logging.config
from aq_lib.utils import LID_HEATER_LOGGING_CONFIG
from aq_lib import lid_worker_metrics as lwm
from aq_lib.lid_heater_log import emit_lid_sample
from aq_lib.lid_heater_window import LidSampler

from .lid_temperature import ADS1115

GPIO.setmode(GPIO.BCM) 
pin_number = 21 
GPIO.setup(pin_number, GPIO.OUT, initial=GPIO.LOW) 
adc = ADS1115( address = 0x48 )
#pwm = GPIO.PWM( pin_number, 200 )
#pwm.start(0)

logging.config.dictConfig( LID_HEATER_LOGGING_CONFIG )
logger = logging.getLogger( "lid_heater" )

DEFAULT_LID_HEATER_CONFIG = {
    "lower_bound": 0.2,
    "upper_bound": 0.34
}

def _load_lid_heater_config(config_path = None):
    config_dir = os.environ.get("CONFIG_DIR", "config_files")
    resolved_path = config_path or os.path.join(config_dir, "lid_heater_config.json")
    config = DEFAULT_LID_HEATER_CONFIG.copy()
    try:
        with open(resolved_path, "r") as fp:
            data = json.load(fp)
        if "lower_bound" in data:
            config["lower_bound"] = float(data["lower_bound"])
        if "upper_bound" in data:
            config["upper_bound"] = float(data["upper_bound"])
    except FileNotFoundError:
        logger.warning("Lid heater config not found at %s, using defaults.", resolved_path)
    except Exception as exc:
        logger.warning("Failed to load lid heater config from %s: %s. Using defaults.", resolved_path, exc)
    return config

def lid_heater_worker( stop_event, quiet_event = None, setpoint = None, lower_bound = None,
                       run_timestamp = None ):

    # --- issue #157 instrumentation: register this worker so leaks are visible ---
    tid = threading.get_ident()
    live = lwm.enter(tid)
    logger.info("LID WORKER START tid=%s live=%d", tid, live)

    # Bound before the try: the finally flushes through these, and an ADC that
    # fails to start must surface its own error, not a NameError.
    sampler = None
    worker_started = time.monotonic()

    try:
        logger.info("Starting lid heater worker")
        adc.start_continuous(channel=0, pga_fs_v=4.096, sps=64)

        if quiet_event is None or not hasattr(quiet_event, "is_set"):
            from threading import Event
            if setpoint is None and quiet_event is not None:
                setpoint = quiet_event
            quiet_event = Event()
            quiet_event.clear()

        config = _load_lid_heater_config()
        if lower_bound is None:
            lower_bound = config["lower_bound"]
        if setpoint is None:
            setpoint = config["upper_bound"]

        if lower_bound >= setpoint:
            logger.warning("Lid heater lower bound %.3f >= upper bound %.3f", lower_bound, setpoint)
        else:
            logger.info("Lid heater bounds: lower=%.3f upper=%.3f", lower_bound, setpoint)

        # Lid Heater Samples are Run-scoped by definition (ADR-022), so the
        # standalone diagnostic runner below -- which has no Run -- samples
        # nothing rather than emitting Samples that reference no Run.
        if run_timestamp is not None:
            sampler = LidSampler(cutoff_voltage=setpoint, floor_voltage=lower_bound,
                                 run_timestamp=run_timestamp)
            worker_started = time.monotonic()

        while not stop_event.is_set():
            retries = 0
            for i in range ( 10 ):
                try:
                    # Time the I2C read: a read > 5s is what lets the teardown
                    # join time out and the thread leak (issue #157, spec H1).
                    t0 = time.monotonic()
                    v = adc.read_continuous(pga_fs_v=4.096)
                    dt = time.monotonic() - t0
                    logger.info("lid AIN0: %.4f V (read %.3fs) tid=%s", v, dt, tid)
                    break
                except Exception as e:
                    retries += 1
                    logger.warning("Hickup in lid heater ADC")
                    if i==9:
                        raise e
                time.sleep ( 0.4 )

            quiet = quiet_event.is_set()
            _record_sample(sampler, v, time.monotonic() - worker_started,
                           quiet=quiet, read_seconds=dt, retries=retries)

            if not quiet_event.is_set():
                if lower_bound < v < setpoint:
                    GPIO.output( pin_number, GPIO.HIGH )
                    logger.debug("GPIO21 HIGH tid=%s v=%.4f", tid, v)
                    #pwm.ChangeDutyCycle(50)

            time.sleep(0.90)
            GPIO.output( pin_number, GPIO.LOW )
            time.sleep(0.10)

        logger.info("Turning off lid heater")
    finally:
        GPIO.output( pin_number, GPIO.LOW )
        # Flush the open window even when the worker dies mid-Run: that Sample
        # is the only record that the lid stopped being heated at all (#452).
        if sampler is not None:
            _emit(sampler.close(elapsed=time.monotonic() - worker_started))
        live = lwm.exit(tid)
        logger.info("LID WORKER EXIT tid=%s live=%d", tid, live)


def _record_sample(sampler, voltage, elapsed, *, quiet, read_seconds, retries):
    """Feed one reading to the Sample Window, emitting a Sample if it closed one.

    Telemetry must never take the heater down with it, so anything that goes
    wrong here is logged and swallowed.
    """
    if sampler is None:
        return
    try:
        _emit(sampler.record(voltage, elapsed=elapsed, quiet=quiet,
                             read_seconds=read_seconds, retries=retries,
                             live_workers=lwm.live_count()))
    except Exception:  # noqa: BLE001 - never let telemetry stall the control loop
        logger.warning("Lid Sample accumulation failed", exc_info=True)


def _emit(sample):
    if sample is None:
        return
    try:
        emit_lid_sample(sample)
    except Exception:  # noqa: BLE001 - never let telemetry stall the control loop
        logger.warning("Lid Sample emission failed", exc_info=True)

def main():

    # If I reach this point it means I am on my own.
    # Going to import some top level tools. 

    import sys

    from threading import Thread
    from threading import Event
    import logging.config

    sys.path.append ( ".." )
    from aq_lib.utils import LOGGING_CONFIG
    LOGGING_CONFIG[ 'handlers' ]['file']['filename'] = "../" + LOGGING_CONFIG[ 'handlers' ]['file']['filename']
    logging.config.dictConfig( LOGGING_CONFIG )

    stop_event = Event()
    thread = Thread( target = lid_heater_worker, args=( stop_event,) )
    thread.start()

    try:
        for counter in range ( 20 ):
            print ( "Counter: ", counter, flush = True )
            time.sleep ( 1 )
    except KeyboardInterrupt:
        print("Done.")

    print("Turning off heater.")
    stop_event.set()
    thread.join ( timeout = 5 )
    GPIO.output( pin_number, GPIO.LOW )

if __name__ == "__main__":
    main()
