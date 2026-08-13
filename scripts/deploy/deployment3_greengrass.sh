#!/usr/bin/env bash
# deployment3_greengrass.sh — Aquila device deployment, Greengrass edition.
#
# Same device build as deployment2.sh (OS, hardware, Docker, kiosk, cert renewal,
# Tailscale, Alloy, security) but AWS IoT Greengrass — not Watchtower — owns image
# delivery and OTA. Installs the Greengrass nucleus in place on the existing RPi OS
# (no reflash) and provisions it with the device's existing acorn-ca cert (JITP ->
# Thing in the holding ring). In-place and REVERSIBLE:
#   sudo bash deployment3_greengrass.sh --revert
# tears Greengrass back out and re-enables the Watchtower/aquila-stack.service path.
#
# Usage: sudo bash deployment3_greengrass.sh
set -euo pipefail

# ── Preflight ─────────────────────────────────────────────────────────────────
[[ "${EUID}" -ne 0 ]] && { echo "Run as root: sudo bash deployment3_greengrass.sh"; exit 1; }

# ── Revert path (reversibility) ───────────────────────────────────────────────
# Remove Greengrass and hand the stack back to the Watchtower/compose service, so
# a device can roll off the migration without a reflash.
if [[ "${1:-}" == "--revert" ]]; then
    echo "Reverting Greengrass migration..."
    systemctl disable --now greengrass 2>/dev/null || true
    rm -f /etc/systemd/system/greengrass.service
    rm -rf /greengrass/v2
    systemctl daemon-reload
    # Re-enable the host compose stack that deployment2.sh installed.
    systemctl enable --now aquila-stack.service 2>/dev/null || \
        echo "  Re-run deployment2.sh to restore the Watchtower stack."
    echo "Revert complete — Greengrass removed."
    exit 0
fi

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
# Phase 3b — NetworkManager: disable BSSID pinning
# ═══════════════════════════════════════════════════════════════════════════════
phase_start "3b" "NetworkManager BSSID policy"

# Hotspots rotate their BSSID when toggled off/on. A dispatcher script that
# clears the pinned BSSID from every profile on each 'up' event ensures NM
# never refuses to reconnect because the AP's MAC address changed.
cat > /etc/NetworkManager/dispatcher.d/99-no-bssid <<'EOF'
#!/usr/bin/env bash
# Clear pinned BSSID from all WiFi profiles on every connection-up event so
# that hotspot BSSID rotation never prevents reconnection.
INTERFACE="$1"
EVENT="$2"
[[ "$EVENT" != "up" ]] && exit 0
nmcli -t -f NAME,TYPE connection show \
    | awk -F: '/wireless/{print $1}' \
    | while read -r name; do
        nmcli connection modify "$name" 802-11-wireless.bssid "" 2>/dev/null || true
      done
EOF
chmod +x /etc/NetworkManager/dispatcher.d/99-no-bssid

run_test "NM dispatcher installed" "test -x /etc/NetworkManager/dispatcher.d/99-no-bssid"

phase_pass "NetworkManager BSSID dispatcher installed"

# ═══════════════════════════════════════════════════════════════════════════════
# Phase 3c — Fleet DNS forwarder (dnsmasq)
# ═══════════════════════════════════════════════════════════════════════════════
# Docker freezes each container's DNS upstream at network-creation time; when a
# device moves networks (or Tailscale changes host DNS) that captured resolver
# becomes unreachable and in-container sync/OTA silently break (#314). A dnsmasq
# forwarder on the docker bridge gateway lets containers follow the host's own
# live resolver instead — the compose dns: entries point at 172.18.0.1.
phase_start "3c" "Fleet DNS forwarder (dnsmasq)"

DEBIAN_FRONTEND=noninteractive apt-get install -y dnsmasq

