import logging
import logging.config

from state_run_assay import AssayInterface
from aq_lib.config_module import Config
from aq_lib.utils import APP_LOGGING_CONFIG
import aq_lib.state_requests as sr

logging.config.dictConfig( APP_LOGGING_CONFIG )
logger = logging.getLogger( "aquila_app" )

def main():
    try:
        ai = AssayInterface()
        run_armed = False
        while True:
            # When end() already armed a run from the results screen (#333),
            # skip ready() so the operator's single Run press starts it.
            if not run_armed:
                ai.ready()
            ai.run()
            run_armed = ai.end()
    except Exception as e:
        print("Exception caught in execution of application")
        print ( e )
        sr.change_screen("-1")

if __name__ == "__main__":
    main()
