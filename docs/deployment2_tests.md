# Deployment2 Tests
## Per-Phase Verification Tests

Each test runs automatically at the end of its corresponding phase in `deployment2.sh`.
Pass = `✓`, Fail = `✗` with reason. A failed test stops the script.

---

## Phase 1 — OS Prerequisites and Host Packages

| Test | Command | Pass Condition |
|---|---|---|
| curl installed | `which curl` | exits 0 |
| chromium installed | `which chromium` | exits 0 |
| kanshi installed | `which kanshi` | exits 0 |
| python3 installed | `which python3` | exits 0 |
| python3-gi installed | `python3 -c "import gi"` | exits 0 |
| WebKit2 available | `dpkg -l libwebkit2gtk-4.1-0 \| grep -q '^ii'` | exits 0 |

```
✓ Phase 1 complete — all host packages installed
✗ Phase 1 FAILED — chromium not found after install. Check apt sources.
```

---

## Phase 2 — Hardware Interfaces (I2C + SPI)

> Note: These checks run after the reboot that follows raspi-config.
> The script verifies the interfaces are present on first post-reboot run.

| Test | Command | Pass Condition |
|---|---|---|
| I2C enabled in boot config | `grep -q "dtparam=i2c_arm=on" /boot/firmware/config.txt` | exits 0 |
| SPI enabled in boot config | `grep -q "dtparam=spi=on" /boot/firmware/config.txt` | exits 0 |
| /dev/i2c-1 exists | `test -e /dev/i2c-1` | exits 0 |
| /dev/spidev0.0 exists | `test -e /dev/spidev0.0` | exits 0 |

```
✓ Phase 2 complete — I2C and SPI enabled, /dev/i2c-1 and /dev/spidev0.0 present
✗ Phase 2 FAILED — /dev/i2c-1 not found. Reboot may be required.
```

---

## Phase 3 — Docker

| Test | Command | Pass Condition |
|---|---|---|
| Docker installed | `docker --version` | exits 0 |
| Docker Compose installed | `docker compose version` | exits 0 |
| Docker service enabled | `systemctl is-enabled docker` | prints `enabled` |
| Docker service running | `systemctl is-active docker` | prints `active` |
| pi user in docker group | `groups pi \| grep -q docker` | exits 0 |

```
✓ Phase 3 complete — Docker installed and running, pi in docker group
✗ Phase 3 FAILED — Docker service not active. Check: sudo systemctl status docker
```

---

## Phase 4 — Autologin (Wayland)

| Test | Command | Pass Condition |
|---|---|---|
| autologin.conf exists | `test -f /etc/lightdm/lightdm.conf.d/autologin.conf` | exits 0 |
| autologin-user=pi | `grep -q "autologin-user=pi" /etc/lightdm/lightdm.conf.d/autologin.conf` | exits 0 |
| autologin-session=rpd-labwc | `grep -q "autologin-session=rpd-labwc" /etc/lightdm/lightdm.conf.d/autologin.conf` | exits 0 |

```
✓ Phase 4 complete — LightDM configured for rpd-labwc autologin
✗ Phase 4 FAILED — autologin.conf missing or has wrong session value
```

---

## Phase 5 — Chromium Kiosk

| Test | Command | Pass Condition |
|---|---|---|
| .desktop file exists | `test -f ~/.config/autostart/chromium-kiosk.desktop` | exits 0 |
| Wayland flag present | `grep -q "\-\-ozone-platform=wayland" ~/.config/autostart/chromium-kiosk.desktop` | exits 0 |
| password-store flag present | `grep -q "\-\-password-store=basic" ~/.config/autostart/chromium-kiosk.desktop` | exits 0 |
| URL not quoted | `grep -qv "\"http" ~/.config/autostart/chromium-kiosk.desktop` | exits 0 |
| Correct URL | `grep -q "http://localhost:8090" ~/.config/autostart/chromium-kiosk.desktop` | exits 0 |

```
✓ Phase 5 complete — Chromium kiosk .desktop file configured correctly
✗ Phase 5 FAILED — --ozone-platform=wayland flag missing from .desktop file
```

---

## Phase 6 — Display Rotation (kanshi)