# Drop-in so we don't clobber the packaged /etc/dnsmasq.conf. Serve only the
# docker bridge gateway and forward to the host's own upstreams (dnsmasq reads
# /etc/resolv.conf by default). Loop-safe: never point upstream at ourselves
# (172.18.0.1) or Docker's embedded resolver (127.0.0.11).
cat > /etc/dnsmasq.d/aquila-fleet.conf <<'DNSMASQ'
# Aquila fleet DNS forwarder — serves the docker bridge, follows host DNS (#314).
listen-address=172.18.0.1
bind-dynamic
DNSMASQ

systemctl enable dnsmasq
systemctl restart dnsmasq

phase_pass "dnsmasq forwarder installed on 172.18.0.1"

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
# Start X with no cursor — touchscreen kiosk, the pointer must never render.
# Disabling the cursor at the X server level means it is never drawn at boot and
# never reappears on pointer/touch events.
xserver-command=X -nocursor
EOF

mkdir -p /etc/lightdm/lightdm.conf.d
cat > /etc/lightdm/lightdm.conf.d/autologin.conf <<'EOF'
[Seat:*]
autologin-user=pi
autologin-session=openbox
xserver-command=X -nocursor
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
run_test "cursor disabled (-nocursor)"     "grep -q 'X -nocursor' /etc/lightdm/lightdm.conf.d/autologin.conf"
run_test "lightdm enabled"                 "systemctl is-enabled lightdm | grep -q enabled"
run_test "xorg.conf has AutoAddGPU off"    "grep -q 'AutoAddGPU' /etc/X11/xorg.conf"
run_test "fbdev not installed"            "! dpkg -l xserver-xorg-video-fbdev 2>/dev/null | grep -q '^ii'"

phase_pass "LightDM configured for X11/Openbox autologin (Wayland compositor disabled)"

# ═══════════════════════════════════════════════════════════════════════════════
# Phase 6 — Display and Touch (verified via autostart)
# ═══════════════════════════════════════════════════════════════════════════════
phase_start 6 "Display and Touch configuration"

# xrandr and xinput are called at runtime from Openbox autostart (Phase 9b).
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
prompt_if_unset IMAGE_TAG       "Enter IMAGE_TAG (sandbox/dev/pilot/prod)"
prompt_if_unset GHCR_USER       "Enter GHCR username"
prompt_if_unset GHCR_TOKEN      "Enter GHCR personal access token"
# Optional: second token for zero-downtime rotation (leave blank to skip)
if [[ -z "${GHCR_TOKEN_2:-}" ]]; then
    read -r -p "  Enter GHCR_TOKEN_2 for rotation (leave blank to skip): " GHCR_TOKEN_2 </dev/tty || true
fi
prompt_if_unset LID_HEATER_UPPER_BOUND "Enter lid heater upper bound voltage (e.g. 0.34)"
prompt_if_unset LID_HEATER_LOWER_BOUND "Enter lid heater lower bound voltage (e.g. 0.20)"
prompt_if_unset DRAWER_READ_STEPS      "Enter drawer read_steps for this device (e.g. 160)"
prompt_if_unset AQ_SYNC_ENDPOINT  "Enter AQ_SYNC_ENDPOINT (AWS ingest URL, leave blank to skip)"
# The Fleet API Key is retired (ADR-013): the Sentri authenticates Sync with its
# Device Certificate (mTLS), installed by scripts/enroll_device.py after deploy.

WATCHTOWER_TOKEN="${WATCHTOWER_TOKEN:-$(openssl rand -hex 32)}"

# acorn-ca renew front for automatic Device Certificate renewal (#279). Defaults
# to prod; override by exporting AQ_RENEW_ENDPOINT before running (e.g. dev CA).
AQ_RENEW_ENDPOINT="${AQ_RENEW_ENDPOINT:-https://renew.cloud.acorngenetics.com/renew}"

# Device ID is the Pi hardware serial (CONTEXT.md / ADR-014), NOT the hostname:
# the Device Certificate's CN must equal what the platform treats as the Device
# ID. Mirrors aq_lib/device_id.read_rpi_serial (the host has no app deps until
# images are pulled in Phase 9). Fail loud rather than enrol under a mutable id.
DEVICE_ID="$(awk -F': ' '/^Serial/ {print $2}' /proc/cpuinfo | tr -d '[:space:]')"
if [[ -z "${DEVICE_ID}" || "${DEVICE_ID}" =~ ^0+$ ]]; then
    echo "  ✗ No Raspberry Pi hardware serial in /proc/cpuinfo — cannot derive Device ID" >&2
    exit 1
