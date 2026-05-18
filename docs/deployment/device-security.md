# Device Security Guide (Pi Kiosk)

## Priority 1 — Do These Now

### SSH Hardening
```bash
sudo nano /etc/ssh/sshd_config
# Set:
#   PasswordAuthentication no
#   PermitRootLogin no
#   Port 2222
sudo systemctl restart sshd
```

### Firewall
```bash
sudo apt install ufw -y
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow 2222        # SSH (non-default port)
sudo ufw allow 8080        # UI
sudo ufw deny 8090         # backend - internal only
sudo ufw deny 8081         # watchtower - internal only
sudo ufw enable
```

### Fix Secret File Permissions
```bash
sudo chmod 600 /opt/aquila/config/device.env
sudo chown root:root /opt/aquila/config/device.env
```

### Watchtower API Token
Add to `/opt/aquila/config/device.env`:
```
WATCHTOWER_HTTP_API_TOKEN=<long-random-string>
```

---

## Priority 2 — Physical Tamper Protection

### Read-Only Filesystem
Prevents SD card theft/modification:
```bash
sudo raspi-config
# Performance Options → Overlay File System → Enable
```
Disable overlay before making system changes, re-enable after.

### Disable USB Boot
Prevents booting a foreign OS from USB:
```bash
sudo raspi-config
# Advanced Options → Boot Order → SD Card only
```

### Lock the Kiosk UI
```bash
chromium-browser --kiosk --noerrdialogs --disable-infobars \
  --no-first-run --disable-pinch \
  --overscroll-history-navigation=0 \
  http://localhost:8080
```

### Auto-Lock on Idle
```bash
sudo apt install xscreensaver -y
# Configure to blank + lock after N minutes
```

---

## Priority 3 — Remote Attack Defense

### Fail2ban (auto-ban brute force)
```bash
sudo apt install fail2ban -y
sudo systemctl enable fail2ban --now
```

### Unattended Security Upgrades
```bash
sudo apt install unattended-upgrades -y
sudo dpkg-reconfigure --priority=low unattended-upgrades
```

### Audit Open Ports
```bash
sudo ss -tlnp
```

---

## Priority 4 — Sensitive Data Encryption

### Encrypt the Data Partition (LUKS)
Protects results/profiles if SD card is stolen:
```bash
sudo apt install cryptsetup -y
# Set up LUKS on /opt/aquila partition
# Requires passphrase or key file on boot
```

---

## Threat Summary

| Threat | Defense |
|--------|---------|
| Remote SSH brute force | Key-only auth + fail2ban + non-default port |
| Open ports exploited | ufw firewall, block 8090/8081 |
| Watchtower API abuse | API token + firewall |
| Physical SD card theft | Read-only overlay + LUKS encryption |
| Someone at the screen | Kiosk mode + disable keyboard shortcuts |
| Booting from USB | Disable USB boot in raspi-config |
| Secrets in env files | chmod 600 + root ownership |
