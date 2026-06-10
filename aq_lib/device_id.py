import os
import re


def read_rpi_serial(cpuinfo_path: str = "/proc/cpuinfo") -> str | None:
    try:
        with open(cpuinfo_path) as f:
            content = f.read()
    except OSError:
        return None
    match = re.search(r"^Serial\s*:\s*([0-9a-fA-F]+)", content, re.MULTILINE)
    if not match:
        return None
    serial = match.group(1)
    if not serial.lstrip("0"):
        return None
    return serial


def inject_hw_serial_env(cpuinfo_path: str = "/proc/cpuinfo") -> None:
    if os.environ.get("AQ_SYNC_DEVICE_ID"):
        return
    serial = read_rpi_serial(cpuinfo_path)
    if serial:
        os.environ["AQ_SYNC_DEVICE_ID"] = serial
