import logging
import logging.config
from threading import Thread, Event
from queue import Queue
from queue import Empty
import RPi.GPIO as GPIO
import sys

from aq_lib.meerstetter import MeerStetter
from aq_lib.meerstetter import set_time
from aq_lib.thermal_engine import thermal_engine
from aq_lib.thermal_parser import thermal_parser
from aq_lib.config_module import Config
from aq_lib.utils import load_json
from aq_lib.utils import LogFileName
from aq_lib.utils import LOGGING_CONFIG

from fan_class import Fan
from adc_class import OpticalRead
from aq_lib.motor_class import Axis, Drawer

logging.config.dictConfig( LOGGING_CONFIG )
logger = logging.getLogger( "aquila_logger" )
config = Config()

axis = Axis( GPIO )
axis.STEP_MULTIPLIER= config.axis["step multiplier"]
ret = axis.move_w_home_flag (   -2200, 0.0011 )
print ( ret )
axis.reset_position()

w0 = config.axis["well_one"]
dw = config.axis["well_spacing"]
positions = [w0 + dw*i for i in range(6)]
print ( positions ) 

device_type = int (config.pcr["device_type"] )

thermal_profile = "profiles/melt_curve.json" 

pid = int(config.pcr["pid"], 16)
vid = int(config.pcr["vid"], 16)
device = MeerStetter.find_meer( vid, pid, device_type)
logger.info ( device )
meer = MeerStetter( device, baudrate = 57600, timeout = 1 )

steps = load_json( thermal_profile )["steps"]

pcr_fan = Fan()
optics = OpticalRead()
optics.read_config()
optics.set_channel( 0,1 ) # fam channel. 

lfn = LogFileName()
pcr_log = lfn.get_pcr_log_filename()
optics_log = lfn.get_optics_log_filename()

logger.info( "PCR log: %s", pcr_log )
logger.info( "Optics log: %s", optics_log )

def executor( q ):
    while True:
        #logger.info( "Queue worker loops" )
        try:
            item = q.get(timeout=10) 
            #logger.info( "Message received: %s", item.__str__() )
            if type(item) is dict and "capture" in item:
                optics.capture_blink( 
                                   item["led_pin"], 
                                   item["cycle"],
                                   item["position"],
                                   )
                q.task_done()  # Mark the task as complete
                continue
            if type(item) is str and item == "quit":
                break
        except Empty:
            pass

message_queue = Queue()
execution_thread = Thread( target = executor, args = (message_queue, ) )

execution_thread.daemon = True
execution_thread.start()

def read_wells( args ):
    cycle = args[1]  # name, n, last_temp...

    for wellnr in range(2,6):
        logger.info( "read wellnr: %d", wellnr )
        position = positions[wellnr]
        axis.move_abs_wo_home_flag( position, 0.0011 )
        message_queue.put( {
            "capture":1, 
            "duration":1, 
            "led_pin":27, 
            "cycle":cycle, 
            "position":wellnr
            } )
        message_queue.join() # wait for task to complete
    # prepare for next
    axis.move_abs_wo_home_flag( positions[2], 0.0011 )

def callback( args ):
    logger.info( "Callback" )
    if "fan_off" in args: pcr_fan.set_state ( 0 )
    elif "fan_on" in args: pcr_fan.set_state ( 1 )
    elif "optics" in args: 
        logger.info( "Optics" )
        read_wells( args )

stop_event = Event()  # to stop thermal loop

try:
    with (
            open ( pcr_log,"w" ) as pcr_fp,
            open ( optics_log, "w" ) as optics_fp
            ):

        actions = thermal_parser( steps )
        thermal_thread = Thread ( 
                target = thermal_engine,
                args = ( actions, meer, callback, pcr_fp, stop_event, ))

        axis.move_abs_wo_home_flag( positions[3], 0.0011 )
        optics.data_file = optics_fp
        print ( "# Starting optics log", file = optics_fp, flush=True )
        print ( "# Starting log", file = pcr_fp )
        optics.t0 = set_time()  # synchronizing optics with thermal
        thermal_thread.start()
        while thermal_thread.is_alive():
            message_queue.put( {
                "capture":1, 
                "duration":1, 
                "led_pin":27, 
                "cycle":0, 
                "position":0
                } )
            message_queue.join() # wait for task to complete
        message_queue.put("quit")
        execution_thread.join()

except KeyboardInterrupt as ki:
    print ( "Keyboard Interrupt. Turning off Meerstetter controller. " )
    logger.error ( "Keyboard Interrupt. Turning off Meerstetter controller. " )
    meer.setTargetObjectTemperature ( 25.0 )
    meer.output_stage_enable ( 0 )
except Exception as e:
    print ( "Exception during thermocycling. Turning off Meerstetter controller. " )
    logger.error ( "Exception during thermocycling. Turning off Meerstetter controller. " )
    meer.setTargetObjectTemperature ( 25.0 )
    meer.output_stage_enable ( 0 )
    raise ( e )



