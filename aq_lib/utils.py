from datetime import datetime
import json
import os

def load_json( fname ):
    with open ( fname, "r" ) as fp:
        return json.load ( fp )

class LogFileName():

    def __init__( self ):
        self.id = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')

    def get_pcr_log_filename( self, folder="logs/lid_heater", prefix="", postfix=".log" ):
        return os.path.join ( folder, prefix + self.id + postfix)

    def get_pcr_log_filename( self, folder="logs/pcr", prefix="", postfix=".log" ):
        return os.path.join ( folder, prefix + self.id + postfix)

    def get_optics_log_filename( self, folder="logs/optics", prefix="", postfix=".log" ):
        return os.path.join ( folder, prefix + self.id + postfix)

    def get_results_json_filename( self, folder="logs/results", prefix="", postfix=".json" ):
        return os.path.join ( folder, prefix + self.id + postfix)
    
class DummyMeer( object ):

    def __init__( self ):
        pass

    def output_stage_enable ( self,state ):
        logger.info ( "Dummy output stage enable: %d", state )
    def change_setpoint ( self, setpoint ):
        logger.info ( "Dummy Change setpoint: %.2f", setpoint )
    def log ( self, endtime, logfile ):
        logger.info ( "Dummy log endtime: %.2f", endtime )

def dummy_fan_callback( on_off ):
    if on_off:
        logger.info( "Dummy fan on" )
    else:
        logger.info( "Dummy fan off" )


LOGGING_CONFIG = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'default': {
            'format': '%(asctime)s - %(levelname)s - %(message)s',
        },
    },
    'handlers': {
        'file': {
            'level': 'DEBUG',
            'class': 'logging.FileHandler',
            'filename': 'logs/logger.log',
            'formatter': 'default',
        },
        'stdout': {
            'level': 'DEBUG',
            'class': 'logging.StreamHandler',
            'formatter': 'default',
        },
    },
    'loggers': {
        'aquila': {
            'handlers': ['file'],
            'level': 'DEBUG',
            'propagate': True,
        },
    },
}

APP_LOGGING_CONFIG = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'default': {
            'format': '%(asctime)s - %(levelname)s - %(message)s',
        },
    },
    'handlers': {
        'file': {
            'level': 'DEBUG',
            'class': 'logging.FileHandler',
            'filename': 'logs/app_logger.log',
            'formatter': 'default',
        },
        'stdout': {
            'level': 'DEBUG',
            'class': 'logging.StreamHandler',
            'formatter': 'default',
        },
    },
    'loggers': {
        'aquila_app': {
            'handlers': ['file'],
            'level': 'DEBUG',
            'propagate': True,
        },
    },
}

LID_HEATER_LOGGING_CONFIG = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'default': {
            'format': '%(asctime)s - %(levelname)s - %(message)s',
        },
    },
    'handlers': {
        'file': {
            'level': 'DEBUG',
            'class': 'logging.FileHandler',
            'filename': 'logs/lid_heater/lid_heater_logger.log',
            'formatter': 'default',
        },
    },
    'loggers': {
        'lid_heater': {
            'handlers': ['file'],
            'level': 'DEBUG',
            'propagate': False,
        },
    },
}