fi

# device.env
cat > /opt/aquila/config/device.env <<EOF
DEVICE_ID=${DEVICE_ID}
DEVICE_HOSTNAME=${DEVICE_HOSTNAME}
IMAGE_TAG=${IMAGE_TAG}
GHCR_REPO=${GHCR_REPO}
RUN_MODE=prod
WATCHTOWER_HTTP_API_TOKEN=${WATCHTOWER_TOKEN}
GHCR_USERNAME=${GHCR_USER}
GHCR_TOKEN=${GHCR_TOKEN}
GHCR_TOKEN_2=${GHCR_TOKEN_2:-}
AQ_SRC_BASEDIR=/opt/aquila
AQ_SYNC_ENDPOINT=${AQ_SYNC_ENDPOINT}
AQ_RENEW_ENDPOINT=${AQ_RENEW_ENDPOINT}
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

# Resolve active token: validate primary, fall back to GHCR_TOKEN_2 if set
if [[ -n "${GHCR_TOKEN_2:-}" ]]; then
    if ! curl -fsSL -o /dev/null \
            -H "Authorization: token ${GHCR_TOKEN}" \
            "https://api.github.com/repos/${GHCR_REPO}" 2>/dev/null; then
        echo "  Primary GHCR_TOKEN failed — switching to GHCR_TOKEN_2"
        GHCR_TOKEN="${GHCR_TOKEN_2}"
    fi
fi

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

# Image delivery + updates are owned by AWS IoT Greengrass (Phase 9g), NOT
# Watchtower: the com.acorn.sentri component pulls the api/ui images from ECR by
# digest and runs the stack. So there is no manual compose pull here, no running
# image-digest bookkeeping, and no host-side updater script.
# device.env (written in Phase 8) remains the container env_file the component uses.

# Generate the device keypair + CSR on-device (CN = Device ID = Pi serial). The
# private key is written owner-only (0600) and never leaves the Pi; only the CSR
# is later submitted to acorn-ca /enroll (#240). Runs in the app image, which
# carries the crypto deps; the host does not. The container reads the same
# /proc/cpuinfo serial, so its CN matches DEVICE_ID written above.
#
# IDEMPOTENT: only generate on first provisioning. Re-running deployment2.sh must
# NOT regenerate the keypair — doing so overwrites device.key while the already
# enrolled device.crt stays put, orphaning the cert (cert/key mismatch → mTLS,
# Sync and renewal all break, requiring re-enrollment). If a key already exists,
# keep it (and its matching cert). To intentionally re-key, delete device.key +
# device.crt first, then re-run and re-enroll.
if [[ -s /opt/aquila/config/device.key ]]; then
    echo "  ℹ device.key already present — keeping existing keypair/CSR (not regenerating)."
else
    docker run --rm \
        -v /opt/aquila/config:/config \
        -v /proc/cpuinfo:/proc/cpuinfo:ro \
        "ghcr.io/${GHCR_REPO}-api:${IMAGE_TAG}" \
        python -m aq_lib.device_csr /config
fi

run_test "device CSR generated"            "test -s /opt/aquila/config/device.csr"
run_test "device key owner-only (0600)"    "test \"\$(stat -c '%a' /opt/aquila/config/device.key)\" = 600"
# If a cert is already installed (device previously enrolled), it MUST still match
# the key — catches the orphaned-cert failure a non-idempotent keygen would cause.
run_test "device cert/key match (if enrolled)" \
    "! test -s /opt/aquila/config/device.crt || diff -q <(openssl x509 -in /opt/aquila/config/device.crt -noout -pubkey) <(openssl pkey -in /opt/aquila/config/device.key -pubout)"

phase_pass "device identity ready (cert/key present); image delivery handed to Greengrass"

