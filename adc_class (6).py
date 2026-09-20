import time
import sys
import statistics
import spidev
import json

import RPi.GPIO as GPIO
from RPi.GPIO import HIGH, LOW, IN, OUT
import logging
from aq_lib.config_module import Config

logger = logging.getLogger( "aquila_logger" )

REG_ADC_CONTROL = 0x01
REG_DATA        = 0x02
REG_ID          = 0x05   
REG_ERROR       = 0x06
REG_CHANNEL     = 0x09
CHANNEL_0    = 0x09
CONFIG_0     = 0x19
REG_FILTER = 0x21

SPI_BUS = 0  # SPI bus number (e.g., 0 for SPI0)
SPI_DEVICE = 0  # Chip Select (CS) line (e.g., 0 for CE0)
SPI_SPEED_HZ = 100000  # SPI clock speed in Hz

# Define the GPIO pins you want to toggle
LED_PIN1 = 22
LED_PIN2 = 27

class OpticalRead():

    def __init__(self ):

        config = Config()
        self.LED_ON = [GPIO.LOW, GPIO.HIGH] [ config.optics["LED_ON" ] ]
        self.LED_OFF= [GPIO.LOW, GPIO.HIGH] [ config.optics["LED_OFF"] ]

        self.fam_channel = ( config.adc["famP"], config.adc["famN"], )
        self.rox_channel = ( config.adc["roxP"], config.adc["roxN"], )

        self.data_file = sys.stdout
        self.t0 = time.time()

        self.gpio = GPIO
        self.gpio.setwarnings(False) 
        self.gpio.setmode(GPIO.BCM) 

        # Set up the pins as output
        self.gpio.setup( LED_PIN1, OUT)
        self.gpio.setup( LED_PIN2, OUT)

        self.spi = spidev.SpiDev()
        self.spi.open( 0,0)
        self.spi.max_speed_hz = SPI_SPEED_HZ
        self.spi.mode = 0b11

        self.well_15 = False
        value = config.info.get("well_15")
        if (
            value is not None
            and value != 0
            and not (
                isinstance(value, str)
                and value.strip().lower() in ("0", "false")
            )
        ):
            self.well_15 = True

        # assuming the new PCB:
        self.adc_num = 1
        self.two_adcs = False
        self.both_channel_was_used = False
        value = config.info.get("two_adcs")
        if (
            value is not None
            and value != 0
            and not (
                isinstance(value, str)
                and value.strip().lower() in ("0", "false")
            )
        ):
            self.two_adcs = True
        self.data_both = [] # calling "both" channel fills up this structure
        self.FAM_enabled = False
        self.ROX_enabled = False
        if self.two_adcs:
            self.adc_num = 2
            self.spi.no_cs = True
            self.ADC1_CS = 8    # GPIO8 / physical CE0
            self.ADC2_CS = 23   # GPIO23
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(self.ADC1_CS, GPIO.OUT, initial=GPIO.HIGH)
            GPIO.setup(self.ADC2_CS, GPIO.OUT, initial=GPIO.HIGH)
            self.cs_list = [self.ADC1_CS, self.ADC2_CS]

        #assuming fast-settling filter:
        self.fast_settling = True
        if self.fast_settling:
            self.blink_num = 7
        else:
            self.blink_num = 10
            
        for i in range(self.adc_num):
            if self.two_adcs:
                GPIO.output(self.cs_list[i], GPIO.LOW)
            # 0x40 is Read bit. 

            reply = self.spi.xfer2( [ 0x40 + REG_ADC_CONTROL, 0x00, 0x00 ] )
            print ( "ADC control", "".join( [" %02x"%x for x in reply] ) ) 
            time.sleep ( 0.1 )

            reply = self.spi.xfer2( [ 0x40 + CHANNEL_0, 0x00, 0x00 ] )
            print ( "Channel 0", "".join( [" %02x"%x for x in reply] ) ) 
            time.sleep ( 0.1 )

            reply = self.spi.xfer2( [ 0x40 + CONFIG_0, 0x00, 0x00 ] )
            print ( "Config 0: ", "".join( [" %02x"%x for x in reply] ) ) 
                                    # confirmed returns 0x0870
                                    # 08 = Bipolar /Burnout /REF_BUFP
                                    # 70 = 0111.0000.  AIN_BUFM AIN_BUFM ref_sel=0b10, pga=0
            time.sleep ( 0.1 )

            # Changing FS buffer to 128 instead of 384
            if self.fast_settling:
                reply = self.spi.xfer2( [ 0x00 + REG_FILTER, 0x80, 0x00, 0x14 ] )
            else:
                reply = self.spi.xfer2( [ 0x00 + REG_FILTER, 0x06, 0x01, 0x40 ] )
            time.sleep ( 0.1 )

            reply = self.spi.xfer2( [ 0x40 + REG_FILTER, 0x00, 0x00, 0x00 ] )
            time.sleep ( 0.1 )
            print ( "Filter 0: ", "".join( [" %02x"%x for x in reply] ) ) 
                                    # 0x060180
                                    # 0000.0110.  0000.0001 1000.0000
                                    # 000 filter = sinc4
                                    #    0 Reject 60
                                    #     .000 Post filter
                                    #             0000.0 not used
                                    #                   001 0100.0000 
                                    #                     256 + 64 = 320
                                    # f_adc = f_clk / ( 32 * FS )
                                    #       = 60Hz settling time 66.82 (table 56. )

            # This is for writing: ~0x40. 
            # Config
            REF_SEL = 0b10  # Internal reference p. 91
            #reply = self.spi.xfer2( [ CONFIG_0, 0x08, 0x60 + 0b10000 ] ) # with buffer
            reply = self.spi.xfer2( [ CONFIG_0, 0x08, 0x00 + 0b10000 ] )
            time.sleep ( 0.1 )

            # ADC_CONTROL
            #                                Full power, continuous conversion ,internal 614.4kHz clock
            reply = self.spi.xfer2( [ 0x01, 0x01, 0x80  ] )
            time.sleep ( 0.1 )

            # CHANNEL_0
                            # EN = 1
                            # AINP = 0
                            # AINM = 1
            reply = self.spi.xfer2( [ CHANNEL_0, 0x80, 0x01 ] )

            if self.two_adcs:
                GPIO.output(self.cs_list[i], GPIO.HIGH)

    def read_ambient_temp(self): # THIS FUNCTION DOES NOT RESTORE THE SELECTED CHANNEL TO ITS PREVIOUS VALUE! RESTORES TO ROX!
        try:
            if self.two_adcs:
                self.ROX_enabled = False
                GPIO.output(self.cs_list[0], GPIO.LOW) # w14 is ONLY routed to the first ADC
            self.set_channel( 4, 1 )

            temp_list = []

            for i in range(5):

                got = False

                for attempt in range ( 20 ):

                    st = self.spi.xfer2( [ 0x40 | 0x00, 0x00 ] )        # read STATUS
                    if not ( st[1] & 0x80 ):                            # RDY low = ready
                        reply2 = self.spi.xfer2( [ 0x42 ] + [0x00, 0x00, 0x00] )
                        adc_value = 1000*self.convert ( reply2 )
                        got = True

                    if got:
                        break

                    time.sleep ( 0.001 )

                if not got:
                    adc_value = -123

                temp_list.append(adc_value)
                time.sleep ( 0.035 )

            if self.two_adcs:
                GPIO.output(self.cs_list[0], GPIO.HIGH)
            return temp_list
        finally:
            if self.two_adcs:
                    GPIO.output(self.cs_list[0], GPIO.LOW)
            self.set_channel( * self.rox_channel )
            if self.two_adcs:
                GPIO.output(self.cs_list[0], GPIO.HIGH)

    #only FAM is routed to the second ADC 
    def set_channel_dye( self, dye_name ):
        if dye_name.lower() == "fam": 
            if self.FAM_enabled:
                return
            else:
                if self.two_adcs:
                    GPIO.output(self.cs_list[1], GPIO.LOW)
                self.set_channel( * self.fam_channel )
                if self.two_adcs:
                    GPIO.output(self.cs_list[1], GPIO.HIGH)
                    self.FAM_enabled = True
        elif dye_name.lower() == "rox":
            if self.ROX_enabled:
                return
            else:
                if self.two_adcs:
                    GPIO.output(self.cs_list[0], GPIO.LOW)
                self.set_channel( * self.rox_channel )
                if self.two_adcs:
                    GPIO.output(self.cs_list[0], GPIO.HIGH)
                    self.ROX_enabled = True
        elif dye_name.lower() == "both" and self.two_adcs:
            if not self.ROX_enabled:
                GPIO.output(self.cs_list[0], GPIO.LOW)
                self.set_channel( * self.rox_channel )
                GPIO.output(self.cs_list[0], GPIO.HIGH)
                self.ROX_enabled = True
            if not self.FAM_enabled:
                GPIO.output(self.cs_list[1], GPIO.LOW)
                self.set_channel( * self.fam_channel )
                GPIO.output(self.cs_list[1], GPIO.HIGH)
                self.FAM_enabled = True
        else:
            logger.error( "Could not set channel, non valid dye: %s", dye_name )

    def set_channel( self, positive_channel, negative_channel ):
        # Datasheet p. 46
        # BYTE1   Enable(1) | Setup(3) | 0 | AINP43(2)
        # BYTE2   AINP3210(3)  | AINP(5)

        if not (0 <= positive_channel < 16): logger.error( "Requested ADC channel out of bounds" )
        if not (0 <= negative_channel < 16): logger.error( "Requested ADC channel out of bounds" )

        AINP_BITS_4_to_3 = ( positive_channel >> 3 ) & 0b00000011
        #                                                     xxx
        #                                                  <----- 5
        #                                                xxx
        AINP_BITS_2_to_0 = ( positive_channel << 5 ) & 0b11100000

        AINM_BITS_4_to_0 = ( negative_channel      ) & 0b00011111

        BYTE1 = 0x80 |  AINP_BITS_4_to_3
        BYTE2 = 0x00 |  AINP_BITS_2_to_0  | AINM_BITS_4_to_0

        reply = self.spi.xfer2( [ 0x00 + CHANNEL_0, BYTE1, BYTE2 ] )
        print ( "W Channel", "".join( [" %02x"%x for x in reply] ) ) 
        time.sleep ( 0.1 )

        # Read back what it is. 
        reply = self.spi.xfer2( [ 0x40 + CHANNEL_0, BYTE1, BYTE2 ] )
        print ( "R Channel", "".join( [" %02x"%x for x in reply] ) ) 
        time.sleep ( 0.1 )


    def convert( self, reply ):
        #code = int.from_bytes( reply[1:3 ], signed=True ) 
        code = ( reply[1]*256*256 + reply[2]*256 + reply[3] )  # p. 48

        return ( code / 2**23 - 1 ) * 2.5

  
    def read_config( self ):

        #print ( "STATUS register:", read_register( REG_STATUS     , 3 ) )

        length = [1,2,3,3,2,1,3,3,1,2,2,2,2,2,2,2,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3]

        #00 [0, 0]
        #01 [0, 0]             # ADC Control
        #02 [0, 124, 63, 108]
        #03 [0, 0, 0, 0]
        #04 [0, 0, 0]
        #05 [0, 20]
        #06 [0, 0, 0, 0]
        #07 [0, 0, 0, 64]
        #08 [0, 0]
        #09 [0, 128, 1]
        #0a [0, 0, 1]
        #0b [0, 0, 1, 0]
        #0c [0, 0, 0, 0]
        #0d [0, 0, 1, 0]
        #0e [0, 0, 1, 0]
        #0f [0, 0, 1, 0]

        for cmd in range ( 16 ):
            reply = self.spi.xfer2( [ 0x40+cmd ] + [0x00]* length[cmd] )
            print (  "%02x"%cmd, reply )
            if cmd == 2: time.sleep ( 0.10 )
            else: time.sleep ( 0.01 )

        print ()

    def print_result ( self, reply1, reply2, adc_value, labels = []):

        def my_print( x ): return print ( x, end = " ", file = self.data_file )
        if not reply2: reply2 = [254, 254, 254, 254]

        my_print ( "%6.3f"%( ( time.time() - self.t0 ) )           )
        #my_print ( ".".join ( [ "%02x"%r for r in reply1])    )
        my_print ( ".".join ( [ "%02x"%r for r in reply2])    )
        my_print ( "%.5f"%adc_value                           )
        print ( *labels, sep=" ", file = self.data_file )

    def mask_data(self): # outputs new optics data in the legacy format 

        # increase blink_num samples to full 10 samples via padding with extra samples that are averages of the last four samples
        avg_sum_rox = 0
        avg_sum_fam = 0
        avg_num_rox = 0
        avg_num_fam = 0
        avg_num = 4
        self.data_both2 = []

        for i in range(len(self.data_both)):
            self.data_both2.append(self.data_both[i])
            if self.blink_num - i % self.blink_num <= avg_num:
                if self.data_both[i][2] != -123:
                    avg_sum_rox += self.data_both[i][2]
                    avg_num_rox = avg_num_rox + 1
                if self.data_both[i][3] != -123:
                    avg_num_fam = avg_num_fam + 1
                    avg_sum_fam += self.data_both[i][3]
            
            if self.data_both[i][2] == -123:
                if i == 0:
                    self.data_both[i][2] = 2.0
                else:
                    self.data_both[i][2] = self.data_both[i-1][2]
            if self.data_both[i][3] == -123:
                if i == 0:
                    self.data_both[i][3] = 2.1
                else:
                    self.data_both[i][3] = self.data_both[i-1][3]


            if i % self.blink_num == self.blink_num - 1:
                if avg_num_rox == 0:
                    avg_num_rox = 1
                    avg_sum_rox = 2.0
                if avg_num_fam == 0:
                    avg_num_fam = 1
                    avg_sum_fam = 2.1
                for k in range(10 - self.blink_num):
                    self.data_both2.append([self.data_both[i][0], self.data_both[i][0], avg_sum_rox / avg_num_rox, avg_sum_fam / avg_num_fam, self.data_both[i][4], self.data_both[i][5], self.data_both[i][6], self.data_both[i][7], self.data_both[i][8], self.data_both[i][9], self.data_both[i][10]])
                avg_sum_rox = 0
                avg_sum_fam = 0
                avg_num_rox = 0
                avg_num_fam = 0

        #increase number of blinks from 2 to 3 via adding a fake first blink; each blink is 20 datapoints
        self.data_both = self.data_both2
        self.data_both3 = []
        for i in range(len(self.data_both2)): # should be divisble by 10 now
            if i%40 == 0:
                for j in range(20):
                    self.data_both3.append([self.data_both[i+j][0], self.data_both[i+j][0], (self.data_both[i+j][2] + self.data_both[i+20+j][2]) / 2, (self.data_both[i+j][3] + self.data_both[i+20+j][3]) / 2, self.data_both[i+j][4], self.data_both[i+j][5], self.data_both[i+j][6], self.data_both[i+j][7], self.data_both[i+j][8], self.data_both[i+j][9], self.data_both[i+j][10]])
            self.data_both3.append(self.data_both2[i])

        #fam is off then on, which violates the lagacy arangement. Thus, each ten samples have to be swapped
        # list of lists x. The task is to swap x[20*k+i][3] and x[20*k+10+i][3] for k from zero to len(x)/20 (excluding the last one) and i from zero to 9
        x = self.data_both3
        for k in range(len(x) // 20):
            for i in range(10):
                x[20*k+i][3], x[20*k+10+i][3] = x[20*k+10+i][3], x[20*k+i][3]

    def out_data ( self ): # outputs new optics data in the legacy format
        logger.info("Checking out_data conds")
        if not self.both_channel_was_used:
            return
        if not self.two_adcs: # data is already out, there is nothing to do
            return

        if self.well_15:
            self.scan_num = 21 # this assumes 15 wells
        else: self.scan_num = 6 # this assumes 4 wells

        logger.info("Scan_num = %d\n", self.scan_num)

        self.mask_data()
        self.data_both = self.data_both3

        if self.scan_num == 21:
            legacy_well_one = 9
            rox_well_one = legacy_well_one
            fam_well_one = rox_well_one - 2
        else:
            rox_well_one = 0
            fam_well_one = 2
        passes_num = int(len(self.data_both) / self.scan_num / 60)
        logger.info("Passes num = %d\n", passes_num)
        for i in range (passes_num):
            true_pass_num = i
            if i == 0: true_pass_num = -1
            for k in range(6):
                logger.info("k = %d", k)
                if k < 4: # rox comes first
                    for j in range(60):
                        #self.print_result( "", reply2, adc_value, labels )
                        rox_index = (i*self.scan_num+rox_well_one+k)*60 + j
                        if self.data_both[rox_index][2] == -123:
                            if j == 0:
                                self.data_both[rox_index][2] = 2.0
                            else:
                                self.data_both[rox_index][2] = self.data_both[rox_index-1][2]
                        self.print_result( "", self.data_both[rox_index][0], self.data_both[rox_index][2], [(j // 10 + 1) % 2, "rox", true_pass_num, k] )

                if k > 1: # fam comes second
                    for j in range(60):
                        fam_index = (i*self.scan_num+fam_well_one+(k-2))*60 + j
                        if self.data_both[fam_index][3] == -123:
                            if j == 0:
                                self.data_both[fam_index][3] = 2.0
                            else:
                                self.data_both[fam_index][3] = self.data_both[fam_index-1][3]
                        self.print_result( "", self.data_both[fam_index][1], self.data_both[fam_index][3], [(j // 10 + 1) % 2, "fam", true_pass_num, k] )
        self.data_both = []

    def capture_blink( self, channel, tag1 = None, tag2=None  ):
        if channel == "both" and self.two_adcs:
            self.both_channel_was_used = True
            FAM_LED_PIN = 27
            ROX_LED_PIN = 22
            pcr_t0 = time.time()

            for j in range ( 4 * self.blink_num ): # adc1 is wried to rox (and fam); adc2 - to fam
                if (j%(2*self.blink_num))==0:
                    self.gpio.output( ROX_LED_PIN, self.LED_ON )
                    self.gpio.output( FAM_LED_PIN, self.LED_OFF )
                    led_state_nr = 1
                elif (j%(2*self.blink_num))==self.blink_num:
                    self.gpio.output( ROX_LED_PIN, self.LED_OFF )
                    self.gpio.output( FAM_LED_PIN, self.LED_ON )
                    led_state_nr = 0

                GPIO.output( self.cs_list[0], GPIO.HIGH )
                GPIO.output( self.cs_list[1], GPIO.HIGH )

                dt = time.time() - pcr_t0
                labels = [ led_state_nr, channel, tag1, tag2 ]

                time.sleep ( max ( 0, j/60 - dt ) )

                got_rox = False
                got_fam = False
                reply2 = None
                reply2_adc2 = None

                for attempt in range ( 7 ):

                    if not got_rox:
                        GPIO.output( self.cs_list[0], GPIO.LOW )
                        st = self.spi.xfer2( [ 0x40 | 0x00, 0x00 ] )        # read STATUS
                        if not ( st[1] & 0x80 ):                            # RDY low = ready
                            reply2 = self.spi.xfer2( [ 0x42 ] + [0x00, 0x00, 0x00] )   # rox
                            adc_value = 1000*self.convert ( reply2 )                   # rox
                            got_rox = True
                        GPIO.output( self.cs_list[0], GPIO.HIGH )

                    if not got_fam:
                        GPIO.output( self.cs_list[1], GPIO.LOW )
                        st = self.spi.xfer2( [ 0x40 | 0x00, 0x00 ] )        # read STATUS
                        if not ( st[1] & 0x80 ):                            # RDY low = ready
                            reply2_adc2 = self.spi.xfer2( [ 0x42 ] + [0x00, 0x00, 0x00] )  # fam
                            adc_value_adc2 = 1000*self.convert ( reply2_adc2 )             # fam
                            got_fam = True
                        GPIO.output( self.cs_list[1], GPIO.HIGH )

                    if got_rox and got_fam:
                        break

                    time.sleep ( 0.001 )

                if not got_rox:
                    adc_value = -123
                    reply2 = [255, 255, 255, 255]
                if not got_fam:
                    adc_value_adc2 = -123
                    reply2_adc2 = [255, 255, 255, 255]

                self.data_both.append([reply2, reply2_adc2, adc_value, adc_value_adc2, led_state_nr, channel, tag1, tag2, pcr_t0, self.t0, time.time()])

            self.gpio.output( ROX_LED_PIN, self.LED_OFF )
            self.gpio.output( FAM_LED_PIN, self.LED_OFF )
            return

        if channel == "fam": LED_PIN = 27
        elif channel == "rox": LED_PIN = 22
        else:
            self.print_result("Invalid channel!")
            return

        pcr_t0 = time.time()

        for j in range ( 1 * 60 ):  # 2 seconds at 60Hz.
            if (j%20)==0:
                self.gpio.output( LED_PIN, self.LED_ON )
                led_state_nr = 1
            elif (j%20)==10:
                self.gpio.output( LED_PIN, self.LED_OFF )
                led_state_nr = 0

            dt = time.time() - pcr_t0
            time.sleep ( max ( 0, j/60 - dt ) )

            if channel == "fam": cs_pin_index = 1
            else: cs_pin_index = 0

            labels = [ led_state_nr, channel, tag1, tag2 ]

            got = False
            reply2 = None

            for attempt in range ( 7 ):

                if self.two_adcs:
                    GPIO.output( self.cs_list[cs_pin_index], GPIO.LOW )

                st = self.spi.xfer2( [ 0x40 | 0x00, 0x00 ] )        # read STATUS
                if not ( st[1] & 0x80 ):                            # RDY low = ready
                    reply2 = self.spi.xfer2( [ 0x42 ] + [0x00, 0x00, 0x00] )
                    adc_value = 1000*self.convert ( reply2 )
                    got = True

                if self.two_adcs:
                    GPIO.output( self.cs_list[cs_pin_index], GPIO.HIGH )

                if got:
                    break

                time.sleep ( 0.001 )

            if not got:
                adc_value = -123
                reply2 = [255, 255, 255, 255]

            self.print_result( "", reply2, adc_value, labels )

    def clean_up( self ):
        print ( "Caught exception, turning off led" )
        self.gpio.output( LED_PIN1, self.LED_OFF)   # Turn pin 22 off
        self.gpio.output( LED_PIN2, self.LED_OFF)   # Turn pin 22 off
        raise e


def main():
    adc = OpticalRead()

    adc.read_config()

if __name__ == "__main__":
    main()
