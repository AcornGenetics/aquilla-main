import os
import time
import requests
import logging
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
    path = os.path.join("/home/pi/aquila", results_filename)
    try:
        response = requests.post(url, json={"path":path})
    except requests.exceptions.RequestException as e:
        logger.exception( "Error in path update. Intended path: %s", path )

def reset_exit():
    try:
        requests.post("http://127.0.0.1:8090/exit/reset", timeout=5)
    except requests.exceptions.RequestException as e:
        logger.exception( "Error in path update. Intended path: %s", path )


def wait_for_button():
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


        time.sleep(0.5)



if __name__ == "__main__":
    change_screen(0)
