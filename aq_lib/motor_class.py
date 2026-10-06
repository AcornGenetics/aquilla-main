import time
import logging
import pigpio
from aq_lib.config_module import Config
from aq_lib.geometry import geometry
from aq_lib.plate_positions import axis_stops, drawer_rows
from aq_lib.homing_log import emit_homing_sample

HIGH = 1
LOW = 0

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger( "aquila.motor" )

config = Config()


class Motor():

    position = 0

    # ------------------------------------------------------------------
    # Pulse delays (seconds for one full STEP high+low cycle).
    # Subclasses override per motor; every move falls back to these unless a
    # call passes an explicit pulse_delay.
    # ------------------------------------------------------------------
    move_pulse_delay = 0.00015   # conservative fallback if a subclass omits it
    home_pulse_delay = 0.0002    # used by move_w_home_flag (bit-banged, not pigpio waves)

    # motor_test parameters (subclasses override test_positions).
    test_delays    = [0.00005, 0.00007, 0.00008, 0.00009, 0.0001, 0.00011, 0.00012, 0.00015, 0.0002]
    test_positions = [320, 640, 960, 1280]

    # ramp_test parameters. Each list runs SLOWEST (safest) FIRST.
    ramp_test_cruise      = [0.00012, 0.00011, 0.0001, 0.00009, 0.00008, 0.00007, 0.00006]
    ramp_test_ramp_steps  = [40, 30, 24, 16, 10, 6, 0]
    ramp_test_start_delay = [0.00025, 0.0002, 0.00018, 0.00016, 0.00014]
    ramp_test_reps        = 3
    ramp_test_tolerance   = 2

    # Acceleration ramp. ramp_start_delay is the slow, always-startable period
    # of the first and last motor step; cruise is the passed pulse_delay.
    # ramp_steps motor steps accelerate, the same number decelerate.
    # ramp_steps = 0 disables ramping for a motor.
    ramp_start_delay = 0.0002
    ramp_steps       = 40

    def _resolve_pulse_delay( self, pulse_delay ):
        """None means 'use this motor's configured default'."""
        return self.move_pulse_delay if pulse_delay is None else pulse_delay

    def __init__( self ):
        self.pi = pigpio.pi("172.18.0.1", 8888) # this ip can be found via running "docker network inspect fleet_default"
        self.pi.set_mode(self.EN_PIN,   pigpio.OUTPUT)
        self.pi.set_mode(self.STEP_PIN, pigpio.OUTPUT)
        self.pi.set_mode(self.DIR_PIN,  pigpio.OUTPUT)
        self.pi.set_mode(self.HME_PIN,  pigpio.INPUT)
        self.pi.write(self.EN_PIN, HIGH) # apperently this Enable Pin is inverted, so setting it HIGH turns the driver off

        logger.info( "Setting pin %d", self.HME_PIN )
        logger.info( "Setup motor pins" )
        value = config.info.get("motor_test") # used ONLY for seeing what is the smallest delay where motor does not stall
        if (
            value is not None
            and value != 0
            and not (
                isinstance(value, str)
                and value.strip().lower() in ("0", "false")
            )
        ):
            self.motor_test()

        value = config.info.get("ramp_test") # sweeps ramp + cruise settings, see ramp_test()
        if (
            value is not None
            and value != 0
            and not (
                isinstance(value, str)
                and value.strip().lower() in ("0", "false")
            )
        ):
            self.ramp_test()

    def motor_test(self):
        """Step-skip sweep. Slowest delay first, so a stall at a fast setting
        cannot leave the driver in a degraded state for the settings after it.

        SINGLE  one move out to a position, then home.
        SCAN    the whole position list walked in order without homing in
                between, then one home. This is the motion a real optical pass
                uses and reproduces run-time step loss a SINGLE sweep can miss.
        """
        logger.info("Start of motor testing for %s\n", self.motor_name)
        logger.info("Test positions: %s", self.test_positions)
        self.home()

        for delay in sorted( self.test_delays, reverse = True ):
            for pos in self.test_positions:
                logger.info("SINGLE: moving to %d position using pulse delay of %f\n", pos, delay)
                self.move_abs_wo_home_flag( pos, 0.000, delay ) # the second argument is step delay - obsolete and kept only for backwards compatibility
                ret = self.move_w_home_flag( -self.home_steps, 0.0020 )
                if self.isHome():
                    self.reset_position()
                logger.info("Moving home took %d steps\n", ret)

        for delay in sorted( self.test_delays, reverse = True ):
            logger.info("SCAN: walking %d positions using pulse delay of %f\n",
                        len( self.test_positions ), delay)
            for pos in self.test_positions:
                self.move_abs_wo_home_flag( pos, 0.000, delay )
            expected = self.test_positions[-1] if self.test_positions else 0
            ret = self.move_w_home_flag( -self.home_steps, 0.0020 )
            logger.info("SCAN result: pulse delay %f, expected %d steps home, took %d, lost %d\n",
                        delay, expected, ret, expected - ret)
            if self.isHome():
                self.reset_position()

        logger.info("End of motor testing for %s\n", self.motor_name)

    def _scan_trial( self, cruise, start_delay, ramp_steps ):
        """Run the real optical-scan motion pattern ramp_test_reps times at one
        setting and report whether it kept its steps.

        The pattern is deliberately the same as an optical pass: home, then walk
        every position in order with no homing in between, then home once. A
        single long move from home can pass at a speed where this pattern fails,
        which is how the bench sweep used to disagree with what happened during
        a run.

        Returns (ok, worst_abs_residual, fastest_scan_seconds).
        """
        saved = ( self.move_pulse_delay, self.ramp_start_delay, self.ramp_steps )
        self.move_pulse_delay = cruise
        self.ramp_start_delay = start_delay
        self.ramp_steps       = ramp_steps

        worst = 0
        best_t = None
        ok = True
        try:
            for rep in range( self.ramp_test_reps ):
                self.home()
                if not self.isHome():
                    logger.error( "RAMPTEST: could not home, abandoning this setting" )
                    return False, None, None
                self.reset_position()

                t0 = time.time()
                for pos in self.test_positions:
                    self.move_abs_wo_home_flag( pos, 0.000 )
                scan_t = time.time() - t0

                expected = self.test_positions[-1]
                ret = self.move_w_home_flag( -self.home_steps, 0.0020 )
                residual = expected - ret
                if self.isHome():
                    self.reset_position()

                worst = max( worst, abs( residual ) )
                best_t = scan_t if best_t is None else min( best_t, scan_t )
                logger.info( "RAMPTEST rep %d/%d  cruise=%.0fus start=%.0fus ramp_steps=%d  scan=%.3fs  residual=%+d",
                             rep + 1, self.ramp_test_reps, cruise*1e6, start_delay*1e6,
                             ramp_steps, scan_t, residual )

                if abs( residual ) > self.ramp_test_tolerance:
                    ok = False
                    break          # a setting that fails once is not usable
        finally:
            self.move_pulse_delay, self.ramp_start_delay, self.ramp_steps = saved

        return ok, worst, best_t

    def ramp_test( self ):
        """Find the fastest ramp + cruise settings this motor keeps steps at.

        Searched in four stages rather than as a full grid, which would take
        hours. Each stage tightens one parameter while holding the others, then
        the last stage re-tries the cruise speed because a shorter ramp and a
        faster cruise interact.
        """
        logger.info( "Start of ramp testing for %s", self.motor_name )
        logger.info( "RAMPTEST positions: %s  reps per setting: %d  tolerance: +/-%d steps",
                     self.test_positions, self.ramp_test_reps, self.ramp_test_tolerance )

        cache = {}
        def trial( c, s, r ):
            key = ( c, s, r )
            if key in cache:
                return cache[key]
            ok, worst, t = self._scan_trial( c, s, r )
            cache[key] = ( ok, worst, t )
            logger.info( "RAMPTEST RESULT cruise=%.0fus start=%.0fus ramp_steps=%-3d -> %s  worst|residual|=%s  scan=%s",
                         c*1e6, s*1e6, r, "PASS" if ok else "FAIL",
                         worst, ( "%.3fs" % t ) if t else "-" )
            return cache[key]

        start = self.ramp_test_start_delay[0]
        steps = self.ramp_test_ramp_steps[0]

        # Stage 1: fastest cruise, with a generous ramp in front of it.
        logger.info( "RAMPTEST stage 1: cruise speed (ramp held at start=%.0fus, %d steps)",
                     start*1e6, steps )
        best_cruise = None
        for c in self.ramp_test_cruise:
            if c >= start:
                continue                      # no ramp possible, skip
            ok, _, _ = trial( c, start, steps )
            if ok:
                best_cruise = c
            else:
                break
        if best_cruise is None:
            logger.error( "RAMPTEST: even the slowest cruise setting lost steps. "
                          "Something is wrong mechanically or electrically; stopping." )
            logger.info( "End of ramp testing for %s", self.motor_name )
            return None

        # Stage 2: shortest ramp that still holds at that cruise.
        logger.info( "RAMPTEST stage 2: ramp length at cruise=%.0fus", best_cruise*1e6 )
        best_steps = steps
        for r in self.ramp_test_ramp_steps:
            ok, _, _ = trial( best_cruise, start, r )
            if ok:
                best_steps = r
            else:
                break

        # Stage 3: fastest start speed for that ramp.
        logger.info( "RAMPTEST stage 3: start speed at cruise=%.0fus, ramp_steps=%d",
                     best_cruise*1e6, best_steps )
        best_start = start
        for s in self.ramp_test_start_delay:
            if s <= best_cruise:
                break
            ok, _, _ = trial( best_cruise, s, best_steps )
            if ok:
                best_start = s
            else:
                break

        # Stage 4: with the ramp tightened, see if the cruise can go faster.
        logger.info( "RAMPTEST stage 4: retry cruise with start=%.0fus, ramp_steps=%d",
                     best_start*1e6, best_steps )
        idx = self.ramp_test_cruise.index( best_cruise )
        for c in self.ramp_test_cruise[idx+1:]:
            if c >= best_start:
                break
            ok, _, _ = trial( c, best_start, best_steps )
            if ok:
                best_cruise = c
            else:
                break

        _, _, best_t = cache[( best_cruise, best_start, best_steps )]

        # A safety notch: one step slower on cruise than the fastest that passed.
        idx = self.ramp_test_cruise.index( best_cruise )
        safe_cruise = self.ramp_test_cruise[idx-1] if idx > 0 else best_cruise

        logger.info( "RAMPTEST ==================== %s ====================", self.motor_name )
        logger.info( "RAMPTEST fastest passing : cruise=%.0fus start=%.0fus ramp_steps=%d  scan=%.3fs",
                     best_cruise*1e6, best_start*1e6, best_steps, best_t or 0 )
        logger.info( "RAMPTEST recommended     : cruise=%.0fus start=%.0fus ramp_steps=%d  (one notch of margin)",
                     safe_cruise*1e6, best_start*1e6, best_steps )
        logger.info( "RAMPTEST settings tried  : %d", len( cache ) )
        logger.info( "RAMPTEST paste into the %s class:", type( self ).__name__ )
        logger.info( "RAMPTEST     move_pulse_delay = %.5f", safe_cruise )
        logger.info( "RAMPTEST     ramp_start_delay = %.5f", best_start )
        logger.info( "RAMPTEST     ramp_steps       = %d", best_steps )
        logger.info( "End of ramp testing for %s", self.motor_name )

        return { "cruise": best_cruise, "safe_cruise": safe_cruise,
                 "start_delay": best_start, "ramp_steps": best_steps,
                 "scan_seconds": best_t }

    def move_out_of_home(self):
        return self.move_wo_home_flag( 100, 0.0020 )

    def home( self ):
        steps = self.home_steps
        if self.isHome():
            self.move_out_of_home()

        logger.info("Homing using %d steps", steps)
        ret = self.move_w_home_flag( -steps, 0.0020 )
        residual = self.position
        reached_home = bool( self.isHome() )
        if reached_home:
            self.reset_position()
        else:
            logger.error("Did not reach home.")

        emit_homing_sample(
            self.motor_name,
            steps_to_flag=ret,
            residual=residual,
            reached_home=reached_home,
        )
        return ret

    def reset_position( self ):
        if abs(self.position) > 20:
            logger.warning("Position Error %d",self.position )
        logger.info("Resetting motor position: %d -> 0", self.position )
        self.position = 0

    def enable( self ):
        self.pi.write ( self.EN_PIN, LOW )

    def disable( self ):
        self.pi.write ( self.EN_PIN, HIGH )

    def isHome(self):
        return self.pi.read ( self.HME_PIN )

    # step_delay is not used but remains for backwards compatibility
    def move_w_home_flag( self, steps, step_delay = 0.0, pulse_delay = None ): # does not pigpio as it needs to check for the flag every step
        pulse_delay = self.home_pulse_delay if pulse_delay is None else pulse_delay
        time0 = time.time()
        logger.info( "Moving with home flag: %d", steps )
        self.set_dir ( steps )
        self.enable()

        steps_traveled = steps
        for i in range( abs( steps ) ):
            if self.pi.read ( self.HME_PIN ):
                logger.info( "Caught home flag after %d steps", i )
                steps_traveled = i
                break
            for k in range ( self.step_multiplier ):
                self.pi.write( self.STEP_PIN, HIGH)
                time.sleep ( pulse_delay / 2 )
                self.pi.write( self.STEP_PIN, LOW)
                time.sleep ( pulse_delay / 2 )

        if steps > 0:
            self.position += steps_traveled
        else:
            self.position -= steps_traveled

        time1 = time.time()
        logger.info( "STEP_DELAY DISABLED W HOME FLAG: steps: %d\tmultiplier: %d\tpulse_delay: %f\tstep_delay: %f\nAnticipated time: with step_delay: %f;\twithout: %f\nActual time: %f\nPosition updated to: %f" , steps_traveled, self.step_multiplier, pulse_delay, step_delay, steps_traveled*step_delay+pulse_delay*steps_traveled*self.step_multiplier, pulse_delay*steps_traveled*self.step_multiplier, time1-time0, self.position)

        logger.info("Position after homing: %d", self.position)
        return steps_traveled

    def move_abs_w_home_flag( self, position, step_delay = 0.0 ):
        delta = position - self.position
        return self.move_w_home_flag( delta, step_delay )

    def move_abs_wo_home_flag( self, position, step_delay = 0.0, pulse_delay = None ):
        logger.info( "Moving %d", position )
        delta = position - self.position
        logger.info( "Moving delta %d", delta )
        return self.move_wo_home_flag( delta, step_delay, pulse_delay )

    def set_dir( self, steps ):
        if steps < 0:
            logger.info( "Setting DIR=LOW" )
            self.direction = 1
            self.pi.write( self.DIR_PIN, self.DIR_BACK_STATE)
        else:
            logger.info( "Setting DIR=HIGH" )
            self.direction = 0
            self.pi.write( self.DIR_PIN, self.DIR_FORWARD_STATE)

    def _ramp_profile( self, total_steps, cruise_delay ):
        """Split a move into (n_ramp, cruise_steps).

        A move shorter than 2*ramp_steps gets a triangular profile: it
        accelerates for half the move and decelerates for the other half.
        """
        if self.ramp_steps <= 0 or self.ramp_start_delay <= cruise_delay:
            return 0, total_steps
        n_ramp = min( self.ramp_steps, total_steps // 2 )
        return n_ramp, total_steps - 2 * n_ramp

    def _ramp_pulses( self, n_ramp, cruise_delay, accelerating ):
        """Pulse list for one ramp leg. Period moves linearly from
        ramp_start_delay to cruise_delay over n_ramp motor steps."""
        pin = 1 << self.STEP_PIN
        d0, d1 = self.ramp_start_delay, cruise_delay
        pulses = []
        for i in range( n_ramp ):
            frac = ( i + 1 ) / n_ramp if accelerating else ( n_ramp - i ) / n_ramp
            period = d0 + ( d1 - d0 ) * frac
            half = max( 2, int( period * 1000000 ) // 2 )   # pigpio wants whole microseconds
            for _ in range( self.step_multiplier ):
                pulses.append( pigpio.pulse( pin, 0, half ) )
                pulses.append( pigpio.pulse( 0, pin, half ) )
        return pulses

    def move_time_estimate( self, steps, pulse_delay = None ):
        """Predicted duration of move_wo_home_flag(steps), in seconds."""
        cruise = self._resolve_pulse_delay( pulse_delay )
        total = abs( steps )
        n_ramp, cruise_steps = self._ramp_profile( total, cruise )
        t = cruise_steps * self.step_multiplier * cruise
        d0, d1 = self.ramp_start_delay, cruise
        for i in range( n_ramp ):
            t += 2 * self.step_multiplier * ( d0 + ( d1 - d0 ) * ( i + 1 ) / n_ramp )
        return t

    def move_wo_home_flag( self, steps, step_delay = 0.0, pulse_delay = None ):

        pulse_delay = self._resolve_pulse_delay( pulse_delay )
        time0 = time.time()

        total_steps = abs( steps )
        if total_steps == 0:
            logger.info( "Move of 0 steps requested, nothing to do" )
            return steps

        self.set_dir( steps )
        self.enable()

        Y = self.STEP_PIN
        pulse_number = total_steps * self.step_multiplier # true number of pulses
        pulse2 = int((pulse_delay * 1000000) // 2) # for backward compatibility reasons pulse_delay reflects the duration of entire ON-OFF cycle; pigpio functions take time in microseconds hence the conversion

        n_ramp, cruise_steps = self._ramp_profile( total_steps, pulse_delay )
        logger.info("pulse2: %f, pulse_number: %d, ramp_steps: %d, cruise_steps: %d\n",
                    pulse2, pulse_number, n_ramp, cruise_steps)

        waves = []
        chain = []

        try:
            if n_ramp:
                self.pi.wave_add_generic( self._ramp_pulses( n_ramp, pulse_delay, True ) )
                w_up = self.pi.wave_create()
                if w_up < 0:
                    logger.error( "CRITICAL ERROR: could not create ramp-up wave (%d)", w_up )
                    return
                waves.append( w_up )
                chain += [ w_up ]

            if cruise_steps:
                pulse_high = pigpio.pulse(1<<Y, 0, pulse2) # Turn GPIO Y ON for pulse_delay//2
                pulse_low = pigpio.pulse(0, 1<<Y, pulse2) # Turn GPIO Y OFF for pulse_delay//2
                self.pi.wave_add_generic([pulse_high, pulse_low])
                wave_a = self.pi.wave_create()
                if wave_a < 0:
                    logger.error( "CRITICAL ERROR: could not create cruise wave (%d)", wave_a )
                    return
                waves.append( wave_a )

                cruise_pulses = cruise_steps * self.step_multiplier
                inner_count = cruise_pulses // 8 # cruise_pulses MUST BE divisble by 8! step_multiplier is 8 or 32, so any cruise_steps satisfies this

                if inner_count > 65000:
                    logger.info ("CRITICAL ERROR: INNER STEP COUNT IS TOO LARGE: %d > 65000", inner_count)
                    return

                chain += [
                    255, 0,          # Start Outer
                        255, 0,      # Start Inner
                            wave_a,
                        255, 1, inner_count % 256, inner_count // 256,# End Inner
                    255, 1, 8, 0     # End Outer
                ]

            if n_ramp:
                self.pi.wave_add_generic( self._ramp_pulses( n_ramp, pulse_delay, False ) )
                w_dn = self.pi.wave_create()
                if w_dn < 0:
                    logger.error( "CRITICAL ERROR: could not create ramp-down wave (%d)", w_dn )
                    return
                waves.append( w_dn )
                chain += [ w_dn ]

            logger.info("Created the wave")
            self.pi.wave_chain(chain)
            logger.info("Created the chain")
            while self.pi.wave_tx_busy():
                time.sleep(0.005) # Sleep for 5ms to avoid maxing out CPU
        finally:
            for w in waves:
                self.pi.wave_delete(w)
        logger.info ("Deleted the chain, success\n")

        self.position += steps

        time1 = time.time()
        logger.info( "STEP_DELAY DISABLED WO HOME FLAG: steps: %d\tmultiplier: %d\tpulse_delay: %f\tstep_delay: %f\nAnticipated time: with step_delay: %f;\twithout: %f\nActual time: %f\nPosition updated to: %d" , steps, self.step_multiplier, pulse_delay, step_delay, steps*step_delay+pulse_delay*steps*self.step_multiplier, pulse_delay*steps*self.step_multiplier, time1-time0, self.position)
        # negative step number indicates backwards direction
        logger.info( "Position updated to: %d", self.position )
        return steps

    def test(self ):
        for _ in range ( 1 ):
            logger.info ( "1000 steps forward" )
            #self.move_wo_home_flag (   16000, 0 )
            logger.info ( "1000 steps backwards" )
            self.move_w_home_flag (   -20000, 0 )

class Drawer ( Motor ):

    motor_name = "drawer"
    EN_PIN = 12
    STEP_PIN = 5
    DIR_PIN = 25
    HME_PIN = 24
    DIR_BACK_STATE = LOW
    DIR_FORWARD_STATE = HIGH
    # Ramp tuning (colleague's bench values, 2026-09 sweeps). Starting point —
    # re-run ramp_test on a real 15-well drawer and paste the recommended values.
    move_pulse_delay = 0.0001
    home_pulse_delay = 0.0002
    ramp_start_delay = 0.0002
    ramp_steps       = 40
    step_multiplier = config.drawer["step_multiplier"]
    open_steps = config.drawer["open_steps"]
    home_steps = config.drawer["home_steps"]

    def __init__( self ):
        super().__init__()
        # Measured read position per plate row (A, B, C…) from host_config.json
        # (drawer.rows), validated against the provisioned geometry. A 4-well
        # plate is the degenerate 1-row case with a single read position.
        self.rows = drawer_rows( config.drawer, geometry() )
        logger.info("Loaded drawer row positions from config: %s", self.rows)

    def open( self ):
        self.home()
        # pulse_delay 0.00007 (was 0.0001). The inner per-pulse sleep runs
        # step_multiplier x open_steps times and dominates travel time, so dropping
        # it ~30% is what actually speeds the drawer up ?~@~T targets ~10%+ faster open.
        # step_delay kept at 0.0005 (Ryan 04/22/26, was 0.002).
        # Hardware-tested: verify full travel on sn01-03 (lower pulse_delay risks step-skip).
        ret = self.move_abs_wo_home_flag ( self.open_steps, 0.0005, 0.00015 )

    def read( self ):
        self.home()
        # pulse_delay 0.00007 (was 0.0001) to match open(); step_delay kept at 0.001.
        # Row A is the read position for a 4-well (1-row) plate.
        ret = self.move_wo_home_flag ( self.rows[0], 0.001, 0.0001 )

    def goto_row( self, row_index ):
        # Position the drawer at plate row `row_index` (0=A, 1=B, 2=C…). Absolute
        # addressing: each row is an independently-calibrated read position.
        logger.info( "Drawer go to row %d", row_index )
        self.move_abs_wo_home_flag( self.rows[row_index], 0.000, 0.0001 )

class Axis ( Motor ):

    motor_name = "axis"
    EN_PIN = 26
    STEP_PIN = 19
    DIR_PIN = 13
    HME_PIN = 16
    DIR_BACK_STATE = HIGH
    DIR_FORWARD_STATE = LOW
    # Ramp tuning (colleague's bench values, 2026-09 sweeps). Starting point —
    # re-run ramp_test on a real 15-well axis and paste the recommended values.
    move_pulse_delay = 0.00009
    home_pulse_delay = 0.0002
    ramp_start_delay = 0.0002
    ramp_steps       = 16
    step_multiplier = config.axis["step_multiplier"]
    home_steps = config.axis["home_steps"]

    def __init__( self ):
        super().__init__()

        # Measured carriage steps come from host_config.json (axis.stops), one
        # per stop index the read plan emits (cols + sensor_gap). axis_stops
        # validates them against the device's provisioned geometry (via
        # assert_axis_positions_match, #505) — a host_config that doesn't match
        # the plate fails loud here, not mid-run.
        self.positions = axis_stops( config.axis, geometry() )
        logger.info("Loaded axis stops from config: %s", self.positions)

    def goto_position( self, N, row = 0 ):
        # positions is either a flat list (shared X across rows) or a list-of-lists
        # (per-row calibration, #526). Select the current row's stops when per-row;
        # the shared form ignores `row` (byte-identical to before).
        stops = self.positions[row] if self.positions and isinstance(self.positions[0], list) else self.positions
        logger.info( "Go to row %d stop %d", row, N )
        self.move_abs_wo_home_flag( stops[N], 0.000, 0.0001 )

def main():

    import sys

    motor_list = {
                "axis": Axis,
                "drawer": Drawer,
            }

    try:
        motor = sys.argv[1].lower()
        assert motor in motor_list
        steps = int(sys.argv[2] )
        assert "%d"%steps == sys.argv[2]
    except Exception as e:
        print ( e )
        print ( "Usage:", sys.argv[0], "drawer/axis <steps>" )
        exit( -1 )

    MotorClass = motor_list[ motor ]
    motor = MotorClass()
    motor.move_w_home_flag( steps, 0 )

if __name__ == "__main__":
    main()