| Test | Command | Pass Condition |
|---|---|---|
| kanshi config exists | `test -f ~/.config/kanshi/config` | exits 0 |
| kanshi config is multiline | `wc -l < ~/.config/kanshi/config \| awk '$1>1'` | returns value > 1 |
| HDMI-A-2 present | `grep -q "HDMI-A-2" ~/.config/kanshi/config` | exits 0 |
| transform 270 set | `grep -q "transform 270" ~/.config/kanshi/config` | exits 0 |
| labwc autostart exists | `test -f ~/.config/labwc/autostart` | exits 0 |
| kanshi in labwc autostart | `grep -q "kanshi" ~/.config/labwc/autostart` | exits 0 |
| correct file ownership | `stat -c '%U' ~/.config/kanshi/config \| grep -q pi` | exits 0 |

```
✓ Phase 6 complete — kanshi config valid, labwc autostart configured
✗ Phase 6 FAILED — kanshi config is single-line (must be multiline with 4-space indent)
```

---

## Phase 7 — Persistent Directory Structure

| Test | Command | Pass Condition |
|---|---|---|
| /opt/aquila/config | `test -d /opt/aquila/config` | exits 0 |
| /opt/aquila/profiles | `test -d /opt/aquila/profiles` | exits 0 |
| /opt/aquila/results | `test -d /opt/aquila/results` | exits 0 |
| /opt/aquila/logs/results | `test -d /opt/aquila/logs/results` | exits 0 |
| /opt/aquila/logs/plots | `test -d /opt/aquila/logs/plots` | exits 0 |
| /opt/aquila/logs/pcr | `test -d /opt/aquila/logs/pcr` | exits 0 |
| /opt/aquila/logs/optics | `test -d /opt/aquila/logs/optics` | exits 0 |
| /opt/aquila/logs/lid_heater | `test -d /opt/aquila/logs/lid_heater` | exits 0 |
| /opt/fleet | `test -d /opt/fleet` | exits 0 |

```
✓ Phase 7 complete — all persistent directories created
✗ Phase 7 FAILED — /opt/aquila/logs/optics missing
```

---

## Phase 8 — Device Identity Files

| Test | Command | Pass Condition |
|---|---|---|
| device.env exists | `test -f /opt/aquila/config/device.env` | exits 0 |
| DEVICE_HOSTNAME set | `grep -q "DEVICE_HOSTNAME=" /opt/aquila/config/device.env` | exits 0 |
| DEVICE_ID set | `grep -q "DEVICE_ID=" /opt/aquila/config/device.env` | exits 0 |
| IMAGE_TAG set | `grep -q "IMAGE_TAG=" /opt/aquila/config/device.env` | exits 0 |
| WATCHTOWER_TOKEN set | `grep -q "WATCHTOWER_HTTP_API_TOKEN=" /opt/aquila/config/device.env` | exits 0 |
| /opt/fleet/.env exists | `test -f /opt/fleet/.env` | exits 0 |

```
✓ Phase 8 complete — device.env and fleet .env written
✗ Phase 8 FAILED — WATCHTOWER_HTTP_API_TOKEN not set in device.env
```

---

## Phase 9 — Docker Images

| Test | Command | Pass Condition |
|---|---|---|
| GHCR login succeeded | `grep -q "ghcr.io" /root/.docker/config.json` | exits 0 |
| docker-compose.yml downloaded | `test -f /opt/fleet/docker-compose.yml` | exits 0 |
| compose file non-empty | `test -s /opt/fleet/docker-compose.yml` | exits 0 |
| backend image pulled | `docker images \| grep -q "aquilla-main-api"` | exits 0 |
| ui image pulled | `docker images \| grep -q "aquilla-main-ui"` | exits 0 |
| update.sh exists and executable | `test -x /opt/fleet/update.sh` | exits 0 |

```
✓ Phase 9 complete — docker-compose.yml downloaded, all images pulled
✗ Phase 9 FAILED — aquilla-main-api image not found. Check GHCR login and IMAGE_TAG.
```

---

## Phase 10 — systemd Service

| Test | Command | Pass Condition |
|---|---|---|
| service file exists | `test -f /etc/systemd/system/aquila-stack.service` | exits 0 |
| service enabled | `systemctl is-enabled aquila-stack.service` | prints `enabled` |

```
✓ Phase 10 complete — aquila-stack.service registered and enabled
✗ Phase 10 FAILED — aquila-stack.service not enabled. Run: systemctl daemon-reload && systemctl enable aquila-stack.service
```

---

## Phase 11 — Fleet Device Configuration

