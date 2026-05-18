import spidev
import time
import statistics
import RPi.GPIO as GPIO


import RPi.GPIO as GPIO
import time

# Set the numbering mode for the GPIO pins (BCM or BOARD)
# BCM refers to the Broadcom SOC channel number (GPIO numbers)
# BOARD refers to the physical pin numbers on the header
GPIO.setmode(GPIO.BCM)

# Define the GPIO pins you want to toggle
pin_22 = 22
pin_27 = 27

# Set up the pins as output
GPIO.setup(pin_22, GPIO.OUT)
GPIO.setup(pin_27, GPIO.OUT)





SPI_BUS = 0  # SPI bus number (e.g., 0 for SPI0)
SPI_DEVICE = 0  # Chip Select (CS) line (e.g., 0 for CE0)
SPI_SPEED_HZ = 100000  # SPI clock speed in Hz

spi = spidev.SpiDev()
#spi.open_path( "/dev/spidev0.0" )
spi.open( 0,0)
spi.max_speed_hz = SPI_SPEED_HZ
spi.mode = 0b11

REG_ADC_CONTROL = 0x01
REG_DATA        = 0x02
REG_ID          = 0x05   
REG_ERROR       = 0x06
REG_CHANNEL     = 0x09

# 0x40 is Read bit. 

reply = spi.xfer2( [ 0x40 + REG_ADC_CONTROL, 0x00, 0x00 ] )
print ( "ADC control", "".join( [" %02x"%x for x in reply] ) ) 

CHANNEL_0 = 0x09
reply = spi.xfer2( [ 0x40 + CHANNEL_0, 0x00, 0x00 ] )
print ( "Channel 0", "".join( [" %02x"%x for x in reply] ) ) 

CONFIG_0 = 0x19
reply = spi.xfer2( [ 0x40 + CONFIG_0, 0x00, 0x00 ] )
print ( "Config 0: ", "".join( [" %02x"%x for x in reply] ) ) 
                                                 # confirmed returns 0x0870
                                                 # 08 = Bipolar /Burnout /REF_BUFP
                                                 # 70 = 0111.0000.  AIN_BUFM AIN_BUFM ref_sel=0b10, pga=0

# Changing FS buffer to 128 instead of 384
REG_FILTER = 0x21
reply = spi.xfer2( [ 0x00 + REG_FILTER, 0x06, 0x00, 0x20 ] )

reply = spi.xfer2( [ 0x40 + REG_FILTER, 0x00, 0x00, 0x00 ] )
print ( "Filter 0: ", "".join( [" %02x"%x for x in reply] ) ) 
                                            # 0x060180
                                            # 0000.0110.  0000.0001 1000.0000
                                            # 000 filter = sinc4
                                            #    0 Reject 60
                                            #     .000 Post filter
                                            #             0000.0 not used
                                            #                   001 1000.0000 
                                            #                     256 + 128 = 384
                                            # f_adc = f_clk / ( 32 * FS )
                                            #       = 50ms settling time 66.82 (table 56. )

# This is for writing: ~0x40. 
# Config
REF_SEL = 0b10  # Internal reference p. 91
reply = spi.xfer2( [ CONFIG_0, 0x08, 0x60 + 0b10000 ] )

# ADC_CONTROL
#                                Full power, continuous conversion ,internal 614.4kHz clock
reply = spi.xfer2( [ 0x01, 0x01, 0x80  ] )

# CHANNEL_0
                                # EN = 1
                                # AINP = 0
                                # AINM = 1
reply = spi.xfer2( [ CHANNEL_0, 0x80, 0x01 ] )


def convert( reply ):
    code = ( reply[1]*256*256 + reply[2]*256 + reply[3] )  # p. 48

    return ( code / 2**23 - 1 ) * 2.5

i=0
while ( 1 ):

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
        reply = spi.xfer2( [ 0x40+cmd ] + [0x00]* length[cmd] )
        print (  "%02x"%cmd, reply )
        if cmd == 2: time.sleep ( 0.10 )
        else: time.sleep ( 0.01 )

    print ()

    break

t0 = time.time()
buf_on = [0] * 10
buf_off = [0] * 10

def print_result ( t0, reply1, reply2, adc_value, tag = "" ):
    print ( "%6.3f"%( ( time.time() - t0 ) ) , end = " " )
    print ( " ".join ( [ "%02x"%r for r in reply1]), end=" " )
    print ( " ".join ( [ "%02x"%r for r in reply2]), end=" " )
    print ( "%.4f"%adc_value, end = " " )
    print ( "%.4f"%statistics.mean( buf_on ), end = " " )
    print ( "%.4f"%statistics.pstdev( buf_on ), end = " " )
    print ( "%.4f"%statistics.mean( buf_off ), end = " " )
    print ( "%.4f"%statistics.pstdev( buf_off ), end = " " )
    print ( "%.4f"%(statistics.mean( buf_on )-statistics.mean( buf_off )), end = " " )
    print( tag )


try:
    for j in range ( 400 ):
        GPIO.output(pin_22, GPIO.HIGH)  # Turn pin 22 on
        for i in range ( 10 ):
            time.sleep ( 0.01)
            reply1 = spi.xfer2( [ 0x41 ] + [0x00,0x00, ] )
            reply2 = spi.xfer2( [ 0x42 ] + [0x00,0x00, 0x00] )
            adc_value = 1000*convert ( reply2 )
            buf_on[i] = adc_value
            print_result( t0, reply1, reply2, adc_value, tag = "*")


        GPIO.output(pin_22, GPIO.LOW)   # Turn pin 22 off
        for i in range ( 10 ):
            time.sleep ( 0.01 )
            reply1 = spi.xfer2( [ 0x41 ] + [0x00,0x00, ] )
            reply2 = spi.xfer2( [ 0x42 ] + [0x00,0x00, 0x00] )
            adc_value = 1000*convert ( reply2 )
            buf_off[i] = adc_value
            print_result( t0, reply1, reply2, adc_value )

except Exception as e:
    print ( "Caught exception, turning off led" )
    GPIO.output(pin_22, GPIO.LOW)   # Turn pin 22 off
    raise e
except KeyboardInterrupt as ke:
    print ( "Keyboard interrupt, turning off led" )
    GPIO.output(pin_22, GPIO.LOW)   # Turn pin 22 off





    #print ( "ADC_CONTROL reg:", read_register( REG_ADC_CONTROL, 3 ) )
    #print ( "DATA        reg:", read_register( REG_DATA       , 4 ) )
    #print ( "ID     register:", read_register( REG_ID         , 1 ) )
    #print ( "ERROR  register:", read_register( REG_ERROR      , 4 ) )
    #print ( "CHANNEL     reg:", read_register( REG_CHANNEL    , 2 ) )


