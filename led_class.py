import RPi.GPIO as GPIO
import time
import logging
from aq_lib.config_module import Config

logger = logging.getLogger( "aquila.led"  )

class LED():
    def __init__( self, channel ):


        self.channel = channel
        config = Config()
        self.led_pin = config.optics[ channel + " pin" ]
        self.LED_OFF = config.optics[ "LED_OFF" ]
        self.LED_ON = config.optics[ "LED_ON" ]

        GPIO.setmode(GPIO.BCM)
        GPIO.setup( self.led_pin, GPIO.OUT, initial = self.LED_OFF)


    def on( self ): GPIO.output ( self.led_pin, self.LED_ON )
    def off( self ): GPIO.output ( self.led_pin, self.LED_OFF )
    def set( self, value ):
        if value: self.on()
        else: self.off()

    def __del__( self ):
        self.off()