| Test | Command | Pass Condition |
|---|---|---|
| DEVICE_ID set in device.env | `grep -q "DEVICE_ID=" /opt/aquila/config/device.env` | exits 0 |
| IMAGE_TAG is valid ring | `grep -E "IMAGE_TAG=(dev\|pilot\|prod)" /opt/aquila/config/device.env` | exits 0 |
| aquila-backend running | `docker ps --filter name=aquila-backend --format '{{.Status}}' \| grep -q Up` | exits 0 |
| aquila-app running | `docker ps --filter name=aquila-app --format '{{.Status}}' \| grep -q Up` | exits 0 |
| aquila-ui running | `docker ps --filter name=aquila-ui --format '{{.Status}}' \| grep -q Up` | exits 0 |
| backend reachable | `curl -sf http://localhost:8090/health` | exits 0 |
| watchtower running | `docker ps --filter name=aquila-watchtower --format '{{.Status}}' \| grep -q Up` | exits 0 |
| watchtower webhook responds | see below | returns HTTP 200 |

**Watchtower webhook smoke test:**
```bash
WATCHTOWER_TOKEN=$(grep WATCHTOWER_HTTP_API_TOKEN /opt/aquila/config/device.env | cut -d= -f2)
curl -sf -o /dev/null -w "%{http_code}" -X POST http://localhost:8081/v1/update \
  -H "Authorization: Bearer ${WATCHTOWER_TOKEN}" | grep -q "200"
```
Confirms: webhook port is open, token is correctly wired, and Watchtower accepts the trigger.
> Note: a 200 response means Watchtower accepted the request and will attempt a pull.
> Check `docker logs aquila-watchtower` afterwards to confirm GHCR auth succeeded.

```
✓ Phase 11 complete — all 4 containers running, backend reachable on :8090, watchtower webhook responding
✗ Phase 11 FAILED — aquila-app not running. Check: docker logs aquila-app
```

---

## Phase 12 — Tailscale

| Test | Command | Pass Condition |
|---|---|---|
| tailscale installed | `which tailscale` | exits 0 |
| tailscale running | `systemctl is-active tailscaled` | prints `active` |
| device authenticated | `tailscale status \| grep -q "${DEVICE_HOSTNAME}"` | exits 0 |
| SSH enabled | `tailscale status --json \| python3 -c "import sys,json; d=json.load(sys.stdin); assert d.get('TailscaleIPs')"` | exits 0 |

```
✓ Phase 12 complete — Tailscale active, device authenticated as <DEVICE_HOSTNAME>
✗ Phase 12 FAILED — Tailscale not authenticated. Run: sudo tailscale up --ssh
```

---

## Phase 13 — Grafana Alloy

| Test | Command | Pass Condition |
|---|---|---|
| alloy installed | `which alloy` | exits 0 |
| alloy service active | `systemctl is-active alloy.service` | prints `active` |
| alloy service enabled | `systemctl is-enabled alloy.service` | prints `enabled` |

```
✓ Phase 13 complete — Grafana Alloy installed and running
✗ Phase 13 FAILED — alloy.service not active. Check: sudo systemctl status alloy.service
```

---

## Phase 14 — Quiet Boot

| Test | Command | Pass Condition |
|---|---|---|
| tty3 in cmdline | `grep -q "console=tty3" /boot/cmdline.txt` | exits 0 |
| tty1 not in cmdline | `! grep -q "console=tty1" /boot/cmdline.txt` | exits 0 |

```
✓ Phase 14 complete — quiet boot configured (tty3)
✗ Phase 14 FAILED — console=tty1 still present in /boot/cmdline.txt
```

---

## Post-Reboot Smoke Tests

Run these manually after first reboot to verify the full stack is up:

| Test | Command | Pass Condition |
|---|---|---|
| All containers running | `docker ps --format '{{.Names}} {{.Status}}' \| grep aquila` | shows 4 containers Up |
| Backend API healthy | `curl -sf http://localhost:8090/health` | returns 200 |
| Kiosk process running | `ps aux \| grep chromium \| grep -v grep` | shows chromium process |
| kanshi running | `ps aux \| grep kanshi \| grep -v grep` | shows kanshi process |
| I2C accessible | `test -e /dev/i2c-1` | exits 0 |
| SPI accessible | `test -e /dev/spidev0.0` | exits 0 |
| Drawer opened on boot | Check physically | drawer is open |
| Display rotated correctly | Check physically | portrait orientation |