# ═══════════════════════════════════════════════════════════════════════════════
# Phase 9g — AWS IoT Greengrass Nucleus + Provisioning (replaces Watchtower OTA)
# ═══════════════════════════════════════════════════════════════════════════════
phase_start "9g" "AWS IoT Greengrass Nucleus + Provisioning"

AWS_REGION="${AWS_REGION:-us-east-2}"
GG_ROLE_ALIAS="${GG_ROLE_ALIAS:-acorn-sentri-tes}"   # Token Exchange role alias (ECR pulls)
GG_THING_GROUP="${GG_THING_GROUP:-holding}"          # JITP lands new Sentris here
GG_ROOT="/greengrass/v2"
# Account IoT endpoints (from `aws iot describe-endpoint`). The Pi has no AWS creds
# to look these up, so they are baked in here (env-overridable for other accounts).
GG_IOT_DATA_ENDPOINT="${GG_IOT_DATA_ENDPOINT:-a2xt0nylntrpe0-ats.iot.us-east-2.amazonaws.com}"
GG_IOT_CRED_ENDPOINT="${GG_IOT_CRED_ENDPOINT:-c1mnxdemzipv8n.credentials.iot.us-east-2.amazonaws.com}"

# The nucleus is a Java app; install a headless JRE + unzip for the installer.
DEBIAN_FRONTEND=noninteractive apt-get install -y default-jre-headless unzip

# The device already holds its acorn-ca cert/key (CSR + /enroll above). Greengrass
# authenticates to AWS IoT with that SAME cert — JITP auto-registers the Thing into
# the ${GG_THING_GROUP} ring on first connect. No AWS keys ever land on the device.
install -d -m 755 "${GG_ROOT}"
curl -fsSL https://d2s8p88vqu9w66.cloudfront.net/releases/greengrass-nucleus-latest.zip \
    -o /tmp/greengrass-nucleus.zip
unzip -q -o /tmp/greengrass-nucleus.zip -d /tmp/greengrass-installer
curl -fsSL https://www.amazontrust.com/repository/AmazonRootCA1.pem \
    -o /opt/aquila/config/AmazonRootCA1.pem

# Manual provisioning (--provision false): reuse the on-device cert, mint no keys.
cat > /opt/aquila/config/greengrass-config.yaml <<EOF
---
system:
  certificateFilePath: "/opt/aquila/config/device.crt"
  privateKeyPath: "/opt/aquila/config/device.key"
  rootCaPath: "/opt/aquila/config/AmazonRootCA1.pem"
  rootpath: "${GG_ROOT}"
  thingName: "${DEVICE_ID}"
services:
  aws.greengrass.Nucleus:
    configuration:
      awsRegion: "${AWS_REGION}"
      iotRoleAlias: "${GG_ROLE_ALIAS}"
      iotDataEndpoint: "${GG_IOT_DATA_ENDPOINT}"
      iotCredEndpoint: "${GG_IOT_CRED_ENDPOINT}"
EOF

java -Droot="${GG_ROOT}" -Dlog.store=FILE \
    -jar /tmp/greengrass-installer/lib/Greengrass.jar \
    --init-config /opt/aquila/config/greengrass-config.yaml \
    --component-default-user ggc_user:ggc_group \
    --setup-system-service true \
    --provision false

# The component runs as ggc_user, which must (a) reach the Docker socket to run
# the compose stack and (b) read the root-owned device.env the compose injects.
# Without these the component goes BROKEN ("permission denied ... docker.sock").
usermod -aG docker ggc_user
chgrp ggc_group /opt/aquila/config/device.env && chmod 640 /opt/aquila/config/device.env
chmod o+rx /opt/aquila /opt/aquila/config

run_test "greengrass root created"        "test -d ${GG_ROOT}"
run_test "greengrass service installed"   "test -f /etc/systemd/system/greengrass.service"
run_test "provisioned with device cert"   "grep -q 'device.crt' /opt/aquila/config/greengrass-config.yaml"
run_test "role alias configured"          "grep -q '${GG_ROLE_ALIAS}' /opt/aquila/config/greengrass-config.yaml"
run_test "ggc_user in docker group"       "id -nG ggc_user | grep -qw docker"
run_test "device.env readable by ggc_group" "test \"\$(stat -c '%G' /opt/aquila/config/device.env)\" = ggc_group"

