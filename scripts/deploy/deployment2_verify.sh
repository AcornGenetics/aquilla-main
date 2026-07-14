#!/usr/bin/env bash
# deployment2_verify.sh — Run phase verification tests independently
# Usage: sudo bash deployment2_verify.sh [phase_number|smoke]
# If no argument given, runs all phases.
set -euo pipefail

[[ "${EUID}" -ne 0 ]] && { echo "Run as root: sudo bash deployment2_verify.sh"; exit 1; }

# Source device env if available
DEVICE_ENV="/opt/aquila/config/device.env"
[[ -f "${DEVICE_ENV}" ]] && source "${DEVICE_ENV}"
DEVICE_HOSTNAME="${DEVICE_HOSTNAME:-unknown}"

PASS=0
FAIL=0

check() {
    local phase=$1 desc=$2 cmd=$3
    if eval "${cmd}" >/dev/null 2>&1; then
        echo "  ✓ [Phase ${phase}] ${desc}"
        (( PASS++ )) || true
    else
        echo "  ✗ [Phase ${phase}] ${desc}"
        (( FAIL++ )) || true
    fi
}

# ═══════════════════════════════════════════════════════════════════════════════

test_phase_1() {
    echo "── Phase 1: OS Prerequisites"
    check 1 "curl installed"       "which curl"
    check 1 "chromium installed"   "which chromium"
    check 1 "kanshi installed"     "which kanshi"
    check 1 "python3 installed"    "which python3"
    check 1 "python3-gi available" "python3 -c 'import gi'"
    check 1 "WebKit2 available"    "dpkg -l libwebkit2gtk-4.1-0 | grep -q '^ii'"
}

test_phase_2() {
    echo "── Phase 2: Hardware Interfaces"
    check 2 "I2C enabled in boot config" "grep -q 'dtparam=i2c_arm=on' /boot/firmware/config.txt"
    check 2 "SPI enabled in boot config" "grep -q 'dtparam=spi=on' /boot/firmware/config.txt"
    check 2 "/dev/i2c-1 exists"          "test -e /dev/i2c-1"
    check 2 "/dev/spidev0.0 exists"      "test -e /dev/spidev0.0"
}

test_phase_3() {
    echo "── Phase 3: Docker"
    check 3 "Docker installed"         "docker --version"
    check 3 "Docker Compose installed" "docker compose version"
    check 3 "Docker service enabled"   "systemctl is-enabled docker | grep -q enabled"
    check 3 "Docker service running"   "systemctl is-active docker | grep -q active"
    check 3 "pi in docker group"       "groups pi | grep -q docker"
}

test_phase_4() {
    echo "── Phase 4: Autologin"
    check 4 "autologin.conf exists"        "test -f /etc/lightdm/lightdm.conf.d/autologin.conf"
    check 4 "autologin-user=pi"           "grep -q 'autologin-user=pi' /etc/lightdm/lightdm.conf.d/autologin.conf"
    check 4 "autologin-session=rpd-labwc" "grep -q 'autologin-session=rpd-labwc' /etc/lightdm/lightdm.conf.d/autologin.conf"
}

test_phase_5() {
    echo "── Phase 5: Chromium Kiosk"
    local d="/home/pi/.config/autostart/chromium-kiosk.desktop"
    check 5 ".desktop file exists"        "test -f ${d}"
    check 5 "Wayland flag present"        "grep -q -- '--ozone-platform=wayland' ${d}"
    check 5 "password-store flag present" "grep -q -- '--password-store=basic' ${d}"
    check 5 "URL not quoted"              "grep -qv '\"http' ${d}"
    check 5 "Correct URL"                 "grep -q 'http://localhost:8090' ${d}"
}

test_phase_6() {
    echo "── Phase 6: Display Rotation"
    local k="/home/pi/.config/kanshi/config"
    local l="/home/pi/.config/labwc/autostart"
    check 6 "kanshi config exists"      "test -f ${k}"
    check 6 "kanshi config multiline"   "test \$(wc -l < ${k}) -gt 1"
    check 6 "HDMI-A-2 present"          "grep -q 'HDMI-A-2' ${k}"
    check 6 "transform 270 set"         "grep -q 'transform 270' ${k}"
    check 6 "labwc autostart exists"    "test -f ${l}"
    check 6 "kanshi in labwc autostart" "grep -q 'kanshi' ${l}"
    check 6 "correct file ownership"    "stat -c '%U' ${k} | grep -q pi"
}

test_phase_7() {
    echo "── Phase 7: Persistent Directories"
    check 7 "/opt/aquila/config"          "test -d /opt/aquila/config"
    check 7 "/opt/aquila/profiles"        "test -d /opt/aquila/profiles"
    check 7 "/opt/aquila/results"         "test -d /opt/aquila/results"
    check 7 "/opt/aquila/logs/results"    "test -d /opt/aquila/logs/results"
    check 7 "/opt/aquila/logs/plots"      "test -d /opt/aquila/logs/plots"
    check 7 "/opt/aquila/logs/pcr"        "test -d /opt/aquila/logs/pcr"
    check 7 "/opt/aquila/logs/optics"     "test -d /opt/aquila/logs/optics"
    check 7 "/opt/aquila/logs/lid_heater" "test -d /opt/aquila/logs/lid_heater"
    check 7 "/opt/fleet"                  "test -d /opt/fleet"
}

