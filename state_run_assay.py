import logging
import logging.config
from threading import Thread
from threading import Event
from queue import Queue
from queue import Empty
import RPi.GPIO as GPIO
import sys
import time
import subprocess
import re
import os
from pathlib import Path

from aq_lib.meerstetter import MeerStetter
from aq_lib.meerstetter import set_time, get_time
from aq_lib.thermal_engine import RunStopped, thermal_engine
from aq_lib.thermal_parser import thermal_parser
from aq_lib.config_module import Config
from aq_lib.utils import load_json
from aq_lib.utils import LogFileName
from aq_lib.utils import LOGGING_CONFIG
from aq_lib.plot_utils import generate_optics_plot
from aq_lib.regulate import lid_heater_worker
from config import get_src_basedir
import aq_lib.state_requests as sr
from aq_lib.motor_class import Axis, Drawer

from aq_curve.main import results_to_json
from fan_class import Fan
from adc_class import OpticalRead

logging.config.dictConfig( LOGGING_CONFIG )
logger = logging.getLogger( "aquila" )
config = Config()

class AssayInterface():

    def __init__( self ):


        self.axis = Axis()
        self.drawer = Drawer()
        self.pcr_fan = Fan() 

        self.message_queue = Queue()
        self.lid_heater_stop_event = Event()
        self.lid_heater_quiet_event = Event()


        self.optics = OpticalRead()
        self.optics.read_config()

        self.run_aborted = False

        self.configure_thermal_control()
         
        self.axis.home()
        self.axis.reset_position()
        self.drawer.home()
        sr.change_screen("0")
        self.drawer.open()
        sr.update_drawer_state(is_open=True, is_closed=False)

    def configure_thermal_control(self):
        device_type = int (config.pcr["device_type"] )
        pid = int(config.pcr["pid"], 16)
        vid = int(config.pcr["vid"], 16)
        device = MeerStetter.find_meer( vid, pid, device_type)
        logger.debug ( "Temperature controller port: %s", device )
        self.meer = MeerStetter( device, baudrate = 57600, timeout = 1 )

        self.meer.setKp(80)
        self.meer.setTi(5)
        self.meer.setTd(4)

        self.thermal_profile = ""

    def executor( self ):
        logger.info( "Execution thread started." )
        while True:
            try:
                item = self.message_queue.get( timeout=10 ) 
                self.lid_heater_quiet_event.set()
                logger.info( "Task received: %s", item.__str__() )
                
                if type(item) is dict and "capture" in item:
                    logger.info("Capture task")
                    dye = item["capture"]
                    self.optics.set_channel_dye( dye )
                    self.optics.capture_blink( 
                                       dye, 
                                       item["cycle"],
                                       item["position"],
                                       )
                elif type(item) is dict and "move" in item:
                    self.axis.move_abs_wo_home_flag( item["move"], 0 )

                elif type(item) is dict and "home" in item:
                    ret = self.axis.home()
                    logger.info("Axis Position is %d", self.axis.position )
                    self.axis.reset_position()

                elif type(item) is dict and "goto_position" in item:
                    position = item["goto_position"]
                    ret = self.axis.goto_position( position )

                elif type(item) is str and item == "quit":
                    break

                self.message_queue.task_done()  # Mark the task as complete
                continue

            except Empty:
                logger.debug( "Executor idle" )
                self.lid_heater_quiet_event.clear()
                self.optics.data_file.flush()

    def queue_task( self, item ):
        self.message_queue.put ( item )

    def read_wells( self, args ):
        cycle = args[1]  # name, n, last_temp...

        for task in [ 
            { "goto_position":0 }, { "capture":"rox", "cycle":cycle, "position":0 },
            { "goto_position":1 }, { "capture":"rox", "cycle":cycle, "position":1 },
            { "goto_position":2 }, { "capture":"rox", "cycle":cycle, "position":2 },
                                   { "capture":"fam", "cycle":cycle, "position":2 },
            { "goto_position":3 }, { "capture":"rox", "cycle":cycle, "position":3 },
                                   { "capture":"fam", "cycle":cycle, "position":3 },
            { "goto_position":4 }, { "capture":"fam", "cycle":cycle, "position":4 },
            { "goto_position":5 }, { "capture":"fam", "cycle":cycle, "position":5 },
                      ]:
            self.queue_task ( task )

        # prepare for next
        self.queue_task( {"home":0})
        self.queue_task( {"goto_position":0})

    def callback( self, args ):
        logger.info( "Callback" )
        if "pcr_fanoff" in args: 
            pass
            self.pcr_fan.set_state ( 0 )
        elif "pcr_fanon" in args: self.pcr_fan.set_state ( 1 )
        elif "optics" in args: 
            logger.info( "Optics" )
            self.read_wells( args )


    def ready( self ):
        #Ready Screen
        sr.change_screen("1")
        ret = self.button_logic( state = "ready" )
        if ret == None:
            ret = self.button_logic( state = "ready" )
            if ret == None:
                logger.error("Profile is returning none when it should not. %s" % (ret))
                sr.change_screen("-1")
                raise Exception ("Profile is returning none when it should not. %s" % (ret))
        profile, run_name = ret
        logger.info("Profile selected: %s" % (profile))
        self.run_name = run_name
        self.thermal_profile = ("profiles/" + profile)
        
    
    def run( self ):
        #Run screen
        sr.change_screen("2")
        time.sleep(1)
        sr.timer_control( status = "start" )
        self.run_aborted = False
        sr.reset_stop_request()

        stop_event = Event()
        stop_monitor_event = Event()
        stop_thread = Thread(
            target=self._monitor_stop_request,
            args=(stop_event, stop_monitor_event)
        )
        stop_thread.daemon = True
        stop_thread.start()

        self.drawer.read()
        lfn = LogFileName()
        run_prefix = self._safe_name(self.run_name)

        pcr_log = lfn.get_pcr_log_filename(prefix=f"{run_prefix}_")
        optics_log = lfn.get_optics_log_filename(prefix=f"{run_prefix}_")
        results_json = lfn.get_results_json_filename(prefix=f"{run_prefix}_")
        plot_filename = f"{run_prefix}_{lfn.id}.png"
        plot_path = os.path.join("logs/plots", plot_filename)

        logger.info( "PCR log: %s", pcr_log )
        logger.info( "Optics log: %s", optics_log )
        logger.info("Optics log absolute: %s", Path(optics_log).resolve())

        steps = load_json( self.thermal_profile )["steps"]
        execution_thread = Thread( target = self.executor )

        execution_thread.daemon = True
        execution_thread.start()

        self.lid_thread = Thread ( 
             target = lid_heater_worker, 
             args = ( self.lid_heater_stop_event, self.lid_heater_quiet_event, ) 
        )
        self.lid_heater_stop_event.clear()
        self.lid_thread.start()
        self.lid_heater_quiet_event.clear()

        try:
            with (
                    open ( pcr_log,"w" ) as pcr_fp,
                    open ( optics_log, "w" ) as optics_fp
                    ):
                self.optics.data_file = optics_fp
                print ( "# Starting optics log", file = optics_fp, flush=True )
                t0_sync = set_time()
                print ( "# Starting log t0 = %f"% t0_sync, file = pcr_fp )
                actions = thermal_parser( steps )
                thermal_engine( actions, self.meer, self.callback, pcr_fp, stop_event )

                self.message_queue.put("quit")
                execution_thread.join()

        except RunStopped:
            logger.info("Run stopped by user")
            self.run_aborted = True
        except KeyboardInterrupt as ki:
            logger.error ( "Keyboard Interrupt. Turning off Meerstetter controller. " )
            sr.change_screen("-3")
        except Exception as e:
            logger.error ( "Exception during thermocycling. Turning off Meerstetter controller. " )
            sr.change_screen("-1")
            raise ( e )
        finally:
            stop_monitor_event.set()
            if stop_thread.is_alive():
                stop_thread.join(timeout=2)
            if execution_thread.is_alive():
                self.message_queue.put("quit")
                execution_thread.join(timeout=5)
            self.hw_deinitialize()
            self.drawer.open()
            if self.run_aborted:
                sr.timer_control( "stop" )
                sr.timer_control( "reset" )
                sr.change_screen("1")
                return
            try:
                os.makedirs("logs/results", exist_ok=True)
                results_to_json( optics_log, results_json )
                sr.mark_results_ready(results_json)
            except Exception as e:
                logger.error("Failed to generate results: %s", e)
            graph_path = None
            try:
                os.makedirs("logs/plots", exist_ok=True)
                generate_optics_plot(optics_log, plot_path)
                graph_path = f"/plots/{plot_filename}"
            except Exception as e:
                logger.error("Failed to generate plot: %s", e)
            sr.log_history(self.thermal_profile.replace("profiles/", ""), self.run_name, results_json, graph_path)
            sr.advance_run_name()
            sr.change_screen("3")


    def hw_deinitialize(self):
        self.meer.setTargetObjectTemperature ( 25.0 )
        self.meer.output_stage_enable ( 0 )

        #self.lid_heater_stop_event.set()
        #self.lid_thread.join( timeout = 5 )


    def end( self ):
        #End of run
        if self.run_aborted:
            self.run_aborted = False
            sr.timer_control( "stop" )
            sr.timer_control( "reset" )
            sr.change_screen("1")
            return
        sr.timer_control( "stop" )
        time.sleep(2)
        sr.timer_control( "reset" )
        sr.change_screen("3")
        self.button_logic( state = "end" ) 

    def _monitor_stop_request(self, stop_event: Event, stop_monitor_event: Event) -> None:
        while not stop_monitor_event.is_set() and not stop_event.is_set():
            if sr.check_stop_request():
                logger.info("Stop request detected")
                stop_event.set()
                sr.reset_stop_request()
                return
            time.sleep(0.5)

    def button_logic(self, state = "ready"):
        include_run_complete_ack = state == "end"
        ret = sr.wait_for_button(include_run_complete_ack)
        
        if(state == "end"):
            screens = ["8","3","9","1"]  
            #8 test complete drawer open
            #3 test complete remove samples
            #9 test complete drawer close
            #1 ready to run
        elif(state == "ready"):
            screens = ["6","1","7","4"]    
            #6 Ready to run drawer open
            #1 Ready to run
            #7 Ready to run Drawer close selected
            #4 Ready to run No profile selected Try again...

        while True:
            run = ret.get("run_requested")
            profile = ret.get("profile")
            run_name = ret.get("run_name")
            drawer_open = ret.get("drawer_open_status")
            drawer_close = ret.get("drawer_close_status")
            exit_status = ret.get("exit_button_status")
            run_complete_ack = ret.get("run_complete_ack")

            if( run is True and profile is not None ):
                break
            elif( drawer_open is True and drawer_close is False ):
                self.drawer.open()
                sr.update_drawer_state(is_open=True, is_closed=False)
                if state != "end":
                    sr.change_screen( screens[0] )
                    #time.sleep(5) #simulate drawer opening
                    sr.change_screen( screens[1] ) 
                ret = sr.wait_for_button(include_run_complete_ack)
            elif( drawer_open is False and drawer_close is True ): 
                self.drawer.read()
                sr.update_drawer_state(is_open=False, is_closed=True)
                if state != "end":
                    sr.change_screen( screens[2] )
                    #time.sleep(5) #simulate drawer close
                    sr.change_screen( screens[1] ) 
                ret = sr.wait_for_button(include_run_complete_ack)
            elif( run is True and profile is None ):
                sr.change_screen( screens[3] )
                if( state == "ready" ): 
                    ret = sr.wait_for_button(include_run_complete_ack)
                elif( state == "end" ):
                    break
            elif( exit_status is True ):
                ret = sr.wait_for_button(include_run_complete_ack)
                if(ret.get("exit_button_status")):
                    ret = sr.wait_for_button(include_run_complete_ack)
                    if(ret.get("exit_button_status")):
                        sr.change_screen("-4")
                        time.sleep(3)
                        base_dir = Path(get_src_basedir())
                        exit_script = base_dir / "exit_kiosk.sh"
                        subprocess.run(
                                [str(exit_script)], 
                                check=False
                                )
                        time.sleep(3)
                        sr.change_screen( screens[1] )
                        ret = sr.wait_for_button(include_run_complete_ack) 
                    else:
                        pass
                else:
                    pass
            elif run_complete_ack and state == "end":
                sr.change_screen("1")
                sr.reset_run_complete_ack()
                ret = sr.wait_for_button(include_run_complete_ack)

        return profile, run_name

    def _safe_name(self, value: str | None) -> str:
        if not value:
            return "run"
        return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_") or "run"
