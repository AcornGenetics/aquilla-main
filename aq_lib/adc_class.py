import time
import sys
import statistics
import spidev
import json

import RPi.GPIO as GPIO
from RPi.GPIO import HIGH, LOW, IN, OUT
import logging
from aq_lib.config_module import Config
from aq_lib.geometry import geometry
from aq_lib.optics_read_plan import capture_mode
from aq_lib.adc_health_log import emit_adc_health_sample

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

# --- RDY polling budget ----------------------------------------------------
# Attempts are capped separately for the two paths because optics scan time is
# the binding constraint. The capture loop keeps 7 attempts (~6 ms of wait);
# read_ambient_temp is off the scan path so it can afford 20 (~19 ms, which
# covers a full 16.7 ms conversion period at 60 SPS).
ADC_RDY_ATTEMPTS_CAPTURE = 7
ADC_RDY_ATTEMPTS_AMBIENT = 20
ADC_RDY_SLEEP            = 0.001

class OpticalRead():

    def __init__(self ):

        config = Config()
        self.LED_ON = [GPIO.LOW, GPIO.HIGH] [ config.optics["LED_ON" ] ]
        self.LED_OFF= [GPIO.LOW, GPIO.HIGH] [ config.optics["LED_OFF"] ]

        self.fam_channel = ( config.adc["famP"], config.adc["famN"], )
        self.rox_channel = ( config.adc["roxP"], config.adc["roxN"], )

        self.data_file = sys.stdout
        self.t0 = time.time()

        # --- diagnostic counters -------------------------------------------
        # n_retries       : data reads that needed more than one RDY poll
        # n_failed_reads  : reads that never came ready (a -123 was written)
        # n_stale_frames  : frames whose byte0 was not 0x00 (see _check_frame)
        # n_unrepairable  : -123 samples with no usable neighbour in their LED
        #                   half-period. Initialized here; the actual increment
        #                   lives in the -123 repair (Tier 2), so this stays 0
        #                   until Tier 2 lands.
        self.n_retries      = 0
        self.n_failed_reads = 0
        self.n_stale_frames = 0
        self.n_unrepairable = 0

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

        # Capture configuration derives from the provisioned plate geometry
        # (ADR-023 / #524), not host_config flags — so a device can never be
        # mis-configured (e.g. a 15-well plate flagged single-ADC). Multi-row
        # plates are the dual-ADC 'both' builds; 1-row 4-well is single-ADC.
        geo = geometry()
        self.well_15 = geo.well_count == 15
        self.adc_num = 1  # becomes 2 below when two_adcs
        self.two_adcs = capture_mode(geo) == "both"
        self.both_channel_was_used = False
        self.data_both = [] # calling "both" channel fills up this structure
        self._raw_log_fp = None # when set (run context), 'both' rows are also streamed to a raw safety log (ADR-024)
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

                for attempt in range ( ADC_RDY_ATTEMPTS_AMBIENT ):

                    st = self.spi.xfer2( [ 0x40 | 0x00, 0x00 ] )        # read STATUS
                    if not ( st[1] & 0x80 ):                            # RDY low = ready
                        reply2 = self._check_frame( self.spi.xfer2( [ 0x42 ] + [0x00, 0x00, 0x00] ), "ambient" )
                        adc_value = 1000*self.convert ( reply2 )
                        got = True

                    if got:
                        break

                    time.sleep ( ADC_RDY_SLEEP )

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
                self.ROX_enabled = True

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


    def _check_frame( self, reply, where ):
        """byte0 is the ADC's DOUT/RDY line sampled during the command byte.
        0x00 means a fresh conversion was waiting; anything else means it was
        not, and the data register is handing back the previous conversion.

        With the RDY poll in front of every read this should be 0x00 on every
        frame, so a non-zero value means the poll is not doing its job. Nothing
        used to read this byte, so that failure would have been silent.

        The test is != 0x00, not == 0xff: partial values (0x80, 0xc0, 0xf0,
        0xfc) occur when the ready line changes state part way through the
        command byte and are ~12% of all stale frames in the legacy logs.
        """
        if reply and reply[0] != 0x00:
            self.n_stale_frames += 1
            if self.n_stale_frames <= 10:          # cap the log noise
                logger.warning( "stale frame at %s: byte0=%02x (RDY poll passed but data was not fresh)",
                                where, reply[0] )
        return reply

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

    def _repair_sample(self, buf, wi, abs_i, w):
        """Repair the -123 sentinel in buf[wi][2] and [3], in place.

        Sentinel-aware interpolation: neighbours come from inside this LED
        half-period only (abs_i % w), so a repair never crosses an on/off
        transition. buf[wi-1] is already repaired; buf[wi+1] may still be -123
        and is skipped (averaging it would give (good + -123)/2 ~ -60 mV).

        ``abs_i`` is the sample's absolute index in the run (drives the look-back
        decisions); ``buf`` is a window in which wi-1 / wi-2w / wi-scan_num*4*w
        resolve. Shared by mask_data (whole buffer) and mask_data_streaming
        (bounded 2-pass window) so the two are byte-identical (ADR-024)."""
        pass_back = self.scan_num * 4 * w
        for j in range(2):
            idx = j + 2
            if buf[wi][idx] == -123:
                has_prev = ( abs_i % w ) > 0
                has_next = ( abs_i % w ) < w - 1

                prev_val = buf[wi-1][idx] if has_prev else None
                next_val = buf[wi+1][idx] if ( has_next and wi+1 < len(buf) ) else None
                if next_val == -123:
                    next_val = None

                if prev_val is not None and next_val is not None:
                    buf[wi][idx] = ( prev_val + next_val ) / 2
                elif prev_val is not None:
                    buf[wi][idx] = prev_val
                elif next_val is not None:
                    buf[wi][idx] = next_val
                else:
                    self.n_unrepairable += 1
                    if abs_i - pass_back > 0:
                        buf[wi][idx] = buf[wi - pass_back][idx] # same well/channel/phase, previous cycle
                    elif abs_i - 2*w > 0: # previous well or flash, same channel/phase
                        buf[wi][idx] = buf[wi - 2*w][idx]
                    else:
                        buf[wi][idx] = 2.0 if idx == 2 else 2.1

    def _synth_swap(self, rows, w):
        """Reshape repaired raw rows into the legacy format: synthesize a 3rd
        blink (average of the 2 real blinks, prepended per tube), then swap each
        blink's two w-sample half-flashes (FAM is off-then-on).

        Returns NEW rows (copies) so the caller's input is never mutated — the
        streaming path depends on retaining an un-swapped previous pass. The
        reshape is per-tube/per-blink local, so applying it per pass and
        concatenating equals applying it to the whole run."""
        out = []
        for i in range(len(rows)):
            if i % (4*w) == 0:
                for j in range(2*w):
                    a = rows[i+j]
                    b = rows[i+2*w+j]
                    out.append([a[0], a[0], (a[2] + b[2]) / 2, (a[3] + b[3]) / 2, a[4], a[5], a[6], a[7], a[8], a[9], a[10]])
            out.append(list(rows[i]))
        for k in range(len(out) // (2*w)):
            for i in range(w):
                out[2*w*k+i][3], out[2*w*k+w+i][3] = out[2*w*k+w+i][3], out[2*w*k+i][3]
        return out

    def mask_data(self): # outputs new optics data in the legacy format
        # Whole-buffer mask. Half-flash width w = blink_num (#517 Slice 7); see
        # _repair_sample / _synth_swap for the shared logic. mask_data_streaming
        # produces byte-identical output pass-by-pass with bounded RAM (ADR-024).
        w = self.blink_num
        self.n_unrepairable = 0
        for i in range(len(self.data_both)):
            self._repair_sample(self.data_both, i, i, w)
        self.data_both2 = self.data_both
        self.data_both3 = self._synth_swap(self.data_both2, w)

    def mask_data_streaming(self, raw_passes):
        """Mask the run pass-by-pass with a bounded 2-pass window; returns the
        reshaped output (== mask_data's self.data_both3 for the same raw rows).

        ``raw_passes``: iterable of passes, each a list of scan_num*4*w raw rows.
        Only the current + previous pass are held at once — the repair looks back
        at most one pass (scan_num*4*w), so a 2-pass window is exact (ADR-024).
        The retained previous pass is the repaired-but-not-reshaped rows
        (_synth_swap copies, so it is never swapped)."""
        w = self.blink_num
        self.n_unrepairable = 0
        out = []
        prev = []
        processed = 0
        for cur in raw_passes:
            cur = list(cur)
            window = prev + cur
            base = len(prev)
            for wi in range(base, len(window)):
                self._repair_sample(window, wi, processed + (wi - base), w)
            out.extend(self._synth_swap(window[base:], w))
            prev = window[base:]   # repaired, un-swapped cur = next pass's look-back
            processed += len(cur)
        return out

    def emit_health(self, run_timestamp, position):
        """Write a structured ADC-health Sample from the live read-quality
        counters (#528), stamped with the run + position correlation key so it
        can be joined downstream against the Homing Samples to flag reads taken
        after a motor stall. Returns the Sample dict."""
        return emit_adc_health_sample(
            run_timestamp=run_timestamp,
            position=position,
            n_stale_frames=self.n_stale_frames,
            n_retries=self.n_retries,
            n_failed_reads=self.n_failed_reads,
            n_unrepairable=self.n_unrepairable,
        )

    def out_data ( self ): # outputs new optics data in the legacy format
        logger.info("Checking out_data conds")
        logger.info( "ADC health: %d reads needed a retry, %d never came ready (-123 written), "
                     "%d frames had byte0 != 0x00, %d samples had no usable neighbour in their half-period",
                     self.n_retries, self.n_failed_reads, self.n_stale_frames,
                     getattr( self, "n_unrepairable", 0 ) )
        if not self.both_channel_was_used:
            return
        if not self.two_adcs: # data is already out, there is nothing to do
            return

        self.scan_num = 21 if self.well_15 else 6 # 15 vs 4 wells
        logger.info("Scan_num = %d\n", self.scan_num)

        self.mask_data()
        self._write_masked(self.data_both3)
        self.data_both = []

    def _write_masked(self, masked):
        """Write masked optics rows to the data file in the legacy format.
        Shared by the live path (out_data) and the crash-safe recovery path
        (optics_from_raw_log) so both emit identical output (ADR-024)."""
        if self.scan_num == 21:
            legacy_well_one = 9
            rox_well_one = legacy_well_one
            fam_well_one = rox_well_one - 2
        else:
            rox_well_one = 0
            fam_well_one = 2
        rpc = 6 * self.blink_num  # rows per capture = 3 blinks x 2*w (60 at w=10, 42 at w=7)
        passes_num = int(len(masked) / self.scan_num / rpc)
        logger.info("Passes num = %d\n", passes_num)
        for i in range (passes_num):
            true_pass_num = i
            if i == 0: true_pass_num = -1
            for k in range(6):
                if k < 4: # rox comes first
                    for j in range(rpc):
                        rox_index = (i*self.scan_num+rox_well_one+k)*rpc + j
                        if masked[rox_index][2] == -123:
                            if j == 0:
                                masked[rox_index][2] = 2.0
                            else:
                                masked[rox_index][2] = masked[rox_index-1][2]
                        self.print_result( "", masked[rox_index][0], masked[rox_index][2], [(j // self.blink_num + 1) % 2, "rox", true_pass_num, k] )

                if k > 1: # fam comes second
                    for j in range(rpc):
                        fam_index = (i*self.scan_num+fam_well_one+(k-2))*rpc + j
                        if masked[fam_index][3] == -123:
                            if j == 0:
                                masked[fam_index][3] = 2.0
                            else:
                                masked[fam_index][3] = masked[fam_index-1][3]
                        self.print_result( "", masked[fam_index][1], masked[fam_index][3], [(j // self.blink_num + 1) % 2, "fam", true_pass_num, k] )

    def _read_raw_passes(self, raw_path, pass_len):
        """Yield whole passes of raw rows from a safety log, pass_len rows each,
        keeping only one pass in memory (ADR-024 bounded read). A torn trailing
        line from a crash mid-write is dropped; a partial trailing pass is
        incomplete and not yielded."""
        import ast
        pass_rows = []
        with open(raw_path) as fp:
            for line in fp:
                line = line.strip()
                if not line:
                    continue
                try:
                    pass_rows.append(ast.literal_eval(line))
                except (ValueError, SyntaxError):
                    logger.warning("raw log: dropping unparseable trailing line")
                    break
                if len(pass_rows) == pass_len:
                    yield pass_rows
                    pass_rows = []

    def optics_from_raw_log(self, raw_path):
        """Crash-safe write-out (ADR-024): reconstruct the optics file from a raw
        safety log by masking it pass-by-pass (bounded raw read) and writing the
        legacy format. Same output as the live out_data for the same capture
        (modulo the write-time timestamp column — see print_result)."""
        self.scan_num = 21 if self.well_15 else 6
        pass_len = self.scan_num * 4 * self.blink_num
        masked = self.mask_data_streaming(self._read_raw_passes(raw_path, pass_len))
        self._write_masked(masked)

    def start_raw_log(self, raw_path):
        """Begin streaming 'both' capture rows to a raw safety log for this run
        (ADR-024). Keep this OUTSIDE logs/optics/ so the uploader (which syncs
        only the reported logs/optics/*.log) never picks it up."""
        self.stop_raw_log()
        self._raw_log_fp = open(raw_path, "w")

    def stop_raw_log(self):
        """Close the raw safety log (idempotent)."""
        if self._raw_log_fp is not None:
            try:
                self._raw_log_fp.flush()
                self._raw_log_fp.close()
            finally:
                self._raw_log_fp = None

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

                for attempt in range ( ADC_RDY_ATTEMPTS_CAPTURE ):

                    if not got_rox:
                        GPIO.output( self.cs_list[0], GPIO.LOW )
                        st = self.spi.xfer2( [ 0x40 | 0x00, 0x00 ] )        # read STATUS
                        if not ( st[1] & 0x80 ):                            # RDY low = ready
                            reply2 = self._check_frame( self.spi.xfer2( [ 0x42 ] + [0x00, 0x00, 0x00] ), "rox" )   # rox
                            adc_value = 1000*self.convert ( reply2 )                   # rox
                            got_rox = True
                        GPIO.output( self.cs_list[0], GPIO.HIGH )

                    if not got_fam:
                        GPIO.output( self.cs_list[1], GPIO.LOW )
                        st = self.spi.xfer2( [ 0x40 | 0x00, 0x00 ] )        # read STATUS
                        if not ( st[1] & 0x80 ):                            # RDY low = ready
                            reply2_adc2 = self._check_frame( self.spi.xfer2( [ 0x42 ] + [0x00, 0x00, 0x00] ), "fam" )  # fam
                            adc_value_adc2 = 1000*self.convert ( reply2_adc2 )             # fam
                            got_fam = True
                        GPIO.output( self.cs_list[1], GPIO.HIGH )

                    if got_rox and got_fam:
                        if attempt > 0:
                            self.n_retries += 1      # needed more than one RDY poll
                        break

                    time.sleep ( ADC_RDY_SLEEP )

                if not got_rox:
                    adc_value = -123
                    reply2 = [255, 255, 255, 255]
                    self.n_failed_reads += 1
                if not got_fam:
                    adc_value_adc2 = -123
                    reply2_adc2 = [255, 255, 255, 255]
                    self.n_failed_reads += 1

                row = [reply2, reply2_adc2, adc_value, adc_value_adc2, led_state_nr, channel, tag1, tag2, pcr_t0, self.t0, time.time()]
                self.data_both.append(row)
                if self._raw_log_fp is not None:
                    # Crash-safe raw safety log (ADR-024): gated on run context so
                    # the shared capture_blink used by melt_curve never writes it.
                    self._raw_log_fp.write(repr(row) + "\n")

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

            for attempt in range ( ADC_RDY_ATTEMPTS_CAPTURE ):

                if self.two_adcs:
                    GPIO.output( self.cs_list[cs_pin_index], GPIO.LOW )

                st = self.spi.xfer2( [ 0x40 | 0x00, 0x00 ] )        # read STATUS
                if not ( st[1] & 0x80 ):                            # RDY low = ready
                    reply2 = self._check_frame( self.spi.xfer2( [ 0x42 ] + [0x00, 0x00, 0x00] ), channel )
                    adc_value = 1000*self.convert ( reply2 )
                    got = True

                if self.two_adcs:
                    GPIO.output( self.cs_list[cs_pin_index], GPIO.HIGH )

                if got:
                    break

                time.sleep ( ADC_RDY_SLEEP )

            if not got:
                adc_value = -123
                reply2 = [255, 255, 255, 255]
                self.n_failed_reads += 1

            self.print_result( "", reply2, adc_value, labels )

    def clean_up( self ):
        print ( "Caught exception, turning off led" )
        self.gpio.output( LED_PIN1, self.LED_OFF)   # Turn pin 22 off
        self.gpio.output( LED_PIN2, self.LED_OFF)   # Turn pin 22 off
        logger.info( "ADC health: %d reads needed a retry, %d never came ready (-123 written), "
                     "%d frames had byte0 != 0x00, %d samples had no usable neighbour in their half-period",
                     self.n_retries, self.n_failed_reads, self.n_stale_frames,
                     getattr( self, "n_unrepairable", 0 ) )
        raise


def main():
    adc = OpticalRead()

    adc.read_config()

if __name__ == "__main__":
    main()
