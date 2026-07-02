import os
import time
from pathlib import Path
import requests
import logging
from config import get_src_basedir
from .config_module import Config

config = Config()
logger = logging.getLogger("aquila")
BACKEND_URL = os.environ.get("BACKEND_URL", "http://127.0.0.1:8090")

def timer_control( status = "stop" ):

    status_dict = [ "start", "stop", "reset" ]
    if status not in status_dict:
        logger.warning( "Invaild timer request: %s" % status )

    logger.info( "Timer request: %s" % status )

    url = f"{BACKEND_URL}/timer"
    try:
        response = requests.post(url, json={"action":status}, timeout=5)
    except requests.exceptions.RequestException as e:
        logger.exception( "Error in timer request. Intended timer request: %s", status )


def change_screen( state ):
    if config.state.get(state) == None:
        logger.warning( "Invalid state: %s" % state )
        state = "-2"
    logger.info( "State selected: %s" % state )

    url = f"{BACKEND_URL}/change_screen/"
    try:
        response = requests.post(url, json=config.state[state], timeout=5)
    except requests.exceptions.RequestException as e:
        logger.exception( "Error in change screen request. Intended screen request: %s", state )

def update_results_path( results_filename ):
    url = f"{BACKEND_URL}/results/path"
    base_dir = Path(get_src_basedir())
    path = Path(results_filename)
    if not path.is_absolute():
        path = base_dir / path
    try:
        response = requests.post(url, json={"path":str(path)}, timeout=5)
    except requests.exceptions.RequestException as e:
        logger.exception( "Error in path update. Intended path: %s", path )

def mark_results_ready(path: str | Path) -> None:
    base_dir = Path(get_src_basedir())
    resolved = Path(path)
    if not resolved.is_absolute():
        resolved = base_dir / resolved
    try:
        requests.post(
            f"{BACKEND_URL}/results/path",
            json={"path": str(resolved)},
            timeout=5,
        )
    except requests.exceptions.RequestException as e:
        logger.exception("Error marking results ready: %s", e)

def log_history(profile, run_name, results_path, graph_path=None):
    url = f"{BACKEND_URL}/history/append"
    resolved_results_path = None
    tube_names = None
    try:
        response = requests.get(f"{BACKEND_URL}/tube_names", timeout=5)
        if response.ok:
            data = response.json()
            tube_names = data.get("names")
    except requests.exceptions.RequestException:
        tube_names = None
    if results_path:
        base_dir = Path(get_src_basedir())
        candidate_path = Path(results_path)
        if not candidate_path.is_absolute():
            candidate_path = base_dir / results_path
        resolved_results_path = str(candidate_path)
    payload = {
        "profile": profile,
        "run_name": run_name,
        "results_path": resolved_results_path or results_path,
        "graph_path": graph_path,
        "tube_names": tube_names
    }
    try:
        requests.post(url, json=payload, timeout=5)
    except requests.exceptions.RequestException as e:
        logger.exception("Error logging history: %s", e)

def update_drawer_state(is_open: bool, is_closed: bool) -> None:
    url = f"{BACKEND_URL}/drawer/state"
    payload = {"open": bool(is_open), "closed": bool(is_closed)}
    try:
        requests.post(url, json=payload, timeout=5)
    except requests.exceptions.RequestException as e:
        logger.exception("Error updating drawer state: %s", e)

def advance_run_name():
    url = f"{BACKEND_URL}/run/name/advance"
    try:
        requests.post(url, timeout=5)
    except requests.exceptions.RequestException as e:
        logger.exception("Error advancing run name: %s", e)

def emit_run_complete(
    run_name: str,
    profile: str,
    results_path: str,
    run_timestamp: str | None = None,
) -> None:
    url = f"{BACKEND_URL}/events/run_complete"
    payload = {"run_name": run_name, "profile": profile, "results_path": results_path}
    if run_timestamp is not None:
        payload["run_timestamp"] = run_timestamp
    try:
        requests.post(url, json=payload, timeout=5)
    except requests.exceptions.RequestException as e:
        logger.exception("Error emitting run_complete event: %s", e)

def emit_optics_readings(
    optics_path: str,
    run_timestamp: str,
    expected_lines: int,
    aborted: bool = False,
) -> None:
    # Capture the exact optics file this run produced onto the same events
    # outbox as run_complete, sharing its run_timestamp so the cloud derives one
    # run_id per Run (#288). The backend reads/gzips/hashes the file and applies
    # the completeness + abort rules from the frozen contract.
    url = f"{BACKEND_URL}/events/optics_readings"
    payload = {
        "optics_path": optics_path,
        "run_timestamp": run_timestamp,
        "expected_lines": expected_lines,
        "aborted": aborted,
    }
    try:
        requests.post(url, json=payload, timeout=5)
    except requests.exceptions.RequestException as e:
        logger.exception("Error emitting optics_readings event: %s", e)

