import time
from pathlib import Path
import requests
import logging
from config import get_src_basedir
from .config_module import Config

config = Config()
logger = logging.getLogger("aquila")

def timer_control( status = "stop" ):

    status_dict = [ "start", "stop", "reset" ]
    if status not in status_dict:
        logger.warning( "Invaild timer request: %s" % status )

    logger.info( "Timer request: %s" % status )

    url = "http://127.0.0.1:8090/timer"
    try:
        response = requests.post(url, json={"action":status})
    except requests.exceptions.RequestException as e:
        logger.exception( "Error in timer request. Intended timer request: %s", status )


def change_screen( state ):
    if config.state.get(state) == None:
        logger.warning( "Invalid state: %s" % state )
        state = "-2"
    logger.info( "State selected: %s" % state )

    url = "http://127.0.0.1:8090/change_screen/" 
    try:
        response = requests.post(url, json=config.state[state])
    except requests.exceptions.RequestException as e:
        logger.exception( "Error in change screen request. Intended screen request: %s", state )

def update_results_path( results_filename ):
    url =  "http://127.0.0.1:8090/results/path"
    base_dir = Path(get_src_basedir())
    path = Path(results_filename)
    if not path.is_absolute():
        path = base_dir / path
    try:
        response = requests.post(url, json={"path":str(path)})
    except requests.exceptions.RequestException as e:
        logger.exception( "Error in path update. Intended path: %s", path )

def mark_results_ready(path: str | Path) -> None:
    base_dir = Path(get_src_basedir())
    resolved = Path(path)
    if not resolved.is_absolute():
        resolved = base_dir / resolved
    try:
        requests.post(
            "http://127.0.0.1:8090/results/path",
            json={"path": str(resolved)},
            timeout=5,
        )
    except requests.exceptions.RequestException as e:
        logger.exception("Error marking results ready: %s", e)

def log_history(profile, run_name, results_path, graph_path=None):
    url = "http://127.0.0.1:8090/history/append"
    resolved_results_path = None
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
        "graph_path": graph_path
    }
    try:
        requests.post(url, json=payload, timeout=5)
    except requests.exceptions.RequestException as e:
        logger.exception("Error logging history: %s", e)

def update_drawer_state(is_open: bool, is_closed: bool) -> None:
    url = "http://127.0.0.1:8090/drawer/state"
    payload = {"open": bool(is_open), "closed": bool(is_closed)}
    try:
        requests.post(url, json=payload, timeout=5)
    except requests.exceptions.RequestException as e:
        logger.exception("Error updating drawer state: %s", e)

def advance_run_name():
    url = "http://127.0.0.1:8090/run/name/advance"
    try:
        requests.post(url, timeout=5)
    except requests.exceptions.RequestException as e:
        logger.exception("Error advancing run name: %s", e)

def reset_exit():
    try:
        requests.post("http://127.0.0.1:8090/exit/reset", timeout=5)
    except requests.exceptions.RequestException as e:
        logger.exception( "Error in path update. Intended path: %s", path )

def reset_run_complete_ack() -> None:
    try:
        requests.post("http://127.0.0.1:8090/run/complete/ack/reset", timeout=5)
    except requests.exceptions.RequestException as e:
        logger.exception("Error resetting run complete ack: %s", e)

def reset_stop_request() -> None:
    try:
        requests.post("http://127.0.0.1:8090/stop/reset", timeout=5)
    except requests.exceptions.RequestException as e:
        logger.exception("Error resetting stop request: %s", e)

def check_stop_request() -> bool:
    url = "http://127.0.0.1:8090/button_status/"
    try:
        ret = requests.get(url, timeout=5)
        ret.raise_for_status()
        data = ret.json()
    except Exception as e:
        logger.warning("Error polling stop request", e)
        return False
    return bool(data.get("stop_requested"))


def wait_for_button(include_run_complete_ack: bool = False):
    url =  "http://127.0.0.1:8090/button_status/"
    while True:
        try:
            ret = requests.get(url, timeout=5)
            ret.raise_for_status()
            data = ret.json()
            #print(data)
        except Exception as e:
            logger.warning("Error polling run_status button", e)
            time.sleep(0.5)
            continue

        if data.get("run_requested"):
            logger.info("Run button pressed")
            profile_id = data.get("profile")
            logger.info("Requests profile selected: %s" % (profile_id))
            try:
                requests.post("http://127.0.0.1:8090/run_status/reset", timeout=5)
            except Exception as e:
                logger.warning("Error resetting button", e)
            return data
        elif data.get("drawer_open_status"):
            logger.info("Drawer open button pressed")
            ret = data.get("drawer_open_status")
            logger.info("Drawer open status: %s" % (ret))
            drawer_open = True
            drawer_close = False
            try:
                requests.post("http://127.0.0.1:8090/drawer_status/reset", timeout=5)
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
                requests.post("http://127.0.0.1:8090/drawer_status/reset", timeout=5)
            except Exception as e:
                logger.warning("Error resetting button", e)
            return data
        elif data.get("exit_button_status"):
            logger.info("Exit button pressed")
            ret = data.get("exit_button_status")
            logger.info("Exit button status: %s" % (ret))
            try:
                requests.post("http://127.0.0.1:8090/exit/reset", timeout=5)
            except Exception as e:
                logger.warning("Error resetting button", e)
            return data
        elif include_run_complete_ack and data.get("run_complete_ack"):
            logger.info("Run complete acknowledged")
            return data


        time.sleep(0.5)



if __name__ == "__main__":
    change_screen(0)
