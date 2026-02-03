import time
import sys
import statistics
import spidev

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

    def set_channel_dye( self, dye_name ):

        if dye_name.lower() == "fam": 
            self.set_channel( * self.fam_channel )
        elif dye_name.lower() == "rox":
            self.set_channel( * self.rox_channel )
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

    def print_result ( self, reply1, reply2, adc_value, labels = [] ):

        def my_print( x ): return print ( x, end = " ", file = self.data_file )

        my_print ( "%6.3f"%( ( time.time() - self.t0 ) )           )
        #my_print ( ".".join ( [ "%02x"%r for r in reply1])    )
        my_print ( ".".join ( [ "%02x"%r for r in reply2])    )
        my_print ( "%.5f"%adc_value                           )
        print ( *labels, sep=" ", file = self.data_file )

    def capture_blink( self, channel, tag1 = None, tag2=None  ):
        if channel == "fam": LED_PIN = 27
        elif channel == "rox": LED_PIN = 22

        pcr_t0 = time.time()

        for j in range ( 1 * 60 ):  # 2 seconds at 60Hz.
            if (j%20)==0:
                self.gpio.output( LED_PIN, self.LED_ON )
                led_state_nr = 1
            elif (j%20)==10:
                self.gpio.output( LED_PIN, self.LED_OFF )
                led_state_nr = 0

            dt = time.time() - pcr_t0

            labels = [ led_state_nr, channel, tag1, tag2 ]

            #reply1 = self.spi.xfer2( [ 0x41 ] + [0x00,0x00, ] )
            time.sleep ( max ( 0, j/60 - dt ) )
            reply2 = self.spi.xfer2( [ 0x42 ] + [0x00,0x00, 0x00] )
            adc_value = 1000*self.convert ( reply2 )
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


