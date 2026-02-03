# ads1115_pi.py
from smbus2 import SMBus
import time

class ADS1115:
    DEFAULT_ADDR = 0x48
    REG_CONVERSION = 0x00
    REG_CONFIG     = 0x01
    REG_LO_THRESH  = 0x02
    REG_HI_THRESH  = 0x03

    # PGA map: full-scale range in volts -> bitfield
    _PGA_BITS = {
        6.144: 0b000,
        4.096: 0b001,
        2.048: 0b010,  # default
        1.024: 0b011,
        0.512: 0b100,
        0.256: 0b101,  # 0b110 and 0b111 map to same 0.256V
    }

    # SPS map: samples per second -> bitfield
    _DR_BITS = {
        8:   0b000,
        16:  0b001,
        32:  0b010,
        64:  0b011,
        128: 0b100,  # default
        250: 0b101,
        475: 0b110,
        860: 0b111,
    }

    def __init__(self, i2c_bus: int = 1, address: int = DEFAULT_ADDR):
        self.bus = SMBus(i2c_bus)
        self.address = address

    def _lsb_size(self, pga_fs_v: float) -> float:
        # ADS1115 is 16-bit signed; code range -32768..32767 over ±FS
        return pga_fs_v / 32768.0

    def _mux_bits_single_ended(self, channel: int) -> int:
        if channel not in (0, 1, 2, 3):
            raise ValueError("channel must be 0..3")
        # MUX[14:12]: 100=A0,GND; 101=A1,GND; 110=A2,GND; 111=A3,GND
        return 0b100 + channel

    def _build_config(self, channel: int, pga_fs_v: float, sps: int,
                      mode_single_shot: bool, start: bool) -> int:
        # Disable comparator: COMP_QUE=11 (bits1:0), rest default OK.
        config = 0x0003

        # DR bits [7:5]
        dr_bits = self._DR_BITS.get(sps)
        if dr_bits is None:
            raise ValueError(f"Unsupported sps {sps}. Choose one of {sorted(self._DR_BITS)}")
        config |= (dr_bits & 0b111) << 5

        # MODE bit [8]
        if mode_single_shot:
            config |= (1 << 8)  # single-shot
        else:
            config |= 0         # continuous

        # PGA bits [11:9]
        pga_bits = self._PGA_BITS.get(pga_fs_v)
        if pga_bits is None:
            raise ValueError(f"Unsupported PGA ±{pga_fs_v}V. Choose one of {sorted(self._PGA_BITS)}")
        config |= (pga_bits & 0b111) << 9

        # MUX bits [14:12] for single-ended channel
        mux_bits = self._mux_bits_single_ended(channel)
        config |= (mux_bits & 0b111) << 12

        # OS bit [15] (start conversion for single-shot)
        if start:
            config |= (1 << 15)

        return config

    def _write_config(self, value: int):
        # ADS1115 expects big-endian for 16-bit registers
        self.bus.write_i2c_block_data(self.address, self.REG_CONFIG, [(value >> 8) & 0xFF, value & 0xFF])

    def _read_u16(self, reg: int) -> int:
        data = self.bus.read_i2c_block_data(self.address, reg, 2)
        return (data[0] << 8) | data[1]

    def _read_s16(self, reg: int) -> int:
        u = self._read_u16(reg)
        return u - 0x10000 if u & 0x8000 else u

    def read_single_ended(self, channel: int, pga_fs_v: float = 4.096, sps: int = 128) -> float:
        """
        Single-shot read on one channel (0..3). Returns voltage in volts.
        pga_fs_v is the full-scale (±V). Use 6.144, 4.096, 2.048, 1.024, 0.512, or 0.256.
        sps is the data rate: 8..860 per the ADS1115 table.
        """
        # Build + write config; OS=1 to start
        cfg = self._build_config(channel, pga_fs_v, sps, mode_single_shot=True, start=True)
        self._write_config(cfg)

        # Poll OS bit until conversion completes (OS=1 when ready)
        # Datasheet: conversion time ~1/sps; add a small guard.
        timeout_s = 1.0 / sps + 0.01
        t0 = time.perf_counter()
        while True:
            cfg_now = self._read_u16(self.REG_CONFIG)
            if cfg_now & 0x8000:  # OS bit
                break
            if time.perf_counter() - t0 > timeout_s:
                # fall back to just reading; usually still fine
                break
            # light polling
            time.sleep(0.0005)

        raw = self._read_s16(self.REG_CONVERSION)
        volts = raw * self._lsb_size(pga_fs_v)
        return volts

    def start_continuous(self, channel: int, pga_fs_v: float = 4.096, sps: int = 250):
        """
        Put device in continuous-conversion mode on a channel.
        Call read_continuous() to fetch subsequent samples.
        """
        cfg = self._build_config(channel, pga_fs_v, sps, mode_single_shot=False, start=False)
        self._write_config(cfg)
        # One conversion period before first valid sample
        time.sleep(1.0 / sps)

    def read_continuous(self, pga_fs_v: float = 4.096) -> float:
        raw = self._read_s16(self.REG_CONVERSION)
        return raw * self._lsb_size(pga_fs_v)

    def set_comparator_window(self, low_v: float, high_v: float, pga_fs_v: float = 4.096):
        """
        Optional: program the threshold registers (ALERT/RDY pin).
        """
        lsb = self._lsb_size(pga_fs_v)
        lo = int(max(min(low_v / lsb, 32767), -32768)) & 0xFFFF
        hi = int(max(min(high_v / lsb, 32767), -32768)) & 0xFFFF
        self.bus.write_i2c_block_data(self.address, self.REG_LO_THRESH, [(lo >> 8) & 0xFF, lo & 0xFF])
        self.bus.write_i2c_block_data(self.address, self.REG_HI_THRESH, [(hi >> 8) & 0xFF, hi & 0xFF])
    
if __name__ == "__main__":
    
    adc = ADS1115(address=0x48)  

    # Example: continuous stream on A0
    adc.start_continuous(channel=0, pga_fs_v=4.096, sps=250)
    print("Streaming AIN0 (Ctrl+C to stop)...")
    try:
        while True:
            v = adc.read_continuous(pga_fs_v=4.096)
            print(f"\rAIN0: {v:.6f}", end="", flush=True)
            time.sleep(0.20)
    except KeyboardInterrupt:
        print("\nDone.")

