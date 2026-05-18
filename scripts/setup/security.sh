#!/usr/bin/env bash
# security.sh — Aquila device security hardening
# Run after deployment2.sh once testing is complete.
# Usage: sudo bash /opt/aquila/security.sh
set -euo pipefail

[[ "${EUID}" -ne 0 ]] && { echo "Run as root: sudo bash security.sh"; exit 1; }

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

run_test() {
    local desc=$1 cmd=$2
    if eval "${cmd}" >/dev/null 2>&1; then
        echo "  ✓ ${desc}"
    else
        phase_fail "${desc}"
    fi
}

# ═══════════════════════════════════════════════════════════════════════════════
# Phase 1 — Security Hardening
# ═══════════════════════════════════════════════════════════════════════════════
phase_start 1 "Security Hardening"

# Lock config directory — only root can read or list it
chmod 700 /opt/aquila/config
chmod 600 /opt/aquila/config/device.env
find /opt/aquila/config -name "*.json" -exec chmod 600 {} \;

# Restrict pi's sudo to safe operational commands only.
# Access to root (and config) is via Tailscale SSH authenticated
# through the owner's Tailscale account — not local sudo.
deluser pi sudo 2>/dev/null || true
cat > /etc/sudoers.d/pi-restricted <<'EOF'
pi ALL=(ALL) NOPASSWD: /usr/bin/docker compose *
pi ALL=(ALL) NOPASSWD: /bin/systemctl restart aquila-stack
pi ALL=(ALL) NOPASSWD: /bin/systemctl status aquila-stack
pi ALL=(ALL) NOPASSWD: /bin/systemctl restart kiosk-control
pi ALL=(ALL) NOPASSWD: /bin/systemctl status kiosk-control
EOF
chmod 440 /etc/sudoers.d/pi-restricted

run_test "config dir root-only"         "stat -c '%a' /opt/aquila/config | grep -q 700"
run_test "device.env root-only"         "stat -c '%a' /opt/aquila/config/device.env | grep -q 600"
run_test "pi not in sudo group"         "! groups pi | grep -qw sudo"
run_test "pi-restricted sudoers exists" "test -f /etc/sudoers.d/pi-restricted"
run_test "sudoers file valid"           "visudo -cf /etc/sudoers.d/pi-restricted"

phase_pass "config locked to root, pi sudo restricted to operational commands"

echo ""
echo "=================================================="
echo " Security hardening complete."
echo " Config directory is now root-only."
echo " pi user sudo access is restricted."
echo "=================================================="
