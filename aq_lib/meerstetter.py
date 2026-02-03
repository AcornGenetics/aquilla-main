import time
import struct
import re
import os
import logging

from serial import Serial
from serial import SerialException
from serial.tools import list_ports

from .mecrc16 import crc16_list

global t0

def set_time():
    global t0
    t0 = time.time()

    return t0

def get_time():
    return time.time() - t0


def deprecate( func ):
    def wrapper ( self, *args, **kwargs ):
        print ( "Deprecated: ", func.__name__ )
        result = func ( self, *args, **kwargs )
        return result
    return wrapper

def float_factory( self, func_name, parid ):

    def get_func( obj, inst = None): return obj.get_parid_float( parid, inst = inst)
    def set_func( obj, value, inst = None): return obj.set_parid_float( parid, value, inst)

    getter = get_func.__get__( self, MeerStetter )
    setter = set_func.__get__( self, MeerStetter )
    setattr( self, "get"+func_name, getter )
    setattr( self, "set"+func_name, setter )
    return ( getter, setter )

def long_factory( self, func_name, parid ):

    def get_func( obj, inst = None): return obj.get_parid_long( parid, inst = inst)

    getter = get_func.__get__( self, MeerStetter )
    setattr( self, "get"+func_name, getter )
    return ( getter, )


    