phase_pass "Greengrass nucleus installed + provisioned; ggc_user granted Docker + config access (JITP -> ${GG_THING_GROUP})"

# ═══════════════════════════════════════════════════════════════════════════════
# Phase 9b — Chromium Kiosk (Openbox autostart)
# ═══════════════════════════════════════════════════════════════════════════════
phase_start "9b" "Chromium Kiosk (Openbox autostart)"

# Remove stale Wayland/desktop launcher paths so only one launch path exists
rm -f "${PI_HOME}/.config/autostart/chromium-kiosk.desktop"
rm -f "${PI_HOME}/.config/labwc/autostart"

# Install boot splash page
curl -fsSL \
    -H "Authorization: token ${GHCR_TOKEN}" \
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

# Clear the root-window cursor (covers terminal and behind Chromium).
# X is already started with `-nocursor` (see LightDM autologin.conf) so the pointer
# is never rendered. We deliberately do NOT run unclutter: it only hides on an idle
# timer and re-shows the cursor on pointer/touch events, causing a startup flash and
# a lingering cursor over dropdowns on every tap.
xsetroot -cursor_name none

# Allow display and compositor to settle before launching Chromium
sleep 3

# If kiosk_disabled flag exists, show desktop instead of kiosk.
# Flag is in /tmp/ so it is cleared on reboot (kiosk relaunches normally).
if [ ! -f /tmp/kiosk_disabled ]; then
  # GTK_THEME: Chromium's window background — the surface visible after the window
  # is mapped but before the page paints — comes from GTK, not from Chromium. It is
  # bright white by default, which makes every seam and flicker around it obvious
  # against the black either side. No Chromium flag reaches it:
  # --default-background-color and --cast-app-background-color both govern the PAGE
  # area and were verified in the running process on sn09 with no effect. A dark GTK
  # theme does reach it. See ~/.config/gtk-3.0/gtk.css above for the black override.
  env GTK_THEME=Adwaita:dark chromium \
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
    --disk-cache-size=0 \
    --start-maximized \
    --hide-scrollbars \
    >/dev/null 2>&1 &
fi
EOF

# Openbox decorates every window by default, and --kiosk does not survive a
# window being re-mapped: at startup Chromium's window appears briefly before it
# is fullscreened, and Openbox paints a title bar reading "Untitled — Chromium"
# across the top of the display (#428). The legacy WebKit kiosk guarded against
# this explicitly (server_web/kiosk.py, set_decorated(False)); the Chromium path
# relies on --kiosk alone and had no equivalent until now.
#
# The rule also forces the window fullscreen at map time. Without it Chromium's
# window is mapped small and then resized up to fullscreen, and you watch it grow
# — this is the "quadrant fill" reported on #428, which was mistaken for a slow
# repaint for some time. Frame-by-frame capture on sn09 showed a part-sized,
# decorated window rather than a partially painted one. Mapping it fullscreen
# removes the intermediate sizes entirely.
#
# A kiosk never wants decoration on anything, so the rule is unconditional.
# Openbox has no drop-in config directory — the only way to set a window rule is
# to own a copy of rc.xml, which is why this copies the distro file rather than
# patching it in place. That is the same "copied file drifts from upstream"
# pattern that caused #424 and #426, so it is deliberate and documented here.
#
# Verified on sn03 (title bar gone) and sn09 (window arrives fullscreen; the
# growing fill is gone). Kiosk otherwise unaffected on both.
OPENBOX_RC="${PI_HOME}/.config/openbox/rc.xml"
if [[ ! -f "${OPENBOX_RC}" && -f /etc/xdg/openbox/rc.xml ]]; then
    cp /etc/xdg/openbox/rc.xml "${OPENBOX_RC}"
