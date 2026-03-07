import json
import subprocess
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
CONFIG_PATH = BASE_DIR / "config_files" / "wifi.json"
WPA_SUPPLICANT_PATH = Path("/etc/wpa_supplicant/wpa_supplicant.conf")


def _load_config():
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"Missing wifi config at {CONFIG_PATH}")
    with CONFIG_PATH.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    ssid = (data.get("ssid") or "").strip()
    psk = (data.get("psk") or data.get("password") or "").strip()
    country = (data.get("country") or "US").strip()
    if not ssid or not psk:
        raise ValueError("wifi.json must include non-empty ssid and psk")
    return ssid, psk, country


def _read_wpa_lines():
    if WPA_SUPPLICANT_PATH.exists():
        return WPA_SUPPLICANT_PATH.read_text(encoding="utf-8").splitlines()
    return []


def _write_wpa_lines(lines):
    content = "\n".join(lines) + "\n"
    WPA_SUPPLICANT_PATH.write_text(content, encoding="utf-8")


def _strip_network_block(lines, ssid):
    updated = []
    in_block = False
    block_matches = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("network="):
            in_block = True
            block_matches = False
        if in_block and stripped.startswith("ssid="):
            ssid_value = stripped.split("=", 1)[1].strip().strip('"')
            if ssid_value == ssid:
                block_matches = True
        if in_block and stripped == "}":
            if not block_matches:
                updated.append(line)
            in_block = False
            block_matches = False
            continue
        if in_block:
            if not block_matches:
                updated.append(line)
            continue
        updated.append(line)
    return updated


def _ensure_header(lines, country):
    header = [
        f"country={country}",
        "ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev",
        "update_config=1",
    ]
    if not lines:
        return header
    has_country = any(line.strip().startswith("country=") for line in lines)
    if not has_country:
        lines = header + lines
    return lines


def apply_wifi_config():
    ssid, psk, country = _load_config()
    lines = _read_wpa_lines()
    lines = _ensure_header(lines, country)
    lines = _strip_network_block(lines, ssid)
    lines.append("network={")
    lines.append(f"    ssid=\"{ssid}\"")
    lines.append(f"    psk=\"{psk}\"")
    lines.append("    key_mgmt=WPA-PSK")
    lines.append("}")
    _write_wpa_lines(lines)
    subprocess.run(["wpa_cli", "-i", "wlan0", "reconfigure"], check=False)


if __name__ == "__main__":
    apply_wifi_config()