class MeerStetter( Serial ):

    def __init__( self, *args, **kwargs ):
        
        self.commands = self.load_header()
        
        if "baudrate" not in kwargs:
            kwargs["baudrate"] = 57600
        
        super ( Serial, self ).__init__( *args, **kwargs )

        self.registers = [
            ( "ObjectTemperature"          , 1000  ),
            ( "SinkTemperature"            , 1001  ),
            ( "TargetObjectTemperature"    , 1010  ),
            ( "RampNominalObjectTemperature", 1011 ),
            ( "ThermalPowerModelCurrent"   , 1012  ),
            ( "ActualOutputCurrent"        , 1020  ),
            ( "ActualOutputVoltage"        ,1021   ),
            ( "PIDLowerLimitation"         ,1030   ),
            ( "PIDUpperLimitation"         ,1031  ),
            ( "PIDControlVariable"         ,1032 ),
            ( "ObjectSensorResistance"     ,1042 ),
            ( "SinkSensorResitance"        ,1043 ),
            ( "SinkSensorTemperature"      ,1044 ),
            ( "DriverInputVoltage"         ,1060 ),
            ( "MedVInternalSupply"         ,1061 ),
            ( "3_3VInternalSupply"         ,1062 ),
            ( "BasePlateTemperature"       ,1063 ),
            ( "ParallelActualOutputCurrent",1090 ),
            ( "FanRelativeCoolingPower"    ,1100 ),
            ( "FanNominalFanSpeed"         ,1101 ),
            ( "FanActualFanSpeed"          ,1102 ),
            ( "FanActualPwmLevel"          ,1103 ),
            ( "CurrentLimitation",         2030 ),
            ( "VoltageLimitation",         2031 ),
            ( "CurrentErrorThreshold",     2032 ),
            ( "VoltageErrorThreshold",     2033 ),
            ( "ComWatchDogTimeout",        2060 ),
            ( "TargetObjectTemp"         , 3000 ),
            ( "CoarseTempRamp"           , 3003 ),
            ( "ProximityWidth"           , 3002 ),
            ( "Kp"                       , 3010 ),
            ( "Ti"                       , 3011 ),
            ( "Td"                       , 3012 ),
            ( "DPartDampPT1"             , 3013 ),
            ( "ModelizationMode"         , 3020 ),
            ( "PeltierMaxCurrent"        , 3030 ),
            ( "PeltierMaxVoltage"        , 3031 ),
            ( "PeltierCoolingCapacity"   , 3032 ),
            ( "PeltierDeltaTemperature"  , 3033 ),
            ( "ResistorResistance"       , 3040 ),
            ( "ResistorMaxCurrent"       , 3041 ),
        ]

        self.attributes = [
                (
                    func_name, 
                    parid, 
                    float_factory ( self, func_name, parid )
                )
                for func_name, parid in self.registers
            ]


        self.long_registers = [
            ("DeviceType",          100 ),
            ("HW_version",          101 ),
            ("Serial_nr",           102 ),
            ("FW_version",          103 ),
            ("dev_Status",          104 ),
            ("Error_nr.",           105 ),
            ("Error_instance",      106 ),
            ("Error_Param",         107 ),
            ("ObjectSensorRawADCValue",     1040 ),
            ("SinkSensorRawADCValue",       1041 ),
            ("FirmwareVersion",             1050 ),
            ("FirmwareBuildNumber",         1051 ),
            ("HardwareVersion",             1052 ),
            ("SerialNumber",                1053 ),
            ("ErrorNumber",                 1070 ),
            ("ErrorInstance",                 1071 ),
            ("ErrorParameter",              1072 ),
            ("DriverStatus",                1080 ),
            ("ParameterSystemFlashStatus",  1081 ),
            ("TemperatureIsStable",         1200 ),
        ]

        self.long_attributes = [
                (
                    func_name, 
                    parid, 
                    long_factory ( self, func_name, parid )
                )
                for func_name, parid in self.long_registers
            ]

    common_params = [\
       (100 ,"DeviceType"),
       (101 ,"HW version"),
       (102 ,"Serial nr"),
       (103 ,"FW version"),
       (104 ,"dev Status"),
       (105 ,"Error nr."),
       (106 ,"Error instance"),
       (107 ,"Error Param"),
    ]

    def get_common_params( self ):
        for par_id, name in self.common_params:
            yield par_id, name, self.get_parid_long( par_id, 1 ),



    def print_info( self ):
        device_info = self.get_info()
        device_type = self.get_device_type()
        device_snr = self.get_snr()
        print ( "Meerstetter info string:", device_info )
        print ( "Meerstetter device type string:", device_type )
        print ( "Meerstetter device snr:", device_snr )
        for par_id, name, value in self.get_common_params():
            print ( f"Meerst. parid {par_id} ({name}): {value}")
        print ( "Meerst. parid 1053:", self.get_parid( 1053,1 ) )
        print ( "Meerst. parid 1000:", self.get_parid( 1000,1 ) )

    @staticmethod
    def list_meer( vid=0x0403, pid=0x6015 ):
        for el in list_ports.comports():
            print( el )
            logging.debug("Meer: comports_el: ", el)
            if ( el.vid, el.pid ) == ( vid, pid ):
                #print ( "Found vid, pid:", (vid, pid ) )
                #self.logfile.debug("Found vid,pid: ", (vid,pid))
                meer = MeerStetter( el.device, baudrate=57600, timeout=1 )

                device_info = meer.get_info()
                device_type = meer.get_device_type()
                device_snr = meer.get_snr()
                print ( "Meerstetter info string:", device_info )
                print ( "Meerstetter device type string:", device_type )
                print ( "Meerstetter device snr:", device_snr )
                print ( "Meerstetter parid long 100:", meer.get_parid_long( 100,1 ) )
                print ( "Meerstetter parid long 101:", meer.get_parid_long( 101,1 ) )
                print ( "Meerstetter parid long 102:", meer.get_parid_long( 102,1 ) )
                print ( "Meerstetter parid long 1053:", meer.get_parid( 1053,1 ) )
                print ( "Meerstetter parid long 1000:", meer.get_parid( 1000,1 ) )
                meer.close()
                print()

    def initialize_meerstetter( self ):
        ### for testing we dont need this block
        #TODO add logging functionality to tec
        """temp_log_dir = "Temperature_logs"
        os.makedirs(temp_log_dir, exist_ok = True)
        log_filename = self.generate_filename()
        log_file_path = os.path.join(temp_log_dir, log_filename)
        self.fd = open (log_file_path, "w")"""
        temp_log_dir = "logs"
        os.makedirs(temp_log_dir, exist_ok = True)
        log_file_path = os.path.join(temp_log_dir, "temp_templogs.log")
        self.fd = open (log_file_path, "w")

        #self.logfile.info( "Initializiing meerstetter" )
        print("INIT MEER")

        self.device = MeerStetter.find_meer( 0x0403, 0x6015, 1161)

        if self.device == None:
            #self.logfile.error( "Could not find meerstetter")
            print("Could not find meer")
            raise Exception ( "Couldn't find the device" )
        else:
            #self.logfile.debug( "Found meerstetter")
            print("found meer")
        
        self.meer = MeerStetter(self.device, baudrate = 57600, timeout = 1 )
        
        time.sleep ( 2 )

        try:
            tec_ramprate = 4
            self.change_ramprate( tec_ramprate )
            self.change_max_current( 2 )
            #self.logfile.debug( "Set ramp rate to %d" % tec_ramprate )

        except Exception as e:
            #self.logfile.error( "Caught exception: ", e)
            raise Exception("Caught exception in inititalize meerstetter")

        #self.logfile.info( "Meerstetter initilization successful" )
        print("INIT GOOD")
        return

    def turn_on_tec ( self ):
        try:
            #self.logfile.debug( "Turn on tec chip" )
            self.output_stage_enable( 1 )
            print("Tec on")
            #self.logfile.debug( "Tec chip on" )
        except Exception as e:
            #self.logfile.error("Tec chip failed to enable: ", e)
            raise Exception ("Tec chip failed to enable ")
        
    def turn_off_tec( self ):
        try:
            #self.logfile.debug( "Turn off tec chip" )
            self.output_stage_enable( 0 )
            print("Tec off")
            #self.logfile.debug( "Tec chip off" )
        except Exception as e:
            #self.logfile.error("Tec chip failed to disable: ", e)
            raise Exception ("Tec chip failed to disable ")
        finally:
            self.output_stage_enable( 0 )

    def set_temperature( self, temp = 1 ):
        try:
            #self.logfile.info( "Temp set to: %dC" % temp )
            print("Temp set to: %dC" % temp)
            self.change_setpoint( temp )
        except Exception as e:
            #self.logfile.error("Tec chip failed to set temp: ", e)
            print("Tec failed to set temp: ", e)
            self.output_stage_enable( 0 )
            raise Exception ("Tec chip failed to set temp ")

    def log_temp( self, duration ):
        self.s0 = set_time()
        self.log( get_time() + duration, self.fd )

        return

    def get_current_temp ( self ): return self.get_temp()

    def log( self, endtime, logfile ):

        send_cmds = [
            self.compile( 1000, 1, seq_nr=1543 ),  # Object Temperature
            self.compile( 1000, 2, seq_nr=1544 ),
            self.compile( 3000, 1, seq_nr=1545 ),  # Target temperature
            self.compile( 3000, 2, seq_nr=1546 ),
            self.compile( 1011, 1, seq_nr=1545 ),  # Ramp Nominal
            self.compile( 1011, 2, seq_nr=1546 ),
            self.compile( 1020, 1, seq_nr=1547 ),  # Actual Output Current
            self.compile( 1020, 2, seq_nr=1548 ),
            self.compile( 1021, 1, seq_nr=1549 ),  # Actual Output Voltage
            self.compile( 1021, 2, seq_nr=1550 ),
        ]

        condition = True
        while (condition):
            t = get_time()
            if t>=endtime:
                condition = False
                break
            print ( f"{t:.2f} ", end=" ", file = logfile )
            for cmd in send_cmds:
                try:
                    self.write ( cmd )
                    reply = self.read(20)
                    value = self.reply_to_float ( reply )
                    if value == None:
                        reply = self.read(20)
                        value = self.reply_to_float ( reply )
                    print ( f"{value:.6f}", file=logfile, end = " " )
                except SerialException as se:
                    logging.error("Serial Exception, continuing. %s", se.__str__() )
                except Exception as e:
                    logging.error("Unknown exception in meerstetter logger %s", e.__str__() )
                
                time.sleep ( 0.05 )  # original 0.05 Mon 10 Mar 14:22:32 PDT 2025
            print ( file = logfile, flush = True )

    @staticmethod
    def find_meer( vid, pid, search_device_type ):
        for el in list_ports.comports():

            if ( el.vid, el.pid ) == ( vid, pid ):
                print ( "Found vid, pid: %04x, %04x"%(vid, pid ) )
                meer = MeerStetter( el.device, baudrate=57600, timeout=1 )
                print ( "Created class" )
                device_info = meer.get_info()
                print ( "Get info" )
                time.sleep ( 0.1 )
                device_type = meer.get_parid_long( 100,1 )
                print ( "Device type", device_type )
                meer.close()
                if device_type == search_device_type:
                    device = el.device
                    #print ( el )
                    #print ( device_info )
                    #print ( device_type )
                    
                    return device
        return None

    @staticmethod
    def load_header ( fname = None):

        if fname is None:
            fname = "MeCom.h"
        script_dir = os.path.dirname(__file__)
        fname = os.path.join(script_dir, fname)
        pattern = r"#define MeCom_TEC_(\w+)\(.*ParValue([fl])\((\w+), +(\d*).*\)"

        prog = re.compile ( pattern )

        commands = {}

        with open ( fname, "r" ) as fp:
            for line in fp:

                result = prog.match ( line )
                if result:

                    name = result.group(1)
                    v_type = result.group(2)
                    parid = result.group(4)

                    commands[ int(parid) ] = [ name, v_type ]

        return commands

    @staticmethod
    def load_header_common ( fname = None):

        if fname is None:
            fname = "MeCom.h"

        pattern = r"#define MeCom_COM_(\w+)\(.*ParValue([fl])\((\w+), +(\d*).*\)"

        prog = re.compile ( pattern )

        commands = {}

        with open ( fname, "r" ) as fp:
            for line in fp:

                result = prog.match ( line )
                if result:

                    name = result.group(1)
                    v_type = result.group(2)
                    parid = result.group(4)

                    commands[ int(parid) ] = [ name, v_type ]

        return commands

    def change_setpoint( self, temperature ):       return self.setTargetObjectTemp( temperature )
    def change_ramprate( self, ramprate ):          return self.setCoarseTempRamp( ramprate )
    def change_max_current( self, current ):        return self.setPeltierMaxCurrent( current )
    def change_max_peltier_current( self, current ):return self.setPeltierMaxCurrent ( current )
    def change_max_voltage( self, voltage ):        return self.setPeltierMaxVoltage( voltage )
    def change_current_error_threshold( self, current ): return self.setCurrentErrorThreshold( current )
    def set_max_current(self, inst, value):         return self.setPeltierMaxCurrent( inst, value )
    def set_max_voltage(self, inst, value):         return self.setPeltierMaxVoltage( inst, value )
    def set_error_voltage_threshold(self, inst, value): return self.setVoltageErrorThreshold( inst,value)
