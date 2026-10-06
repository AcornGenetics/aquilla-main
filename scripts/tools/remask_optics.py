#!/usr/bin/env python3
"""Re-mask a leftover raw optics safety log into the legacy optics file (ADR-024).

After a crash or an abnormal stop that left a raw safety log without a finished
optics file, reconstruct the optics file from it:

    python -m scripts.tools.remask_optics <raw_log> <optics_out> [--wells 4|15] [--no-fast-settling]

The raw log is masked pass-by-pass (bounded RAM). Output is identical to the
live write-out apart from the write-time timestamp column (see
OpticalRead.print_result).
"""
import argparse
import time

from aq_lib.adc_class import OpticalRead


def remask(raw_log, optics_out, wells=4, fast_settling=True):
    # Build a masker without the hardware __init__ (no SPI/GPIO needed to re-mask).
    reader = object.__new__(OpticalRead)
    reader.blink_num = 7 if fast_settling else 10
    reader.two_adcs = True
    reader.well_15 = (wells == 15)
    reader.n_unrepairable = 0
    reader.n_retries = reader.n_failed_reads = reader.n_stale_frames = 0
    reader.t0 = time.time()
    with open(optics_out, "w") as fp:
        reader.data_file = fp
        reader.optics_from_raw_log(raw_log)


def main():
    ap = argparse.ArgumentParser(description="Re-mask a raw optics safety log (ADR-024).")
    ap.add_argument("raw_log", help="path to the raw safety log")
    ap.add_argument("optics_out", help="path to write the reconstructed optics file")
    ap.add_argument("--wells", type=int, default=4, choices=(4, 15))
    ap.add_argument("--no-fast-settling", action="store_true",
                    help="capture used 10 samples/half-flash instead of 7")
    args = ap.parse_args()
    remask(args.raw_log, args.optics_out, args.wells, not args.no_fast_settling)


if __name__ == "__main__":
    main()
