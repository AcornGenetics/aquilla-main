#!/usr/bin/env bash
# wifi_recovery.sh — runs on boot via systemd, cleans broken WiFi profiles and reconnects.
# Installed by deployment2.sh to /opt/aquila/wifi_recovery.sh

set -uo pipefail

log() { echo "[wifi-recovery] $*" | systemd-cat -t wifi-recovery 2>/dev/null || echo "[wifi-recovery] $*"; }

check_internet() {
    curl -s --max-time 5 --head https://dns.google > /dev/null 2>&1
}

delete_broken_wifi_profiles() {
    local names
    names=$(nmcli -t -f NAME,TYPE connection show 2>/dev/null \
        | awk -F: '$2 == "802-11-wireless" {print $1}')
    while IFS= read -r name; do
        [[ -z "$name" ]] && continue
        # A saved wifi profile with no key-mgmt but a security section is broken
        local security_section
        security_section=$(nmcli -g 802-11-wireless-security connection show "$name" 2>/dev/null || true)
        local key_mgmt
        key_mgmt=$(nmcli -g 802-11-wireless-security.key-mgmt connection show "$name" 2>/dev/null || true)
        if [[ -n "$security_section" && -z "$key_mgmt" ]]; then
            log "Deleting broken profile (missing key-mgmt): $name"
            nmcli connection delete "$name" 2>/dev/null || true
        fi
    done <<< "$names"
}

reconnect() {
    # Rescan for available networks
    nmcli device wifi rescan 2>/dev/null || true
    sleep 4

    local available
    available=$(nmcli -t -f SSID device wifi list 2>/dev/null | sort -u)

    # Try each saved wifi profile that is currently in range
    local saved
    saved=$(nmcli -t -f NAME,TYPE connection show 2>/dev/null \
        | awk -F: '$2 == "802-11-wireless" {print $1}')

    while IFS= read -r name; do
        [[ -z "$name" ]] && continue
        local ssid
        ssid=$(nmcli -g 802-11-wireless.ssid connection show "$name" 2>/dev/null || echo "$name")
        if echo "$available" | grep -qF "$ssid"; then
            log "Trying: $name"
            nmcli connection up "$name" 2>/dev/null || true
            sleep 3
            if check_internet; then
                log "Connected via: $name"
                return 0
            fi
        fi
    done <<< "$saved"

    log "No working network found"
    return 1
}

# Give NetworkManager time to settle after boot
sleep 10

if check_internet; then
    log "Internet available — nothing to do"
    exit 0
fi

log "No internet on boot — cleaning broken profiles and reconnecting"
delete_broken_wifi_profiles
reconnect || true