fi
if [[ -f "${OPENBOX_RC}" ]] && ! grep -q 'aquila-kiosk-no-decor' "${OPENBOX_RC}"; then
    # Insert inside the existing <applications> block; a second top-level
    # <applications> element would be invalid and silently ignored.
    sed -i 's|</applications>|  <!-- aquila-kiosk-no-decor: see #428 -->\n  <application class="*">\n    <decor>no</decor>\n    <maximized>yes</maximized>\n    <fullscreen>yes</fullscreen>\n  </application>\n</applications>|' "${OPENBOX_RC}"
    # A malformed rc.xml leaves Openbox with no window manager, so validate
    # before letting it reach a reboot. Restore the stock file if we broke it.
    if ! python3 -c "import xml.etree.ElementTree as ET; ET.parse('${OPENBOX_RC}')" 2>/dev/null; then
        echo "  ✗ rc.xml failed XML validation — restoring stock file"
        cp /etc/xdg/openbox/rc.xml "${OPENBOX_RC}"
    fi
fi

chown -R pi:pi "${PI_HOME}/.config/openbox"

# Paint Chromium's window background black rather than the theme's dark grey, so
# the empty window is indistinguishable from the black on either side of it and
# the seams between frames have nothing to show. GTK_THEME=Adwaita:dark on the
# launch line (Phase 9b) selects a dark theme; this pins the exact colour.
mkdir -p "${PI_HOME}/.config/gtk-3.0"
cat > "${PI_HOME}/.config/gtk-3.0/gtk.css" <<'EOF'
/* Kiosk: the browser window background before any page paints (#428). */
window, .background, decoration {
    background-color: #000000;
}
EOF
chown -R pi:pi "${PI_HOME}/.config/gtk-3.0"

AUTOSTART="${PI_HOME}/.config/openbox/autostart"
run_test "openbox autostart exists"    "test -f ${AUTOSTART}"
run_test "openbox rc.xml exists"       "test -f ${OPENBOX_RC}"
run_test "window decorations disabled" "grep -q 'aquila-kiosk-no-decor' ${OPENBOX_RC}"
run_test "rc.xml is valid XML"         "python3 -c \"import xml.etree.ElementTree as ET; ET.parse('${OPENBOX_RC}')\""
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
# Phase 10 — App stack owned by Greengrass (no host compose service)
# ═══════════════════════════════════════════════════════════════════════════════
phase_start 10 "App Stack Ownership (Greengrass)"

# Under Greengrass the com.acorn.sentri component runs `docker compose up` from
# its recipe, so the host must NOT also run the stack — a second owner would race
# the component (double up/down, port clashes). Unconditionally remove any legacy
# host compose service left by deployment2 so greengrass.service is the sole owner.
# (disable is best-effort; the rm is what the check below verifies.)
systemctl disable --now aquila-stack.service 2>/dev/null || true
rm -f /etc/systemd/system/aquila-stack.service
systemctl daemon-reload

run_test "no host compose service" "! test -f /etc/systemd/system/aquila-stack.service"

phase_pass "app stack owned by the Greengrass component (com.acorn.sentri)"

# ═══════════════════════════════════════════════════════════════════════════════
# Phase 10b — Device Certificate Auto-Renewal Timer (#279)
# ═══════════════════════════════════════════════════════════════════════════════
phase_start "10b" "Device Certificate Auto-Renewal Timer"

# The renewer runs in the app image (which carries the crypto + requests deps the
# host lacks), mounting /opt/aquila/config so it reads the current cert/key +
# device.env and installs the rotated pair in place. It presents the current cert
# to acorn-ca /renew over mTLS — no operator, no AWS creds. renewal_due() no-ops
# until the cert is past ~2/3 of its life, so a daily run is cheap.
cat > /etc/systemd/system/aquila-cert-renew.service <<EOF
[Unit]
Description=Renew Sentri Device Certificate (acorn-ca /renew)
After=docker.service network-online.target
Wants=network-online.target
Requires=docker.service

[Service]
Type=oneshot
ExecStart=/usr/bin/docker run --rm \\
    -v /opt/aquila/config:/config \\
    ghcr.io/${GHCR_REPO}-api:${IMAGE_TAG} \\
    python -m aq_lib.renew /config
