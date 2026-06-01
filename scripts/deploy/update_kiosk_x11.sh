#!/usr/bin/env bash
# update_kiosk_x11.sh — Migrate existing Aquila devices from Wayland/labwc to X11/Openbox
#
# Run on device:
#   sudo bash update_kiosk_x11.sh
#
# What this does:
#   1. Installs required X11/Openbox packages
#   2. Switches LightDM autologin session from rpd-labwc to openbox
#   3. Writes the correct Openbox autostart (xrandr + touch matrix + Chromium)
#   4. Removes stale Wayland/kanshi/labwc launcher files
#   5. Reboots (or prompts to reboot)
set -euo pipefail

[[ "${EUID}" -ne 0 ]] && { echo "Run as root: sudo bash update_kiosk_x11.sh"; exit 1; }

PI_HOME="/home/pi"

# ── Helpers ───────────────────────────────────────────────────────────────────

step() { echo ""; echo "▶ $1"; }
pass() { echo "  ✓ $1"; }
fail() { echo "  ✗ FAILED — $1"; exit 1; }

run_test() {
    local desc=$1 cmd=$2
    if eval "${cmd}" >/dev/null 2>&1; then
        pass "${desc}"
    else
        fail "${desc}"
    fi
}

# ═══════════════════════════════════════════════════════════════════════════════
# Step 1 — Install X11/Openbox packages
# ═══════════════════════════════════════════════════════════════════════════════
step "Installing X11/Openbox packages"

apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y \
    openbox \
    xserver-xorg \
    x11-xserver-utils \
    xinput \
    unclutter

run_test "openbox installed"  "which openbox"
run_test "xrandr installed"   "which xrandr"
run_test "xinput installed"   "which xinput"
run_test "unclutter installed" "which unclutter"

pass "X11/Openbox packages installed"

# ═══════════════════════════════════════════════════════════════════════════════
# Step 2 — Switch LightDM autologin to X11/Openbox
# ═══════════════════════════════════════════════════════════════════════════════
step "Switching LightDM autologin to X11/Openbox"

mkdir -p /etc/lightdm/lightdm.conf.d
cat > /etc/lightdm/lightdm.conf.d/autologin.conf <<'EOF'
[Seat:*]
autologin-user=pi
autologin-session=openbox
EOF

run_test "autologin.conf written"     "test -f /etc/lightdm/lightdm.conf.d/autologin.conf"
run_test "autologin-session=openbox"  "grep -q 'autologin-session=openbox' /etc/lightdm/lightdm.conf.d/autologin.conf"

pass "LightDM configured for X11/Openbox autologin"

# ═══════════════════════════════════════════════════════════════════════════════
# Step 3 — Remove stale Wayland/kanshi/labwc launcher files
# ═══════════════════════════════════════════════════════════════════════════════
step "Removing stale Wayland launcher files"

# Old .desktop kiosk launcher (Wayland/labwc path)
rm -f "${PI_HOME}/.config/autostart/chromium-kiosk.desktop"
pass "removed chromium-kiosk.desktop"

# labwc autostart that launched kanshi
rm -f "${PI_HOME}/.config/labwc/autostart"
pass "removed labwc autostart"

# kanshi config (no longer needed — xrandr handles rotation)
rm -f "${PI_HOME}/.config/kanshi/config"
pass "removed kanshi config"

pass "Stale Wayland files removed"

# ═══════════════════════════════════════════════════════════════════════════════
# Step 4 — Write Openbox autostart
# ═══════════════════════════════════════════════════════════════════════════════
step "Writing Openbox autostart"

mkdir -p "${PI_HOME}/.config/openbox"

cat > "${PI_HOME}/.config/openbox/autostart" <<'EOF'
# Disable screen blanking and power management
xset s off
xset s noblank
xset -dpms

# Rotate display and match touch matrix (HDMI-2, rotate right)
xrandr --output HDMI-2 --mode 1024x768 --rate 60 --rotate right

xinput set-prop "Focaltech Systems FT5926 MultiTouch" \
  "Coordinate Transformation Matrix" \
  0 1 0 -1 0 1 0 0 1

# Hide cursor after 0.5s idle
unclutter -idle 0.5 &

# Allow display and compositor to settle before launching Chromium
sleep 3

chromium \
  --kiosk http://localhost:8090 \
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
  --start-maximized \
  &
EOF

chown -R pi:pi "${PI_HOME}/.config/openbox"

run_test "autostart file exists"        "test -f ${PI_HOME}/.config/openbox/autostart"
run_test "correct URL (8090)"           "grep -q 'localhost:8090' ${PI_HOME}/.config/openbox/autostart"
run_test "X11 platform flag"            "grep -q 'ozone-platform=x11' ${PI_HOME}/.config/openbox/autostart"
run_test "touch-events flag"            "grep -q 'touch-events=enabled' ${PI_HOME}/.config/openbox/autostart"
run_test "xrandr present"               "grep -q 'xrandr' ${PI_HOME}/.config/openbox/autostart"
run_test "touch matrix present"         "grep -q 'Coordinate Transformation Matrix' ${PI_HOME}/.config/openbox/autostart"
run_test "no stale .desktop launcher"   "test ! -f ${PI_HOME}/.config/autostart/chromium-kiosk.desktop"
run_test "correct file ownership"       "stat -c '%U' ${PI_HOME}/.config/openbox/autostart | grep -q pi"

pass "Openbox autostart written"

# ═══════════════════════════════════════════════════════════════════════════════
# Done
# ═══════════════════════════════════════════════════════════════════════════════
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " All steps complete."
echo " Boot flow: LightDM → X11 → Openbox → autostart"
echo "            → xrandr HDMI-2 right + touch matrix"
echo "            → Chromium kiosk on localhost:8090"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

read -rp "Reboot now? [Y/n]: " REBOOT_NOW </dev/tty
REBOOT_NOW="${REBOOT_NOW:-Y}"
if [[ "${REBOOT_NOW}" =~ ^[Yy]$ ]]; then
    echo "Rebooting..."
    reboot
else
    echo "Reboot skipped. Run 'sudo reboot' when ready."
fi
