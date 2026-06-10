# Spec: Suppress Pi Boot Screen — Show Acorn Branding Only

## Problem

On device power-on, users see Raspberry Pi boot visuals before the Acorn splash page
appears. This includes:

1. **The Pi rainbow/firmware splash** — `disable_splash=1` is already set in `config.txt`
   but this only suppresses the *firmware* rainbow square. With the `vc4-kms-v3d` (KMS)
   driver active, the GPU takes over the display after firmware and a colored framebuffer
   state can still flash briefly.
2. **Kernel boot messages** — printk output scrolls on the console even though
   `console=tty3` is set. `console=tty3` redirects the *login console* but does not
   suppress kernel messages on the framebuffer unless `quiet` is also present in
   `cmdline.txt`.
3. **The Tux penguin logo** — appears during kernel load unless `logo.nologo` is set.
4. **A blank or colored framebuffer gap** — between kernel finishing and X11/Openbox
   starting, the display shows whatever color the KMS driver leaves (usually purple/
   magenta on Pi 5 with vc4-kms-v3d).

The existing Chromium splash page (`splash.html`) and its health-poll transition to the
app are working correctly and must be preserved unchanged.

## Root Cause: Why `disable_splash=1` Does Not Work

`disable_splash=1` is a firmware flag. It suppresses the firmware-level rainbow image
that appears in the first ~1 second. However:

- The KMS driver (`vc4-kms-v3d`) reinitialises the display after firmware, which can
  briefly show a colored framebuffer.
- Kernel printk messages are written directly to the framebuffer console and are not
  controlled by firmware flags.
- The Tux logo is rendered by the kernel, not firmware.

All three require kernel cmdline changes, not config.txt changes.

## Proposed Changes

### 1. `cmdline.txt` — suppress kernel visual output

Add the following parameters to `/boot/firmware/cmdline.txt`:

```
quiet loglevel=3 logo.nologo vt.global_cursor_default=0
```

| Parameter | Effect |
|-----------|--------|
| `quiet` | Suppresses most kernel printk messages on the framebuffer |
| `loglevel=3` | Only shows errors (not info/debug) — belt-and-suspenders with `quiet` |
| `logo.nologo` | Suppresses the Tux penguin logo |
| `vt.global_cursor_default=0` | Hides the blinking text cursor on the console |

`deployment2.sh` already sets `console=tty3`. The new parameters should be appended
on the same line. The final cmdline should look like:

```
console=serial0,115200 console=tty3 quiet loglevel=3 logo.nologo vt.global_cursor_default=0 ...
```

### 2. `config.txt` — fill the KMS framebuffer gap with black

Add the following to `config.txt` to set the initial framebuffer color to black before
the KMS driver hands off to X11:

```ini
# Set framebuffer background to black before X11 starts (suppresses colored gap)
framebuffer_ignore_alpha=1
```

Additionally, confirm `disable_splash=1` remains (it suppresses the firmware square even
if the KMS gap still needs the framebuffer fix above).

### 3. Systemd service — paint framebuffer black before X11 (belt-and-suspenders)

For the gap between kernel init and X11 starting, add a one-shot systemd service that
runs before `lightdm` or the display manager:

**`/etc/systemd/system/aquila-black-fb.service`**
```ini
[Unit]
Description=Set framebuffer to black before display manager starts
Before=lightdm.service display-manager.service
After=local-fs.target

[Service]
Type=oneshot
ExecStart=/bin/sh -c 'dd if=/dev/zero bs=1M count=8 > /dev/fb0 2>/dev/null || true'
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
```

`dd if=/dev/zero` writes black pixels to the framebuffer. The `|| true` ensures it
doesn't fail if `/dev/fb0` is not available (e.g. headless). `count=8` covers
1920×1080×4 bytes (~8 MB).

### 4. `deployment2.sh` — automate all of the above

Add a new phase to `deployment2.sh` after the existing quiet-boot section (line ~834):

```bash
# ── Suppress Pi boot visuals ─────────────────────────────────────────────────
echo "Phase N: Suppressing Pi boot visuals..."

CMDLINE_FILE="/boot/firmware/cmdline.txt"

# Add quiet + kernel flags if not already present
for flag in "quiet" "loglevel=3" "logo.nologo" "vt.global_cursor_default=0"; do
    if ! grep -q "${flag}" "${CMDLINE_FILE}"; then
        sed -i "s/$/ ${flag}/" "${CMDLINE_FILE}"
    fi
done

# Install black framebuffer service
cat > /etc/systemd/system/aquila-black-fb.service << 'EOF'
[Unit]
Description=Set framebuffer to black before display manager starts
Before=lightdm.service display-manager.service
After=local-fs.target

[Service]
Type=oneshot
ExecStart=/bin/sh -c 'dd if=/dev/zero bs=1M count=8 > /dev/fb0 2>/dev/null || true'
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable aquila-black-fb.service

run_test "quiet in cmdline"      "grep -q 'quiet' ${CMDLINE_FILE}"
run_test "loglevel=3 in cmdline" "grep -q 'loglevel=3' ${CMDLINE_FILE}"
run_test "logo.nologo in cmdline" "grep -q 'logo.nologo' ${CMDLINE_FILE}"
run_test "black-fb service enabled" "systemctl is-enabled aquila-black-fb.service"
```

## What Is NOT Changing

- `splash.html` and its health-poll/redirect logic — untouched
- The Openbox autostart that launches Chromium — untouched
- The transition from splash to the app — untouched
- Error logging — kernel errors still go to system journal (`journalctl -b`)

## Affected Files

| File | Change |
|------|--------|
| `config.txt` | Add `framebuffer_ignore_alpha=1` (already has `disable_splash=1`) |
| `scripts/deploy/deployment2.sh` | New phase: add cmdline flags, install systemd service |
| `/etc/systemd/system/aquila-black-fb.service` | New file on device (created by deployment2.sh) |

## Acceptance Criteria

- [ ] On cold boot, no Tux penguin logo is visible
- [ ] On cold boot, no kernel printk messages scroll on screen
- [ ] On cold boot, no Pi rainbow/firmware splash is visible
- [ ] The gap between kernel and X11 is black (not purple/magenta)
- [ ] Acorn splash page (`splash.html`) appears as the first visible content
- [ ] Transition from splash to app still works
- [ ] Kernel errors are still captured in `journalctl -b` — not silenced from logs
- [ ] `deployment2.sh` is idempotent — running it twice does not duplicate cmdline flags
- [ ] Tests pass: `pytest tests unit_tests -v`

## Testing Notes

Hardware-only — must be verified on a physical Pi by power-cycling the device.
Cannot be tested in simulation mode or CI.