# Greengrass loads device.crt once at startup and holds a long-lived MQTT
# connection, so it won't pick up a renewed cert on its own (#363). The renewal
# runs in the container above and can't touch host systemd; on a rotation it drops
# /opt/aquila/config/.cert-rotated. Only when that marker is present do we restart
# Greengrass so it reconnects with the new cert, then clear it. A no-op renewal
# leaves no marker => Greengrass's healthy connection is never bounced. If the
# restart fails the marker stays and the next daily tick retries it.
ExecStartPost=/bin/sh -c 'test -f /opt/aquila/config/.cert-rotated && { systemctl restart greengrass && rm -f /opt/aquila/config/.cert-rotated; } || true'
EOF

# Daily, but with a large randomized delay so a batch of devices enrolled the same
# day does NOT stampede /renew at the same instant (and their renewed certs then
# expire together). Persistent=true catches up a missed run after downtime.
cat > /etc/systemd/system/aquila-cert-renew.timer <<'EOF'
[Unit]
Description=Daily Device Certificate renewal check

[Timer]
OnCalendar=daily
RandomizedDelaySec=6h
Persistent=true

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable --now aquila-cert-renew.timer

run_test "renew service file exists" "test -f /etc/systemd/system/aquila-cert-renew.service"
run_test "renew reconnects greengrass"  "grep -q 'restart greengrass' /etc/systemd/system/aquila-cert-renew.service"
run_test "renew timer file exists"   "test -f /etc/systemd/system/aquila-cert-renew.timer"
run_test "renew timer enabled"       "systemctl is-enabled aquila-cert-renew.timer | grep -q enabled"
run_test "renew timer active"        "systemctl is-active aquila-cert-renew.timer | grep -q active"
run_test "AQ_RENEW_ENDPOINT set"     "grep -q 'AQ_RENEW_ENDPOINT=' /opt/aquila/config/device.env"

phase_pass "aquila-cert-renew.timer registered and enabled"

# ═══════════════════════════════════════════════════════════════════════════════
# Phase 11 — Fleet Device Configuration (Start Stack)
# ═══════════════════════════════════════════════════════════════════════════════
phase_start 11 "Fleet Device Configuration"

# The app stack is started by the Greengrass component (com.acorn.sentri), not by
# a manual compose up. Once the holding-group deployment lands, the component pulls
# the ECR images and runs the stack; wait for the backend to answer /health.
echo "  Waiting for Greengrass to bring up the app stack..."
for i in $(seq 1 30); do
    if curl -sf http://localhost:8090/health >/dev/null 2>&1; then
        break
    fi
    sleep 2
done

# The Greengrass side is what provisioning owns. The app + Meerstetter first-time
# tuning happen once the com.acorn.sentri component runs, which requires a cloud
# deployment targeting this device's ring — that may land AFTER provisioning. So
# the app-up check below is informational (non-fatal); Meerstetter tuning is no
# longer a provisioning step (it needs the running app container the component owns).
run_test "DEVICE_ID set"             "grep -q 'DEVICE_ID=' /opt/aquila/config/device.env"
run_test "greengrass service active" "systemctl is-active greengrass | grep -q active"

app_up=0
for i in $(seq 1 30); do
    if curl -sf http://localhost:8090/health >/dev/null 2>&1; then app_up=1; break; fi
    sleep 2
done
if [[ "${app_up}" == "1" ]]; then
    echo "  ✓ app already up — a deployment has landed (/health OK on :8090)"
else
    echo "  ℹ app not up yet — it starts once a Greengrass deployment targets this device's ring."
fi

phase_pass "Greengrass active + provisioned; app starts when a ring deployment lands"

# ═══════════════════════════════════════════════════════════════════════════════
# Phase 11b — Kiosk Control Service
# ═══════════════════════════════════════════════════════════════════════════════
phase_start "11b" "Kiosk Control Service"

