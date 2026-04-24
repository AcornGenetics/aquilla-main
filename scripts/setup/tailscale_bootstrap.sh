#!/usr/bin/env bash
# tailscale_bootstrap.sh — Install and connect Tailscale on a new Aquila device.
#
# Run this first on a fresh Pi so you can SSH in from your computer
# and complete the rest of deployment2.sh remotely.
#
# Usage:
#   sudo bash tailscale_bootstrap.sh
#
# Or pre-set values to skip prompts:
#   DEVICE_HOSTNAME=sn05 TAILSCALE_KEY=tskey-auth-... sudo bash tailscale_bootstrap.sh
#
set -euo pipefail

[[ "${EUID}" -ne 0 ]] && { echo "Run as root: sudo bash tailscale_bootstrap.sh"; exit 1; }

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " Aquila — Tailscale Bootstrap"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# ── Device hostname ───────────────────────────────────────────────────────────
if [[ -z "${DEVICE_HOSTNAME:-}" ]]; then
    read -rp "  Device hostname (e.g. sn05): " DEVICE_HOSTNAME
fi
echo "  → Hostname: ${DEVICE_HOSTNAME}"

# Set system hostname now so Tailscale registers the right name
hostnamectl set-hostname "${DEVICE_HOSTNAME}"

# ── Install Tailscale ─────────────────────────────────────────────────────────
if command -v tailscale >/dev/null 2>&1; then
    echo "  ✓ Tailscale already installed: $(tailscale version | head -1)"
else
    echo "  → Installing Tailscale..."
    curl -fsSL https://tailscale.com/install.sh | sh
    echo "  ✓ Tailscale installed"
fi

# Ensure tailscaled is enabled and running
systemctl enable --now tailscaled
echo "  ✓ tailscaled service enabled"

# ── Authenticate ──────────────────────────────────────────────────────────────
if [[ -z "${TAILSCALE_KEY:-}" ]]; then
    echo ""
    echo "  Enter a Tailscale auth key, or press Enter to authenticate interactively."
    echo "  (Get a key from https://login.tailscale.com/admin/settings/keys)"
    read -rp "  Tailscale auth key [Enter for browser auth]: " TAILSCALE_KEY
fi

if [[ -n "${TAILSCALE_KEY:-}" ]]; then
    tailscale up --ssh --authkey "${TAILSCALE_KEY}" --hostname "${DEVICE_HOSTNAME}"
else
    tailscale up --ssh --hostname "${DEVICE_HOSTNAME}"
    echo ""
    echo "  → Complete Tailscale authentication in your browser, then press Enter to continue."
    read -r
fi

# ── Verify ────────────────────────────────────────────────────────────────────
echo ""
echo "  Verifying..."

if ! systemctl is-active tailscaled | grep -q active; then
    echo "  ✗ tailscaled is not running"
    exit 1
fi
echo "  ✓ tailscaled active"

if ! tailscale status | grep -q "${DEVICE_HOSTNAME}"; then
    echo "  ✗ Device not found in tailscale status — authentication may have failed"
    exit 1
fi
echo "  ✓ Device authenticated as ${DEVICE_HOSTNAME}"

TAILSCALE_IP=$(tailscale ip -4 2>/dev/null || true)
if [[ -z "${TAILSCALE_IP}" ]]; then
    echo "  ✗ No Tailscale IP assigned yet — check authentication"
    exit 1
fi
echo "  ✓ Tailscale IP: ${TAILSCALE_IP}"

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " Tailscale is up. From your computer, SSH in with:"
echo ""
echo "   ssh pi@${DEVICE_HOSTNAME}"
echo "   # or"
echo "   ssh pi@${TAILSCALE_IP}"
echo ""
echo " Then run deployment2.sh to complete device setup."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
