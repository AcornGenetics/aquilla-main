
def thermal_parser(steps, last_temp = 25, last_time = 0, n = "-1", ramp_rate = 10.0):
    setpoint = 25# Initialization of setpoint
    for s in steps:
        if "repeat" in s:
            cycles = s["cycles"]
            for i in range ( cycles ):
                for args in thermal_parser ( s["repeat"], last_temp, last_time, i+1, ramp_rate ):
                    _, _, last_temp, _, _, last_time = args
                    yield args

        elif "setpoint" in s:
            setpoint = s["setpoint"]
            duration = s["duration"]
            try:
                ramp_duration = abs( setpoint - last_temp ) / ramp_rate
            except TypeError as te:
                #print ( "setpoint", setpoint )
                #print ( "last_temp", last_temp )
                raise ( te )

            last_time += ramp_duration
            yield "ramp", n, last_temp, setpoint, ramp_duration, last_time

            last_temp = setpoint
            #print ( "last_temp", last_temp )
            last_time += duration
            yield "hold", n, setpoint, setpoint, duration, last_time
            #yield f"{n} Hold {setpoint} for {duration} seconds until {last_time + duration:.2f}"

        elif "disable" in s:
            duration = s["duration"]
            last_time += duration
            yield "disable", n, setpoint, setpoint, duration, last_time

        elif "enable" in s:
            duration = s["duration"]
            last_time += duration
            yield "enable", n, setpoint, setpoint, duration, last_time

        elif "optics" in s:     
            yield "optics", n, setpoint, setpoint, duration, last_time

        elif "cmd" in s:        yield "cmd", s
        elif "fanon" in s:      yield "fanon", s
        elif "fanoff" in s:     yield "fanoff", s
        elif "stc_fanon" in s:  yield "stc_fanon", s
        elif "stc_fanoff" in s: yield "stc_fanoff", s
        elif "pcr_fanon" in s:  yield "pcr_fanon", s
        elif "pcr_fanoff" in s: yield "pcr_fanoff", s

        elif "ramp_rate" in s:
            ramp_rate = s["ramp_rate"]
            yield "call", "change_ramprate", [ s["ramp_rate"] ]