KIOSK_RAW="${RAW_REPO_URL}/scripts/kiosk-control"
curl -fsSL -H "Authorization: token ${GHCR_TOKEN}" "${KIOSK_RAW}/kiosk_control.py" -o /usr/local/bin/kiosk_control.py
chmod +x /usr/local/bin/kiosk_control.py
curl -fsSL -H "Authorization: token ${GHCR_TOKEN}" "${KIOSK_RAW}/kiosk-control.service" -o /etc/systemd/system/kiosk-control.service
systemctl daemon-reload
systemctl enable --now kiosk-control

# Install wifi-recovery startup service — cleans broken profiles and reconnects on boot
curl -fsSL -H "Authorization: token ${GHCR_TOKEN}" "${RAW_REPO_URL}/scripts/setup/wifi_recovery.sh" -o /opt/aquila/wifi_recovery.sh
chmod +x /opt/aquila/wifi_recovery.sh
cat > /etc/systemd/system/wifi-recovery.service <<'EOF'
[Unit]
Description=WiFi recovery — clean broken profiles and reconnect on boot
After=NetworkManager.service
Wants=NetworkManager.service

[Service]
Type=oneshot
ExecStart=/opt/aquila/wifi_recovery.sh
RemainAfterExit=yes
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable wifi-recovery.service

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
apt-get install -y --no-install-recommends plymouth plymouth-themes librsvg2-bin imagemagick 2>/dev/null

# Reinstall plymouth if initramfs hook is still missing (ensures early-boot coverage)
if [[ ! -f "${PLYMOUTH_INITRAMFS_HOOK}" ]]; then
    echo "  Plymouth initramfs hook missing — reinstalling plymouth..."
    apt-get install --reinstall -y plymouth 2>/dev/null
fi

# Download acornlogo SVG from repo if not already on device
if [[ ! -f "${ACORN_LOGO_SVG}" ]]; then
    curl -fsSL -H "Authorization: token ${GHCR_TOKEN}" \
        "${RAW_REPO_URL}/aquila_web/static/acornlogo.svg" \
        -o "${ACORN_LOGO_SVG}" 2>/dev/null || true
fi

# Create theme directory and convert SVG → PNG (256×256, white on transparent → white on black)
mkdir -p "${PLYMOUTH_THEME_DIR}"

if [[ -f "${ACORN_LOGO_SVG}" ]]; then
    # 192×192 px. Pre-rotate 270° (= 90° CCW) to compensate for display_hdmi_rotate=1.
    # Plymouth renders to the raw framebuffer; hardware rotation applies after,
    # so the image must be pre-rotated to appear upright on the physical screen.
    rsvg-convert -w 192 -h 192 --background-color white "${ACORN_LOGO_SVG}" \
        -o /tmp/acorn_logo_tmp.png 2>/dev/null
    if command -v convert &>/dev/null; then
        convert /tmp/acorn_logo_tmp.png -rotate 90 "${ACORN_LOGO_PNG}" 2>/dev/null \
            || cp /tmp/acorn_logo_tmp.png "${ACORN_LOGO_PNG}"
    elif python3 -c "from PIL import Image" &>/dev/null 2>&1; then
        python3 -c "
from PIL import Image
img = Image.open('/tmp/acorn_logo_tmp.png')
img.rotate(-90, expand=True).save('${ACORN_LOGO_PNG}')
" 2>/dev/null || cp /tmp/acorn_logo_tmp.png "${ACORN_LOGO_PNG}"
    else
        cp /tmp/acorn_logo_tmp.png "${ACORN_LOGO_PNG}"
        echo "  ⚠ No rotation tool found (install imagemagick) — logo may appear sideways"
    fi
else
    echo "  ✗ acornlogo.svg not found — skipping logo conversion"
fi

# Install theme files from repo
curl -fsSL -H "Authorization: token ${GHCR_TOKEN}" \
    "${RAW_REPO_URL}/scripts/setup/plymouth/acorn.plymouth" \
    -o "${PLYMOUTH_THEME_DIR}/acorn.plymouth" 2>/dev/null
curl -fsSL -H "Authorization: token ${GHCR_TOKEN}" \
    "${RAW_REPO_URL}/scripts/setup/plymouth/acorn.script" \
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
