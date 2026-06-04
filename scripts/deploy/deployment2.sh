#!/usr/bin/env bash
# deployment2.sh — Aquila device deployment
# Usage: sudo bash deployment2.sh
# All values can be pre-set as env vars to skip prompts:
#   DEVICE_HOSTNAME=sn04 IMAGE_TAG=prod GHCR_USER=... GHCR_TOKEN=... sudo bash deployment2.sh
set -euo pipefail

# ── Preflight ─────────────────────────────────────────────────────────────────
[[ "${EUID}" -ne 0 ]] && { echo "Run as root: sudo bash deployment2.sh"; exit 1; }

PI_HOME="/home/pi"
GHCR_REPO="${GHCR_REPO:-acorngenetics/aquilla-main}"
RAW_REPO_URL="https://raw.githubusercontent.com/${GHCR_REPO}/main"
MEERSTETTER_XMLS=(${MEERSTETTER_XMLS:-"24NOV25.SN1.Config.w.PT1000.cal.1.xml"})

# ── Load existing device config if present (allows re-runs without re-entering values) ──
if [[ -f /opt/aquila/config/device.env ]]; then
    echo "  ℹ Found existing /opt/aquila/config/device.env — loading saved values"
    while IFS='=' read -r key val; do
        [[ -z "${key}" || "${key}" == \#* ]] && continue
        # Only set if not already in environment
        eval "_existing=\"\${${key}:-}\""
        if [[ -z "${_existing}" ]]; then
            export "${key}=${val}"
        fi
    done < /opt/aquila/config/device.env
fi

# Load lid heater config if present
if [[ -f /opt/aquila/config/lid_heater_config.json ]]; then
    LID_HEATER_LOWER_BOUND="${LID_HEATER_LOWER_BOUND:-$(python3 -c "import json; print(json.load(open('/opt/aquila/config/lid_heater_config.json'))['lower_bound'])" 2>/dev/null || true)}"
    LID_HEATER_UPPER_BOUND="${LID_HEATER_UPPER_BOUND:-$(python3 -c "import json; print(json.load(open('/opt/aquila/config/lid_heater_config.json'))['upper_bound'])" 2>/dev/null || true)}"
fi

# Load drawer read_steps if present
if [[ -f /opt/aquila/config/host_config.json && -n "${DEVICE_HOSTNAME:-}" ]]; then
    DRAWER_READ_STEPS="${DRAWER_READ_STEPS:-$(python3 -c "import json; c=json.load(open('/opt/aquila/config/host_config.json')); print(c.get('${DEVICE_HOSTNAME}',{}).get('drawer',{}).get('read_steps',''))" 2>/dev/null || true)}"
fi

# ── Helpers ───────────────────────────────────────────────────────────────────
PHASE=""

phase_start() {
    PHASE=$1
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo " Phase ${PHASE} — $2"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
}

phase_pass() {
    echo "✓ Phase ${PHASE} complete — $1"
}

phase_fail() {
    echo "✗ Phase ${PHASE} FAILED — $1"
    exit 1
}

prompt_if_unset() {
    local var=$1 msg=$2 secret=${3:-false}
    local _cur=""
    eval "_cur=\"\${${var}:-}\""
    [[ -n "${_cur}" ]] && return
    if [[ "${secret}" == "true" ]]; then
        read -rsp "[Phase ${PHASE}] ${msg}: " "${var}" </dev/tty; echo ""
    else
        read -rp  "[Phase ${PHASE}] ${msg}: " "${var}" </dev/tty; echo ""
    fi
}

run_test() {
    local desc=$1 cmd=$2
    if eval "${cmd}" >/dev/null 2>&1; then
        echo "  ✓ ${desc}"
    else
        phase_fail "${desc}"
    fi
}

# ═══════════════════════════════════════════════════════════════════════════════
# Phase 1 — OS Prerequisites and Host Packages
# ═══════════════════════════════════════════════════════════════════════════════
phase_start 1 "OS Prerequisites and Host Packages"

apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get upgrade -y -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y \
    curl ca-certificates gnupg gettext-base python3 \
    chromium openbox \
    xserver-xorg x11-xserver-utils xinput \
    python3-gi gir1.2-gtk-3.0 gir1.2-webkit2-4.1 libwebkit2gtk-4.1-0 \
    xterm unclutter

run_test "curl installed"       "which curl"
run_test "chromium installed"   "which chromium"
run_test "openbox installed"    "which openbox"
run_test "xrandr installed"     "which xrandr"
run_test "xinput installed"     "which xinput"
run_test "python3 installed"    "which python3"
run_test "python3-gi available" "python3 -c 'import gi'"
run_test "WebKit2 available"    "dpkg -l libwebkit2gtk-4.1-0 | grep -q '^ii'"

phase_pass "all host packages installed"

# ═══════════════════════════════════════════════════════════════════════════════
# Phase 2 — Hardware Interfaces (I2C + SPI)
# ═══════════════════════════════════════════════════════════════════════════════
phase_start 2 "Hardware Interfaces (I2C + SPI)"

raspi-config nonint do_i2c 0
raspi-config nonint do_spi 0

run_test "I2C enabled in boot config" "grep -q 'dtparam=i2c_arm=on' /boot/firmware/config.txt"
run_test "SPI enabled in boot config" "grep -q 'dtparam=spi=on' /boot/firmware/config.txt"
run_test "/dev/i2c-1 exists"          "test -e /dev/i2c-1"

if [[ ! -e /dev/spidev0.0 ]]; then
    echo ""
    echo "  /dev/spidev0.0 not yet present — reboot required to load SPI kernel module."
    echo "  Rebooting in 5 seconds... Re-run deployment2.sh after reboot to continue from Phase 3."
    touch /tmp/aquila_spi_reboot_pending
    sleep 5
    reboot
fi

run_test "/dev/spidev0.0 exists"      "test -e /dev/spidev0.0"

phase_pass "I2C and SPI enabled, /dev/i2c-1 and /dev/spidev0.0 present"

# ═══════════════════════════════════════════════════════════════════════════════
# Phase 3 — Docker
# ═══════════════════════════════════════════════════════════════════════════════
phase_start 3 "Docker"

if ! command -v docker >/dev/null 2>&1; then
    curl -fsSL https://get.docker.com | sh
fi
DEBIAN_FRONTEND=noninteractive apt-get install -y docker-compose-plugin
usermod -aG docker pi
systemctl enable --now docker

run_test "Docker installed"         "docker --version"
run_test "Docker Compose installed" "docker compose version"
run_test "Docker service enabled"   "systemctl is-enabled docker | grep -q enabled"
run_test "Docker service running"   "systemctl is-active docker | grep -q active"
run_test "pi in docker group"       "groups pi | grep -q docker"

phase_pass "Docker installed and running, pi in docker group"

# ═══════════════════════════════════════════════════════════════════════════════
# Phase 4 — Autologin (X11/Openbox)
# ═══════════════════════════════════════════════════════════════════════════════
phase_start 4 "Autologin (X11/Openbox)"

# raspi-config sets graphical target and enables LightDM autologin, but on
# Bookworm it writes autologin-session=rpd-labwc (Wayland) into lightdm.conf.
# We run it first for its side-effects, then overwrite lightdm.conf completely
# so no Wayland session entries survive to conflict with X11/Openbox.
raspi-config nonint do_boot_behaviour B4

# Disable the Wayland compositor services so they don't race with X11
systemctl disable --now wayfire.service labwc.service 2>/dev/null || true

# Overwrite main lightdm.conf wholesale to purge the rpd-labwc entry raspi-config just wrote
cat > /etc/lightdm/lightdm.conf <<'EOF'
[Seat:*]
autologin-user=pi
autologin-session=openbox
user-session=openbox
EOF

mkdir -p /etc/lightdm/lightdm.conf.d
cat > /etc/lightdm/lightdm.conf.d/autologin.conf <<'EOF'
[Seat:*]
autologin-user=pi
autologin-session=openbox
EOF

# Fix double-load of modesetting driver (dixRegisterPrivateKey crash on Pi):
# fbdev acts as a fallback that keeps X alive until card1 activates via udev hotplug,
# which triggers a second modesetting load. Removing fbdev prevents the fallback.
# ServerFlags must live in /etc/X11/xorg.conf (not xorg.conf.d) to take effect.
sudo apt remove --purge -y xserver-xorg-video-fbdev 2>/dev/null || true

mkdir -p /etc/X11/xorg.conf.d
cat > /etc/X11/xorg.conf.d/99-v3d.conf <<'EOF'
Section "OutputClass"
  Identifier "vc4"
  MatchDriver "vc4"
  Driver "modesetting"
  Option "PrimaryGPU" "true"
EndSection
EOF

tee /etc/X11/xorg.conf > /dev/null <<'EOF'
Section "ServerFlags"
  Option "AutoAddGPU" "false"
EndSection
EOF

run_test "autologin.conf exists"           "test -f /etc/lightdm/lightdm.conf.d/autologin.conf"
run_test "autologin-user=pi"               "grep -q 'autologin-user=pi' /etc/lightdm/lightdm.conf.d/autologin.conf"
run_test "autologin-session=openbox"       "grep -q 'autologin-session=openbox' /etc/lightdm/lightdm.conf.d/autologin.conf"
run_test "main lightdm.conf not rpd-labwc" "! grep -q 'autologin-session=rpd-labwc' /etc/lightdm/lightdm.conf"
run_test "lightdm enabled"                 "systemctl is-enabled lightdm | grep -q enabled"
run_test "xorg.conf has AutoAddGPU off"    "grep -q 'AutoAddGPU' /etc/X11/xorg.conf"
run_test "fbdev not installed"            "! dpkg -l xserver-xorg-video-fbdev 2>/dev/null | grep -q '^ii'"

phase_pass "LightDM configured for X11/Openbox autologin (Wayland compositor disabled)"

# ═══════════════════════════════════════════════════════════════════════════════
# Phase 5 — Chromium Kiosk (Openbox autostart)
# ═══════════════════════════════════════════════════════════════════════════════
phase_start 5 "Chromium Kiosk (Openbox autostart)"

# Remove stale Wayland/desktop launcher paths so only one launch path exists
rm -f "${PI_HOME}/.config/autostart/chromium-kiosk.desktop"
rm -f "${PI_HOME}/.config/labwc/autostart"

# Install boot splash page
curl -fsSL \
    "${RAW_REPO_URL}/aquila_web/static/splash.html" \
    -o /opt/aquila/splash.html

mkdir -p "${PI_HOME}/.config/openbox"

cat > "${PI_HOME}/.config/openbox/autostart" <<'EOF'
# Disable screen blanking and power management
xset s off
xset s noblank
xset -dpms

# Auto-detect connected HDMI output (handles HDMI-2, HDMI-A-2, etc.)
HDMI_OUT=$(xrandr --query | grep -E "^HDMI.* connected" | head -1 | awk '{print $1}')
if [ -n "$HDMI_OUT" ]; then
    xrandr --output "$HDMI_OUT" --mode 1024x768 --rate 60 --rotate right
fi

xinput set-prop "Focaltech Systems FT5926 MultiTouch" \
  "Coordinate Transformation Matrix" \
  0 1 0 -1 0 1 0 0 1

# Hide cursor immediately on touch — -root covers the whole screen, -noevents prevents re-show on touch
unclutter -idle 0 -root -noevents &

# Allow display and compositor to settle before launching Chromium
sleep 3

# If kiosk_disabled flag exists, show desktop instead of kiosk.
# Flag is in /tmp/ so it is cleared on reboot (kiosk relaunches normally).
if [ ! -f /tmp/kiosk_disabled ]; then
  chromium \
    --kiosk file:///opt/aquila/splash.html \
    --incognito \
    --noerrdialogs \
    --disable-infobars \
    --disable-session-crashed-bubble \
    --check-for-update-interval=31536000 \
    --disable-pinch \
    --overscroll-history-navigation=0 \
    --disable-features=TranslateUI \
    --touch-events=enabled \
    --enable-touch-drag-drop \
    --enable-gpu-rasterization \
    --use-angle=gles \
    --ozone-platform=x11 \
    --disable-web-security \
    --allow-file-access-from-files \
    --user-data-dir=/tmp/chromium-kiosk \
    --start-maximized \
    &
fi
EOF

chown -R pi:pi "${PI_HOME}/.config/openbox"

AUTOSTART="${PI_HOME}/.config/openbox/autostart"
run_test "openbox autostart exists"    "test -f ${AUTOSTART}"
run_test "splash page installed"       "test -f /opt/aquila/splash.html"
run_test "kiosk loads splash"          "grep -q 'splash.html' ${AUTOSTART}"
run_test "kiosk flag check present"    "grep -q 'kiosk_disabled' ${AUTOSTART}"
run_test "X11 platform flag"           "grep -q 'ozone-platform=x11' ${AUTOSTART}"
run_test "user-data-dir flag present"  "grep -q 'user-data-dir' ${AUTOSTART}"
run_test "touch-events flag"           "grep -q 'touch-events=enabled' ${AUTOSTART}"
run_test "xrandr auto-detect present"  "grep -q 'HDMI_OUT' ${AUTOSTART}"
run_test "xinput transform present"    "grep -q 'Coordinate Transformation Matrix' ${AUTOSTART}"
run_test "no stale Wayland .desktop"   "test ! -f ${PI_HOME}/.config/autostart/chromium-kiosk.desktop"
run_test "correct file ownership"      "stat -c '%U' ${AUTOSTART} | grep -q pi"

phase_pass "Openbox autostart configured — X11 kiosk with rotation and touch mapping"

# ═══════════════════════════════════════════════════════════════════════════════
# Phase 6 — Display and Touch (verified via autostart)
# ═══════════════════════════════════════════════════════════════════════════════
phase_start 6 "Display and Touch configuration"

# xrandr and xinput are called at runtime from Openbox autostart (Phase 5).
# This phase verifies the required tools are present on the host.
run_test "xrandr binary present"  "which xrandr"
run_test "xinput binary present"  "which xinput"
run_test "unclutter present"      "which unclutter"

# Disable the Raspberry Pi welcome wizard so it never appears on first boot
rm -f /etc/xdg/autostart/piwiz.desktop

run_test "piwiz disabled" "test ! -f /etc/xdg/autostart/piwiz.desktop"

chown -R pi:pi "${PI_HOME}/.config"

phase_pass "Display and touch tools verified — runtime config applied via Openbox autostart"

# ═══════════════════════════════════════════════════════════════════════════════
# Phase 7 — Persistent Directory Structure
# ═══════════════════════════════════════════════════════════════════════════════
phase_start 7 "Persistent Directory Structure"

mkdir -p /opt/aquila/config
mkdir -p /opt/aquila/profiles
mkdir -p /opt/aquila/profiles/bundled
mkdir -p /opt/aquila/profiles/local
mkdir -p /opt/aquila/results
mkdir -p /opt/aquila/logs/results
mkdir -p /opt/aquila/logs/plots
mkdir -p /opt/aquila/logs/pcr
mkdir -p /opt/aquila/logs/optics
mkdir -p /opt/aquila/logs/lid_heater
mkdir -p /opt/aquila/tests
mkdir -p /opt/fleet

run_test "/opt/aquila/config"           "test -d /opt/aquila/config"
run_test "/opt/aquila/profiles"         "test -d /opt/aquila/profiles"
run_test "/opt/aquila/profiles/bundled" "test -d /opt/aquila/profiles/bundled"
run_test "/opt/aquila/profiles/local"   "test -d /opt/aquila/profiles/local"
run_test "/opt/aquila/results"          "test -d /opt/aquila/results"
run_test "/opt/aquila/logs/results"     "test -d /opt/aquila/logs/results"
run_test "/opt/aquila/logs/plots"       "test -d /opt/aquila/logs/plots"
run_test "/opt/aquila/logs/pcr"         "test -d /opt/aquila/logs/pcr"
run_test "/opt/aquila/logs/optics"      "test -d /opt/aquila/logs/optics"
run_test "/opt/aquila/logs/lid_heater"  "test -d /opt/aquila/logs/lid_heater"
run_test "/opt/aquila/tests"            "test -d /opt/aquila/tests"
run_test "/opt/fleet"                   "test -d /opt/fleet"

phase_pass "all persistent directories created"

# ═══════════════════════════════════════════════════════════════════════════════
# Phase 8 — Device Identity and Config Files
# ═══════════════════════════════════════════════════════════════════════════════
phase_start 8 "Device Identity and Config Files"

prompt_if_unset DEVICE_HOSTNAME "Enter device hostname (e.g. sn04)"
prompt_if_unset IMAGE_TAG       "Enter IMAGE_TAG (dev/pilot/prod)"
prompt_if_unset GHCR_USER       "Enter GHCR username"
prompt_if_unset GHCR_TOKEN      "Enter GHCR personal access token"
prompt_if_unset LID_HEATER_UPPER_BOUND "Enter lid heater upper bound voltage (e.g. 0.34)"
prompt_if_unset LID_HEATER_LOWER_BOUND "Enter lid heater lower bound voltage (e.g. 0.20)"
prompt_if_unset DRAWER_READ_STEPS      "Enter drawer read_steps for this device (e.g. 160)"

WATCHTOWER_TOKEN="${WATCHTOWER_TOKEN:-$(openssl rand -hex 32)}"

# device.env
cat > /opt/aquila/config/device.env <<EOF
DEVICE_ID=${DEVICE_HOSTNAME}
DEVICE_HOSTNAME=${DEVICE_HOSTNAME}
IMAGE_TAG=${IMAGE_TAG}
GHCR_REPO=${GHCR_REPO}
RUN_MODE=prod
WATCHTOWER_HTTP_API_TOKEN=${WATCHTOWER_TOKEN}
GHCR_USERNAME=${GHCR_USER}
GHCR_TOKEN=${GHCR_TOKEN}
AQ_SRC_BASEDIR=/opt/aquila
EOF
chown root:root /opt/aquila/config/device.env
chmod 600 /opt/aquila/config/device.env

# fleet .env (Compose variable substitution)
cat > /opt/fleet/.env <<EOF
IMAGE_TAG=${IMAGE_TAG}
DEVICE_HOSTNAME=${DEVICE_HOSTNAME}
GHCR_REPO=${GHCR_REPO}
DEVICE_ENV_FILE=/opt/aquila/config/device.env
EOF

# host_config.json — keyed by device hostname to match repo structure
cat > /opt/aquila/config/host_config.json <<EOF
{
    "${DEVICE_HOSTNAME}": {
        "info": {
            "dock_name": "${DEVICE_HOSTNAME}"
        },
        "pcr": {
            "comport": "/dev/ttyUSB0",
            "baudrate": 57600,
            "vid": "0x0403",
            "pid": "0x6001",
            "device_type": "1089",
            "pcr_profile": "profiles/verification_profile.json"
        },
        "optics": {
            "rox pin": 22,
            "fam pin": 27,
            "LED_ON": 0,
            "LED_OFF": 1
        },
        "drawer": {
            "open_steps": 4500,
            "close_steps": 0,
            "read_steps": ${DRAWER_READ_STEPS},
            "home_steps": 5000,
            "step_multiplier": 32
        },
        "axis": {
            "home_steps": 2500,
            "step_multiplier": 8,
            "positions": [320, 675, 1030, 1380, 1740, 2080]
        },
        "adc": {
            "famP": 0,
            "famN": 1,
            "roxP": 2,
            "roxN": 3
        }
    }
}
EOF

# state_config.json — static, same on all devices
cat > /opt/aquila/config/state_config.json <<'EOF'
{
    "-5": {
        "title": "EXIT?",
        "text": "Press Exit again to close the GUI",
        "screen": "init"
    },
    "-4": {
        "title": "EXIT",
        "text": "Closing GUI...",
        "screen": "init"
    },
    "-3": {
        "title": "KEYBOARD INTERRUPT",
        "text": "Restart run when ready",
        "screen": "init"
    },
    "-2": {
        "title": "STATE ERRROR",
        "text": "Invalid state requested, change state",
        "screen": "init"
    },
    "-1": {
        "title": "INSTRUMENT ERROR",
        "text": "Power cycle the instrument, if error persists contact Arete Biosciences",
        "screen": "init"
    },
    "0": {
        "title": "INITIALIZING",
        "text": "Please wait for instrument to complete initialization",
        "screen": "init"
    },
    "1": {
        "title": "READY TO RUN",
        "text": "Select profile then select \"Run\" to start",
        "screen": "ready"
    },
    "2": {
        "title": "TEST IN PROGRESS",
        "text": "Please wait for instrument to complete",
        "screen": "running"
    },
    "3": {
        "title": "TEST COMPLETE",
        "text": "Remove samples. Select \"Next Run\" to run again.",
        "screen": "complete"
    },
    "4": {
        "title": "READY TO RUN",
        "text": "No profile selected. Try again then press \"Run\" to start",
        "screen": "ready"
    },
    "5": {
        "title": "Run_assay.py not configured to loop back yet",
        "text": "to rerun use cmdline to run run_assay.py",
        "screen": "init"
    },
    "6": {
        "title": "READY TO RUN",
        "text": "Drawer Open selected.",
        "screen": "ready"
    },
    "7": {
        "title": "READY TO RUN",
        "text": "Drawer Close selected.",
        "screen": "ready"
    },
    "8": {
        "title": "TEST COMPLETE",
        "text": "Drawer Open Selected",
        "screen": "complete"
    },
    "9": {
        "title": "TEST COMPLETE",
        "text": "Drawer close Selected",
        "screen": "complete"
    }
}
EOF

cat > /opt/aquila/config/lid_heater_config.json <<EOF
{
    "lower_bound": ${LID_HEATER_LOWER_BOUND},
    "upper_bound": ${LID_HEATER_UPPER_BOUND}
}
EOF

run_test "device.env exists"          "test -f /opt/aquila/config/device.env"
run_test "DEVICE_HOSTNAME set"        "grep -q 'DEVICE_HOSTNAME=' /opt/aquila/config/device.env"
run_test "DEVICE_ID set"              "grep -q 'DEVICE_ID=' /opt/aquila/config/device.env"
run_test "IMAGE_TAG set"              "grep -q 'IMAGE_TAG=' /opt/aquila/config/device.env"
run_test "WATCHTOWER_TOKEN set"       "grep -q 'WATCHTOWER_HTTP_API_TOKEN=' /opt/aquila/config/device.env"
run_test "GHCR username set"          "grep -q 'GHCR_USERNAME=' /opt/aquila/config/device.env"
run_test "GHCR token set"             "grep -q 'GHCR_TOKEN=' /opt/aquila/config/device.env"
run_test "/opt/fleet/.env exists"     "test -f /opt/fleet/.env"
run_test "host_config.json valid JSON" \
    "python3 -m json.tool /opt/aquila/config/host_config.json"
run_test "host_config.json has hostname key" \
    "python3 -c \"import json; c=json.load(open('/opt/aquila/config/host_config.json')); assert '${DEVICE_HOSTNAME}' in c, 'missing key'\""
run_test "state_config.json valid JSON" \
    "python3 -m json.tool /opt/aquila/config/state_config.json"
run_test "lid_heater_config.json valid JSON" \
    "python3 -m json.tool /opt/aquila/config/lid_heater_config.json"
run_test "drawer read_steps is numeric" \
    "python3 -c \"import json; c=json.load(open('/opt/aquila/config/host_config.json')); assert isinstance(c['${DEVICE_HOSTNAME}']['drawer']['read_steps'], int)\""

phase_pass "device.env, fleet .env, host_config.json, and state_config.json written"

# ═══════════════════════════════════════════════════════════════════════════════
# Phase 9 — GHCR Login, Download Compose File, and Pull Images
# ═══════════════════════════════════════════════════════════════════════════════
phase_start 9 "GHCR Login, Download Compose File, and Pull Images"

echo "${GHCR_TOKEN}" | docker login ghcr.io -u "${GHCR_USER}" --password-stdin
run_test "GHCR login succeeded" "grep -q 'ghcr.io' /root/.docker/config.json"

if [[ -f "/boot/firmware/config.txt" ]]; then
    tmp_boot_config=$(mktemp)
    if curl -fsSL -H "Authorization: token ${GHCR_TOKEN}" \
        "${RAW_REPO_URL}/config.txt" -o "${tmp_boot_config}"; then
        cp "${tmp_boot_config}" /boot/firmware/config.txt
    else
        echo "Warning: failed to download ${RAW_REPO_URL}/config.txt, skipping boot config update."
    fi
    rm -f "${tmp_boot_config}"
else
    echo "Warning: /boot/firmware/config.txt not found, skipping boot config update."
fi

# Ensure HDMI-2 force hotplug is set — prevents intermittent dark screen when
# the display is slow to send its EDID during boot
if [[ -f "/boot/firmware/config.txt" ]]; then
    if ! grep -q "hdmi_force_hotplug:1=1" /boot/firmware/config.txt; then
        echo "hdmi_force_hotplug:1=1" >> /boot/firmware/config.txt
    fi
fi

run_test "hdmi_force_hotplug:1=1 in config.txt" \
    "grep -q 'hdmi_force_hotplug:1=1' /boot/firmware/config.txt"

if [[ ${#MEERSTETTER_XMLS[@]} -gt 0 ]]; then
    mkdir -p /opt/aquila/config/meerstetter
    for xml_name in "${MEERSTETTER_XMLS[@]}"; do
        tmp_meerstetter=$(mktemp)
        if curl -fsSL -H "Authorization: token ${GHCR_TOKEN}" \
            "${RAW_REPO_URL}/config_files/meerstetter/${xml_name}" -o "${tmp_meerstetter}"; then
            cp -n "${tmp_meerstetter}" "/opt/aquila/config/meerstetter/${xml_name}"
        else
            echo "Warning: failed to download ${RAW_REPO_URL}/config_files/meerstetter/${xml_name}"
        fi
        rm -f "${tmp_meerstetter}"
    done
fi

curl -fsSL \
    -H "Authorization: token ${GHCR_TOKEN}" \
    "https://raw.githubusercontent.com/${GHCR_REPO}/main/fleet-config/docker-compose.yml" \
    -o /opt/fleet/docker-compose.yml

docker compose --env-file /opt/fleet/.env -f /opt/fleet/docker-compose.yml pull

# Capture digests of the images just pulled so OTA check can compare against them
RUNNING_IMAGE_DIGEST=$(docker inspect --format='{{index .RepoDigests 0}}' \
    "ghcr.io/${GHCR_REPO}-api:${IMAGE_TAG}" 2>/dev/null | awk -F@ '{print $2}')
RUNNING_IMAGE_DIGEST_UI=$(docker inspect --format='{{index .RepoDigests 0}}' \
    "ghcr.io/${GHCR_REPO}-ui:${IMAGE_TAG}" 2>/dev/null | awk -F@ '{print $2}')

# Re-write /opt/fleet/.env with the captured digests
cat > /opt/fleet/.env <<EOF
IMAGE_TAG=${IMAGE_TAG}
DEVICE_HOSTNAME=${DEVICE_HOSTNAME}
GHCR_REPO=${GHCR_REPO}
DEVICE_ENV_FILE=/opt/aquila/config/device.env
RUNNING_IMAGE_DIGEST=${RUNNING_IMAGE_DIGEST:-}
RUNNING_IMAGE_DIGEST_UI=${RUNNING_IMAGE_DIGEST_UI:-}
EOF

curl -fsSL \
    -H "Authorization: token ${GHCR_TOKEN}" \
    "https://raw.githubusercontent.com/${GHCR_REPO}/main/scripts/deploy/fleet-update.sh" \
    -o /opt/fleet/update.sh
chmod +x /opt/fleet/update.sh

run_test "docker-compose.yml downloaded"   "test -f /opt/fleet/docker-compose.yml"
run_test "compose file non-empty"          "test -s /opt/fleet/docker-compose.yml"
run_test "backend image pulled"            "docker images | grep -q 'aquilla-main-api'"
run_test "ui image pulled"                 "docker images | grep -q 'aquilla-main-ui'"
run_test "update.sh exists and executable" "test -x /opt/fleet/update.sh"

phase_pass "docker-compose.yml downloaded, all images pulled"

# ═══════════════════════════════════════════════════════════════════════════════
# Phase 10 — Register systemd Service
# ═══════════════════════════════════════════════════════════════════════════════
phase_start 10 "Register systemd Service"

cat > /etc/systemd/system/aquila-stack.service <<'EOF'
[Unit]
Description=Aquila Docker Compose Stack
After=docker.service network-online.target
Requires=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/opt/fleet
ExecStart=/usr/bin/docker compose --env-file /opt/fleet/.env -f /opt/fleet/docker-compose.yml up -d
ExecStop=/usr/bin/docker compose --env-file /opt/fleet/.env -f /opt/fleet/docker-compose.yml down
TimeoutStartSec=300

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable aquila-stack.service

run_test "service file exists" "test -f /etc/systemd/system/aquila-stack.service"
run_test "service enabled"     "systemctl is-enabled aquila-stack.service | grep -q enabled"

phase_pass "aquila-stack.service registered and enabled"

# ═══════════════════════════════════════════════════════════════════════════════
# Phase 11 — Fleet Device Configuration (Start Stack)
# ═══════════════════════════════════════════════════════════════════════════════
phase_start 11 "Fleet Device Configuration"

docker compose \
    --env-file /opt/fleet/.env \
    -f /opt/fleet/docker-compose.yml \
    up -d

echo "  Waiting for backend to become healthy..."
for i in $(seq 1 30); do
    if curl -sf http://localhost:8090/health >/dev/null 2>&1; then
        break
    fi
    sleep 2
done

echo "  Running Meerstetter first-time tuning..."
if ! docker exec \
    -e CONFIG_DIR=/opt/aquila/config \
    aquila-app \
    python3 - <<'PY'
from aq_lib.config_module import Config
from aq_lib.meerstetter import MeerStetter

config = Config()
device_type = int(config.pcr["device_type"])
pid = int(config.pcr["pid"], 16)
vid = int(config.pcr["vid"], 16)
device = MeerStetter.find_meer(vid, pid, device_type)
if not device:
    raise SystemExit("Meerstetter device not found")

meer = MeerStetter(device, baudrate=57600, timeout=1)
meer.set_parid_long(108, 1, 0)
meer.read(100)
meer.set_parid_long(2000, 1, 1)
meer.set_parid_float(3002, 3.0)
meer.set_parid_float(3010, 80.0)
meer.set_parid_float(3011, 5.0)
meer.set_parid_float(3012, 4.0)
meer.set_parid_float(3013, 0.0)
meer.set_parid_float(3030, 9.0)
meer.set_parid_float(3033, 73.0)
meer.set_parid_float(3040, 1.0)
meer.set_parid_long(108, 1, 1)
meer.close()
print("Meerstetter tuning applied")
PY
then
    phase_fail "Meerstetter tuning failed"
fi

WATCHTOWER_TOKEN=$(grep WATCHTOWER_HTTP_API_TOKEN /opt/aquila/config/device.env | cut -d= -f2)

run_test "DEVICE_ID set"            "grep -q 'DEVICE_ID=' /opt/aquila/config/device.env"
run_test "IMAGE_TAG is valid ring"   "grep -E 'IMAGE_TAG=(dev|pilot|prod)' /opt/aquila/config/device.env"
run_test "aquila-backend running"    \
    "docker ps --filter name=aquila-backend --format '{{.Status}}' | grep -q Up"
run_test "aquila-app running"        \
    "docker ps --filter name=aquila-app --format '{{.Status}}' | grep -q Up"
run_test "aquila-ui running"         \
    "docker ps --filter name=aquila-ui --format '{{.Status}}' | grep -q Up"
run_test "backend reachable :8090"   "curl -sf http://localhost:8090/health"
run_test "aquila-watchtower running" \
    "docker ps --filter name=aquila-watchtower --format '{{.Status}}' | grep -q Up"
run_test "watchtower webhook responds" \
    "curl -sf -o /dev/null -w '%{http_code}' -X POST http://localhost:8081/v1/update \
     -H 'Authorization: Bearer ${WATCHTOWER_TOKEN}' | grep -q 200"

phase_pass "fleet config set, containers running, backend reachable on :8090, watchtower webhook responding"

# ═══════════════════════════════════════════════════════════════════════════════
# Phase 11b — Kiosk Control Service
# ═══════════════════════════════════════════════════════════════════════════════
phase_start "11b" "Kiosk Control Service"

KIOSK_RAW="${RAW_REPO_URL}/scripts/kiosk-control"
curl -fsSL "${KIOSK_RAW}/kiosk_control.py" -o /usr/local/bin/kiosk_control.py
chmod +x /usr/local/bin/kiosk_control.py
curl -fsSL "${KIOSK_RAW}/kiosk-control.service" -o /etc/systemd/system/kiosk-control.service
systemctl daemon-reload
systemctl enable --now kiosk-control

# Create lxpanel-pi config for desktop WiFi panel (used when kiosk exits)
mkdir -p "${PI_HOME}/.config/lxpanel-pi/panels"
cat > "${PI_HOME}/.config/lxpanel-pi/panels/panel" <<'PANELEOF'
Global {
  edge=top
  align=left
  margin=0
  widthtype=percent
  width=100
  height=36
  autohide=0
  background=0
  iconsize=36
  monitor=0
}
Plugin {
  type=netman
}
Plugin {
  type=clock
}
PANELEOF
chown -R pi:pi "${PI_HOME}/.config/lxpanel-pi"

run_test "kiosk_control.py installed"       "test -f /usr/local/bin/kiosk_control.py"
run_test "kiosk-control service enabled"    "systemctl is-enabled kiosk-control | grep -q enabled"
run_test "kiosk-control service active"     "systemctl is-active kiosk-control | grep -q active"

echo "  Waiting for kiosk-control to become healthy..."
KIOSK_HEALTHY=false
for i in $(seq 1 10); do
    if curl -sf http://127.0.0.1:9191/health 2>/dev/null | grep -q true; then
        KIOSK_HEALTHY=true
        break
    fi
    sleep 1
done
[[ "${KIOSK_HEALTHY}" == "true" ]] || phase_fail "kiosk-control health (not responding on :9191 after 10s)"
echo "  ✓ kiosk-control health"
run_test "lxpanel-pi config exists"         "test -f ${PI_HOME}/.config/lxpanel-pi/panels/panel"

phase_pass "kiosk-control installed and healthy"

# ═══════════════════════════════════════════════════════════════════════════════
# Phase 12 — Tailscale
# ═══════════════════════════════════════════════════════════════════════════════
phase_start 12 "Tailscale"

if ! command -v tailscale >/dev/null 2>&1; then
    curl -fsSL https://tailscale.com/install.sh | sh
fi

prompt_if_unset TAILSCALE_KEY \
    "Enter Tailscale auth key (press Enter to authenticate interactively)"

if [[ -n "${TAILSCALE_KEY:-}" ]]; then
    tailscale up --ssh --authkey "${TAILSCALE_KEY}" --hostname "${DEVICE_HOSTNAME}"
else
    tailscale up --ssh --hostname "${DEVICE_HOSTNAME}"
    echo "  → Complete Tailscale authentication in your browser, then press Enter to continue."
    read -r
fi

run_test "tailscale installed"     "which tailscale"
run_test "tailscaled active"       "systemctl is-active tailscaled | grep -q active"
run_test "device authenticated"    "tailscale status | grep -q ${DEVICE_HOSTNAME}"
run_test "Tailscale IPs assigned"  \
    "tailscale status --json | python3 -c \"import sys,json; d=json.load(sys.stdin); assert d.get('TailscaleIPs')\""

phase_pass "Tailscale active, device authenticated as ${DEVICE_HOSTNAME}"

# ═══════════════════════════════════════════════════════════════════════════════
# Phase 13 — Grafana Alloy
# ═══════════════════════════════════════════════════════════════════════════════
phase_start 13 "Grafana Alloy"

prompt_if_unset GCLOUD_RW_API_KEY "Enter Grafana Cloud RW API key" true

GCLOUD_HOSTED_METRICS_ID="3026216" \
GCLOUD_HOSTED_METRICS_URL="https://prometheus-prod-56-prod-us-east-2.grafana.net/api/prom/push" \
GCLOUD_HOSTED_LOGS_ID="1508783" \
GCLOUD_HOSTED_LOGS_URL="https://logs-prod-036.grafana.net/loki/api/v1/push" \
GCLOUD_FM_URL="https://fleet-management-prod-008.grafana.net" \
GCLOUD_FM_POLL_FREQUENCY="60s" \
GCLOUD_FM_HOSTED_ID="1550994" \
ARCH="arm64" \
GCLOUD_RW_API_KEY="${GCLOUD_RW_API_KEY}" \
/bin/sh -c "$(curl -fsSL https://storage.googleapis.com/cloud-onboarding/alloy/scripts/install-linux.sh)"

systemctl enable alloy.service
systemctl restart alloy.service

run_test "alloy installed"       "which alloy"
run_test "alloy service active"  "systemctl is-active alloy.service | grep -q active"
run_test "alloy service enabled" "systemctl is-enabled alloy.service | grep -q enabled"

phase_pass "Grafana Alloy installed and running"

# ═══════════════════════════════════════════════════════════════════════════════
# Phase 14 — Quiet Boot
# ═══════════════════════════════════════════════════════════════════════════════
phase_start 14 "Quiet Boot"

CMDLINE_FILE="/boot/firmware/cmdline.txt"

if grep -q "console=tty1" "${CMDLINE_FILE}"; then
    sed -i 's/console=tty1/console=tty3/' "${CMDLINE_FILE}"
fi

if ! grep -q "vt.global_cursor_default=0" "${CMDLINE_FILE}"; then
    sed -i 's/$/ vt.global_cursor_default=0/' "${CMDLINE_FILE}"
fi

run_test "tty3 in cmdline"          "grep -q 'console=tty3' ${CMDLINE_FILE}"
run_test "tty1 not in cmdline"      "! grep -q 'console=tty1' ${CMDLINE_FILE}"
run_test "cursor hidden in cmdline" "grep -q 'vt.global_cursor_default=0' ${CMDLINE_FILE}"

phase_pass "quiet boot configured (tty3, cursor hidden)"

# ═══════════════════════════════════════════════════════════════════════════════
# Phase 14b — Plymouth Acorn Boot Theme
# ═══════════════════════════════════════════════════════════════════════════════
phase_start "14b" "Plymouth Acorn Boot Theme"

PLYMOUTH_THEME_DIR="/usr/share/plymouth/themes/acorn"
PLYMOUTH_INITRAMFS_HOOK="${PLYMOUTH_INITRAMFS_HOOK:-/usr/share/initramfs-tools/hooks/plymouth}"
# Fallback: some distros put it in /etc/initramfs-tools/hooks/ instead
[[ -f "/etc/initramfs-tools/hooks/plymouth" ]] && PLYMOUTH_INITRAMFS_HOOK="/etc/initramfs-tools/hooks/plymouth"
ACORN_LOGO_SVG="/opt/aquila/acorn_logo.svg"
ACORN_LOGO_PNG="${PLYMOUTH_THEME_DIR}/acorn_logo.png"

# Ensure Plymouth and theme packages are installed (idempotent)
apt-get install -y --no-install-recommends plymouth plymouth-themes librsvg2-bin 2>/dev/null

# Reinstall plymouth if initramfs hook is still missing (ensures early-boot coverage)
if [[ ! -f "${PLYMOUTH_INITRAMFS_HOOK}" ]]; then
    echo "  Plymouth initramfs hook missing — reinstalling plymouth..."
    apt-get install --reinstall -y plymouth 2>/dev/null
fi

# Download acornlogo SVG from repo if not already on device
if [[ ! -f "${ACORN_LOGO_SVG}" ]]; then
    curl -fsSL "${RAW_REPO_URL}/aquila_web/static/acornlogo.svg" \
        -o "${ACORN_LOGO_SVG}" 2>/dev/null || true
fi

# Create theme directory and convert SVG → PNG (256×256, white on transparent → white on black)
mkdir -p "${PLYMOUTH_THEME_DIR}"

if [[ -f "${ACORN_LOGO_SVG}" ]]; then
    # 192×192 px — large enough for 1080p without blurring, matches splash.html proportions
    rsvg-convert -w 192 -h 192 --background-color white "${ACORN_LOGO_SVG}" \
        -o "${ACORN_LOGO_PNG}" 2>/dev/null \
        || { echo "  ✗ rsvg-convert failed — logo PNG not created"; }
else
    echo "  ✗ acornlogo.svg not found — skipping logo conversion"
fi

# Install theme files from repo
curl -fsSL "${RAW_REPO_URL}/scripts/setup/plymouth/acorn.plymouth" \
    -o "${PLYMOUTH_THEME_DIR}/acorn.plymouth" 2>/dev/null
curl -fsSL "${RAW_REPO_URL}/scripts/setup/plymouth/acorn.script" \
    -o "${PLYMOUTH_THEME_DIR}/acorn.script" 2>/dev/null

# Set Acorn as default theme and rebuild initramfs
if [[ -f "${PLYMOUTH_THEME_DIR}/acorn.plymouth" ]]; then
    plymouth-set-default-theme acorn
    update-initramfs -u -k all 2>/dev/null
    echo "  ✓ Acorn Plymouth theme set and initramfs updated"
else
    echo "  ✗ acorn.plymouth not installed — theme not set"
fi

run_test "plymouth installed"           "command -v plymouth-set-default-theme"
run_test "plymouth initramfs hook"      "test -f ${PLYMOUTH_INITRAMFS_HOOK}"
run_test "acorn theme dir exists"       "test -d ${PLYMOUTH_THEME_DIR}"
run_test "acorn.plymouth file exists"   "test -f ${PLYMOUTH_THEME_DIR}/acorn.plymouth"
run_test "acorn.script file exists"     "test -f ${PLYMOUTH_THEME_DIR}/acorn.script"
run_test "acorn logo png exists"        "test -f ${ACORN_LOGO_PNG}"
run_test "acorn theme is default"       "plymouth-set-default-theme | grep -q acorn"

phase_pass "Plymouth Acorn theme installed (takes effect on next reboot)"

# ═══════════════════════════════════════════════════════════════════════════════
# Phase 15 — Download Security Script
# ═══════════════════════════════════════════════════════════════════════════════
phase_start 15 "Download Security Script"

curl -fsSL \
    -H "Authorization: token ${GHCR_TOKEN}" \
    "${RAW_REPO_URL}/scripts/setup/security.sh" \
    -o /opt/aquila/security.sh
chmod +x /opt/aquila/security.sh

run_test "security.sh downloaded"   "test -f /opt/aquila/security.sh"
run_test "security.sh executable"   "test -x /opt/aquila/security.sh"

phase_pass "security.sh saved to /opt/aquila/security.sh — run it manually when testing is complete"

# ═══════════════════════════════════════════════════════════════════════════════
# Phase 16 — Complete
# ═══════════════════════════════════════════════════════════════════════════════
echo ""
echo "=================================================="
echo " Deployment complete for device: ${DEVICE_HOSTNAME}"
echo ""
echo " IMPORTANT: On first boot, physically push the"
echo " drawer back to the home sensor before powering on."
echo ""
echo " MANUAL STEP REQUIRED after reboot:"
echo " If the login screen appears instead of the kiosk,"
echo " run: sudo raspi-config"
echo " Then: System Options → Boot / Auto Login → Desktop Autologin"
echo " Then reboot again."
echo ""
echo " SECURITY: When testing is complete, lock down the"
echo " device by running:"
echo "   sudo bash /opt/aquila/security.sh"
echo "=================================================="
echo ""
echo " Rebooting in 5 seconds... (Ctrl+C to cancel)"
sleep 5
reboot