#    def set_Kp(self,inst,value):                    return self.setKp(inst,value)
#    def set_Ti(self,inst,value):                    return self.setTi(inst,value)
#    def set_Td(self,inst,value):                    return self.setTd(inst,value)

    def get_target_object_temp(self, inst = None):  return self.getTargetObjecTemp(inst)
    def get_max_current(self, inst = None):         return self.getCurrentLimitation(inst)
    def get_max_peltier_current(self, inst = None): return self.getPeltierMaxCurrent(inst)
    def get_max_voltage(self, inst = None):         return self.getVoltageLimitation(inst)
    def get_temp( self, inst = None ):              return self.getObjectTemperature (inst)
    def set_max_temp_change( self, inst, value ):   return self.set_wrapper ( 4012, inst, value )
    def get_max_temp_change( self, inst = None ):   return self.get_parid_float ( 4012, inst )
#    def get_Kp(self,inst,value):                    return self.getKp(inst,value)
#    def get_Ti(self,inst,value):                    return self.getTi(inst,value)
#    def get_Td(self,inst,value):                    return self.getTd(inst,value)

    def set_wrapper(self, parid, value, inst):

        self.set_parid_float( parid , value, inst)
        reply = self.read(24)
        return reply


    def compile(self, parid, inst, seq_nr = 1543):
        cmd = b'#00'
        cmd += b'%04X'%seq_nr
        cmd += b'?VR'
        cmd += b'%04X'%parid
        cmd += b'%02X'%inst
        cmd += b'%04X'%crc16_list ( 0, cmd )
        cmd += b'\r'

        return cmd

    def compile_set(self, parid, inst, seq_nr = 1543):
        cmd = b'#00'
        cmd += b'%04X'%seq_nr
        cmd += b'?VR'
        cmd += b'%04X'%parid
        cmd += b'%02X'%inst
        cmd += b'%04X'%crc16_list ( 0, cmd )
        cmd += b'\r'

        return cmd

    """
    reset
    Resets the TEC.

    Example:

        tx_data b'#0015BFRSFECE'
        Reply:  b'!0015BFFECE\r'
    """

    def reset( self ):
        tx_data = b'#00'
        tx_data += b'15BF'   # Sequence nr semi-arbitrary.
        tx_data += b'RS'

        checksum = crc16_list ( 0, tx_data )
        tx_data += b"%04X"%checksum # 4

       # print( "tx_data", tx_data )
        self.write( tx_data )
        self.write ( b'\r' )

        reply = self.poll_to( b"\r", 32)
        #print ( "Reply: ", reply )

        return reply


    def get_device_type( self ): return self.get_param( 100 )
    def get_snr( self ): return self.get_param( 102 )

    def get_param( self, param ):

        cmd = f'#00{param:04x}?IF'.encode()
        #print ( "Cmd: ", cmd )
        self.write ( cmd )
        checksum = crc16_list ( 0, cmd )
        self.write ( b'%4X'%checksum )
        self.write ( b'\r' )
        reply = self.read ( 64 )
        if len(reply)> 32:
            print ( "Warning, reply longer than expected ( 32 )", reply )
        return reply

    def get_info( self ):

        cmd = b'#0015BF?IF'
        self.write ( cmd )
        checksum = crc16_list ( 0, cmd )
        self.write ( b'%4X'%checksum )
        self.write ( b'\r' )
        time.sleep ( 0.5 )
        reply = self.read ( 32 )
        return reply

    def poll_to ( self, eof_char, max_length = 32 ):
        reply_str = bytes(b'')
        for _ in range ( max_length ):
            reply = self.read(1)
            if reply is None:
                raise Exception ("No reply")
            reply_str += reply
            if reply == eof_char:
                break

        return reply_str

    def reply_to_long ( self, reply ):
        try:
            l_number = bytes.fromhex(reply[7:15].decode('utf-8') )
        except Exception as e:
            #print ( "Exception:", e, "Reply", reply )
            #print ( " l_number = bytes.fromhex(reply[7:15].decode('utf-8') ) " )
            #raise e
            return None
        long_number = struct.unpack('!l', l_number )
        return long_number[0]

    def reply_to_float ( self, reply ):
        try:
            f_number = bytes.fromhex(reply[7:15].decode('utf-8') )
            float_number = struct.unpack('!f', f_number )
            return float_number[0]
        except Exception as e:
            print ( "Exception caught reply: ", reply )
            #raise ( e ) 
            return None

    def set_parid_long( self, parid, inst, value: int ):
        tx_data = b'#00'
        tx_data += b'15BF'
        tx_data += b'VS'
        tx_data += b"%04X"%parid  # 4
        tx_data += b'%02d'%inst

        long_bytes = struct.pack ( "!l", value )
        #print ( long_bytes.hex().upper() )
        tx_data += long_bytes.hex().upper().encode()

        checksum = crc16_list ( 0, tx_data )
        tx_data += b"%04X"%checksum # 4

        #print( "tx_data", tx_data )
        self.write( tx_data )
        self.write ( b'\r' )

    def set_parid_float( self, parid, value: float, inst=None ):
        #print ( f"set_parid_float( self, {parid}, {value}: float, {inst}=None ):" )

        if inst == None:
            return (
                    self.set_parid_float( parid, value,1 ),
                    self.set_parid_float( parid, value,2 ),
            )

        tx_data = b'#00'
        tx_data += b'15BF'
        tx_data += b'VS'
        tx_data += b"%04X"%parid  # 4
        tx_data += b'%02d'%inst

        float_bytes = struct.pack ( "!f", value )
        #print ( float_bytes.hex().upper() )
        tx_data += float_bytes.hex().upper().encode()

        checksum = crc16_list ( 0, tx_data )
        tx_data += b"%04X"%checksum # 4

        #print( "tx_data", tx_data )g
        self.write( tx_data )
        self.write ( b'\r' )

        reply = self.poll_to( b"\r", 32)
        checksum = crc16_list ( 0, reply[:-5] )
        #print ( "0x%04X"%checksum, "<->", reply[-5:-1] )

        return checksum


    def get_parid_float( self, parid, inst ):

        if inst == None:
            return (
                    self.get_parid_float( parid, 1 ),
                    self.get_parid_float( parid, 2 ),
            )

        send_cmd = self.compile( parid, inst, seq_nr=1543 )
        self.write ( send_cmd )

        reply = self.poll_to( b"\r", 32)
        checksum = crc16_list ( 0, reply[:-5] )
        #print ( "0x%04X"%checksum, "<->", reply[-5:-1] )

        return self.reply_to_float ( reply )

    def get_parid_long( self, parid, inst ):

        if inst == None:
            return (
                    self.get_parid_long( parid, 1 ),
                    self.get_parid_long( parid, 2 ),
            )

        send_cmd = self.compile( parid, inst, seq_nr=1543 )
        self.write ( send_cmd )

        reply = self.poll_to( b"\r", 32)
        checksum = crc16_list ( 0, reply[:-5] )
        #print ( "Get parid long:", parid, reply )
        #print ( f"0x{checksum:04X}<->{reply[-5:-1]}")

        return self.reply_to_long ( reply )

    def get_parid( self, parid, inst ):

        send_cmd = self.compile( parid, inst, seq_nr=1543 )
        self.write ( send_cmd )

        reply = self.poll_to( b"\r", 32)
        checksum = crc16_list ( 0, reply[:-5] )
        #print ( f"0x{checksum:04X}<->{reply[-5:-1]}")

        return reply

    def enable ( self, stage, state ):
        self.set_parid_long ( 2010, stage, state )
        reply = self.read(12)
        #print ( reply )

    def output_stage_enable( self, state ):

        self.set_parid_long ( 2010, 1, state )
        reply = self.read(12)
        #print ( reply )
        self.set_parid_long ( 2010, 2, state )
        reply = self.read(12)
        #print ( reply )


def main():

    MeerStetter.list_meer()

    return

def main2():

    meer = MeerStetter( "/dev/ttyUSB0", baudrate = 57600, timeout = 1)

    print ( meer.commands[3000] )

    meer.get_parid_float(3000, 0)

if __name__ == "__main__":
    main()