def reset_exit():
    try:
        requests.post(f"{BACKEND_URL}/exit/reset", timeout=5)
    except requests.exceptions.RequestException as e:
        logger.exception( "Error in path update. Intended path: %s", path )

def reset_run_complete_ack() -> None:
    try:
        requests.post(f"{BACKEND_URL}/run/complete/ack/reset", timeout=5)
    except requests.exceptions.RequestException as e:
        logger.exception("Error resetting run complete ack: %s", e)

def reset_stop_request() -> None:
    try:
        requests.post(f"{BACKEND_URL}/stop/reset", timeout=5)
    except requests.exceptions.RequestException as e:
        logger.exception("Error resetting stop request: %s", e)

_stop_poll_failures = 0
_STOP_POLL_FAILURE_LIMIT = 10

def check_stop_request() -> bool:
    global _stop_poll_failures
    url = f"{BACKEND_URL}/button_status/"
    try:
        ret = requests.get(url, timeout=5)
        ret.raise_for_status()
        data = ret.json()
        _stop_poll_failures = 0
    except Exception as e:
        _stop_poll_failures += 1
        logger.warning("Error polling stop request (%d/%d): %s", _stop_poll_failures, _STOP_POLL_FAILURE_LIMIT, e)
        if _stop_poll_failures >= _STOP_POLL_FAILURE_LIMIT:
            logger.error("Backend unreachable for %d consecutive polls — forcing stop", _stop_poll_failures)
            return True
        return False
    return bool(data.get("stop_requested"))


def wait_for_button(include_run_complete_ack: bool = False):
    url = f"{BACKEND_URL}/button_status/"
    while True:
        try:
            ret = requests.get(url, timeout=5)
            ret.raise_for_status()
            data = ret.json()
            #print(data)
        except Exception as e:
            logger.warning("Error polling run_status button: %s", e)
            time.sleep(0.5)
            continue

        if data.get("run_requested"):
            logger.info("Run button pressed")
            profile_id = data.get("profile")
            logger.info("Requests profile selected: %s" % (profile_id))
            try:
                # Consume only the run-request edge — must NOT clear the selected
                # profile, or the Run-card header goes blank ("--") for the whole
                # run (#275). /run_status/reset would wipe the profile too.
                requests.post(f"{BACKEND_URL}/run_requested/ack", timeout=5)
            except Exception as e:
                logger.warning("Error acknowledging run request", e)
            return data
        elif data.get("drawer_open_status"):
            logger.info("Drawer open button pressed")
            ret = data.get("drawer_open_status")
            logger.info("Drawer open status: %s" % (ret))
            drawer_open = True
            drawer_close = False
            try:
                requests.post(f"{BACKEND_URL}/drawer_status/reset", timeout=5)
            except Exception as e:
                logger.warning("Error resetting button", e)
            return data
        elif data.get("drawer_close_status"):
            logger.info("Drawer close button pressed")
            ret = data.get("drawer_close_status")
            logger.info("Drawer close status: %s" % (ret))
            drawer_open = False
            drawer_close = True
            try:
                requests.post(f"{BACKEND_URL}/drawer_status/reset", timeout=5)
            except Exception as e:
                logger.warning("Error resetting button", e)
            return data
        elif data.get("force_exit"):
            logger.info("Force exit requested")
            try:
                requests.post(f"{BACKEND_URL}/exit/force/reset", timeout=5)
            except Exception as e:
                logger.warning("Error resetting force exit", e)
            return data
        elif data.get("exit_button_status"):
            logger.info("Exit button pressed")
            ret = data.get("exit_button_status")
            logger.info("Exit button status: %s" % (ret))
            try:
                requests.post(f"{BACKEND_URL}/exit/reset", timeout=5)
            except Exception as e:
                logger.warning("Error resetting button", e)
            return data
        elif include_run_complete_ack and data.get("run_complete_ack"):
            logger.info("Run complete acknowledged")
            return data
        elif data.get("stop_requested"):
            logger.info("Stop requested during end wait — treating as run complete")
            try:
                requests.post(f"{BACKEND_URL}/stop/reset", timeout=5)
            except Exception as e:
                logger.warning("Error resetting stop request: %s", e)
            return data

        time.sleep(0.5)



if __name__ == "__main__":
    change_screen(0)