test_phase_8() {
    echo "── Phase 8: Device Identity Files"
    check 8 "device.env exists"            "test -f /opt/aquila/config/device.env"
    check 8 "DEVICE_HOSTNAME set"          "grep -q 'DEVICE_HOSTNAME=' /opt/aquila/config/device.env"
    check 8 "DEVICE_ID set"                "grep -q 'DEVICE_ID=' /opt/aquila/config/device.env"
    check 8 "IMAGE_TAG set"                "grep -q 'IMAGE_TAG=' /opt/aquila/config/device.env"
    check 8 "WATCHTOWER_TOKEN set"         "grep -q 'WATCHTOWER_HTTP_API_TOKEN=' /opt/aquila/config/device.env"
    check 8 "/opt/fleet/.env exists"       "test -f /opt/fleet/.env"
    check 8 "host_config.json valid JSON"  "python3 -m json.tool /opt/aquila/config/host_config.json"
    check 8 "state_config.json valid JSON" "python3 -m json.tool /opt/aquila/config/state_config.json"
    check 8 "lid_heater_config.json valid JSON" \
        "python3 -m json.tool /opt/aquila/config/lid_heater_config.json"
}

test_phase_9() {
    echo "── Phase 9: Docker Images"
    check 9 "GHCR login succeeded"            "grep -q 'ghcr.io' /root/.docker/config.json"
    check 9 "docker-compose.yml downloaded"   "test -f /opt/fleet/docker-compose.yml"
    check 9 "compose file non-empty"          "test -s /opt/fleet/docker-compose.yml"
    check 9 "backend image pulled"            "docker images | grep -q 'aquilla-main-api'"
    check 9 "ui image pulled"                 "docker images | grep -q 'aquilla-main-ui'"
    check 9 "update.sh exists and executable" "test -x /opt/fleet/update.sh"
}

test_phase_10() {
    echo "── Phase 10: systemd Service"
    check 10 "service file exists" "test -f /etc/systemd/system/aquila-stack.service"
    check 10 "service enabled"     "systemctl is-enabled aquila-stack.service | grep -q enabled"
}

test_phase_11() {
    echo "── Phase 11: Fleet Device Configuration"
    local token
    token=$(grep WATCHTOWER_HTTP_API_TOKEN /opt/aquila/config/device.env | cut -d= -f2)
    check 11 "DEVICE_ID set"             "grep -q 'DEVICE_ID=' /opt/aquila/config/device.env"
    check 11 "IMAGE_TAG is valid ring"   "grep -E 'IMAGE_TAG=(sandbox|dev|pilot|prod)' /opt/aquila/config/device.env"
    check 11 "aquila-backend running"    \
        "docker ps --filter name=aquila-backend --format '{{.Status}}' | grep -q Up"
    check 11 "aquila-app running"        \
        "docker ps --filter name=aquila-app --format '{{.Status}}' | grep -q Up"
    check 11 "aquila-ui running"         \
        "docker ps --filter name=aquila-ui --format '{{.Status}}' | grep -q Up"
    check 11 "backend reachable :8090"   "curl -sf http://localhost:8090/health"
    check 11 "aquila-watchtower running" \
        "docker ps --filter name=aquila-watchtower --format '{{.Status}}' | grep -q Up"
    check 11 "watchtower webhook responds" \
        "curl -sf -o /dev/null -w '%{http_code}' -X POST http://localhost:8081/v1/update \
         -H 'Authorization: Bearer ${token}' | grep -q 200"
}

test_phase_12() {
    echo "── Phase 12: Tailscale"
    check 12 "tailscale installed"    "which tailscale"
    check 12 "tailscaled active"      "systemctl is-active tailscaled | grep -q active"
    check 12 "device authenticated"   "tailscale status | grep -q ${DEVICE_HOSTNAME}"
    check 12 "Tailscale IPs assigned" \
        "tailscale status --json | python3 -c \"import sys,json; d=json.load(sys.stdin); assert d.get('TailscaleIPs')\""
}

test_phase_13() {
    echo "── Phase 13: Grafana Alloy"
    check 13 "alloy installed"       "which alloy"
    check 13 "alloy service active"  "systemctl is-active alloy.service | grep -q active"
    check 13 "alloy service enabled" "systemctl is-enabled alloy.service | grep -q enabled"
}

test_phase_14() {
    echo "── Phase 14: Quiet Boot"
    check 14 "tty3 in cmdline"     "grep -q 'console=tty3' /boot/cmdline.txt"
    check 14 "tty1 not in cmdline" "! grep -q 'console=tty1' /boot/cmdline.txt"
}

test_smoke() {
    echo "── Post-Reboot Smoke Tests"
    check smoke "aquila containers running (4)" \
        "test \$(docker ps --format '{{.Names}}' | grep -c aquila) -ge 4"
    check smoke "Backend API healthy"          "curl -sf http://localhost:8090/health"
    check smoke "Chromium process running"     "pgrep -x chromium"
    check smoke "kanshi process running"       "pgrep -x kanshi"
    check smoke "/dev/i2c-1 accessible"        "test -e /dev/i2c-1"
    check smoke "/dev/spidev0.0 accessible"    "test -e /dev/spidev0.0"
}

# ═══════════════════════════════════════════════════════════════════════════════
# Entry point
# ═══════════════════════════════════════════════════════════════════════════════

ALL_PHASES=(1 2 3 4 5 6 7 8 9 10 11 12 13 14 smoke)

if [[ "${1:-}" == "smoke" ]]; then
    test_smoke
elif [[ -n "${1:-}" ]]; then
    "test_phase_${1}"
else
    for p in "${ALL_PHASES[@]}"; do
        if [[ "${p}" == "smoke" ]]; then
            test_smoke
        else
            "test_phase_${p}"
        fi
        echo ""
    done
fi

echo ""
echo "Results: ${PASS} passed, ${FAIL} failed"
[[ "${FAIL}" -eq 0 ]] && exit 0 || exit 1
