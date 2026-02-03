
import logging

logger = logging.getLogger( "aquila" )

def thermal_engine( actions, meer, callback, logfile, stop_event ):

    for args in actions:
        logger.info ( "Args %s", args.__str__() )
        if stop_event and stop_event.is_set():
            raise Exception("Forced to exit")

        if args[0] == "pcr_fanon":
            callback( args )
            continue

        if args[0] == "pcr_fanoff":
            callback( args )
            continue

        if args[0] == "optics":
            callback( args )
            continue

        if args[0] == "call":
            method_name = args[1]
            arguments = args[2]
            fun = getattr( meer, method_name )
            #print ( fun )
            fun( * arguments )
            continue
        
        name, n, last_temp, setpoint, duration, last_time = args

        if name == "hold":
            logger.info (f"{n:2} Hold            {setpoint} for {duration:6.2f} seconds until {last_time:.2f}")
            meer.log ( endtime = last_time, logfile = logfile )

        elif name == "ramp":
            logger.info( f"{n:2} Ramp from {last_temp} to {setpoint} for {duration:6.2f} seconds until {last_time:.2f}")
            meer.change_setpoint ( setpoint )
            meer.log ( endtime = last_time, logfile = logfile )

        elif name == "disable":
            logger.info( f"{n:2} disable for {duration:6.2f} seconds until {last_time:.2f}")
            meer.output_stage_enable ( 0 )
            meer.log ( endtime = last_time, logfile = logfile )
            
        elif name == "enable":
            logger.info( f"{n:2} enable for {duration:6.2f} seconds until {last_time:.2f}")
            meer.output_stage_enable ( 1 )
            meer.log ( endtime = last_time, logfile = logfile )

        else:
            meer.output_stage_enable ( 0 )
            logger.error ("Unknown command.")
            break
    return

