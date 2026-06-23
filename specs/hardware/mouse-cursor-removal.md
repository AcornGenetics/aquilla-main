# Hardware Spec: Kiosk Mouse Cursor Removal

**Status:** Draft
**Author:** Jack Hu
**Last updated:** 2026-06-11
**Subsystem:** Comms (Kiosk display / Chromium UI)
**Source file(s):** `scripts/deploy/update_kiosk_x11.sh`, `scripts/deploy/deployment2.sh`
**Related (unchanged):** `aquila_web/static/styles.css`

---

## 1. Overview

The SENTRI is a touchscreen-only device — there is no mouse. Despite this, a mouse
cursor appears in the UI in two situations:

1. **On startup**, the pointer is visible until the cursor-hiding idle timer elapses.
2. **On every tap/click**, the pointer reappears for ~1 second as though a mouse had
   moved to the tapped location. This is most obvious on dropdown fields, where the
   cursor lingers over the open menu until the dropdown is dismissed.

The purpose of this spec is to remove the mouse cursor entirely so it is **never**
visible on the SENTRI display — not at boot, not on tap, not over dropdowns.

---

## 2. Hardware Components

| Component | Part / Model | Interface | Notes |
|-----------|-------------|-----------|-------|
| Capacitive touchscreen | Focaltech Systems FT5926 MultiTouch | USB HID (touch as pointer) | The OS treats touch events as pointer events, which is what made `unclutter` re-show the cursor on each tap. No mouse is attached. |
| Display | HDMI panel, 1024×768, rotated right | HDMI-2 | Rendered by Chromium kiosk via X11/Openbox. |
| Raspberry Pi (host) | RPi running Raspberry Pi OS Bookworm | — | Runs LightDM → X11 → Openbox → Chromium kiosk. |

**No component is removed, added, or rewired — this is a display/software configuration
change, not a hardware change.**

---

## 3. Root Cause

Cursor hiding was previously handled by **`unclutter`**, invoked from the Openbox
autostart:

- `scripts/deploy/update_kiosk_x11.sh` — `unclutter -idle 0.5 &`
- `scripts/deploy/deployment2.sh` — `unclutter -idle 0 -root -noevents &`

`unclutter` hides the pointer only after an **idle timer** and, in the classic
(`-idle`) mode, **re-shows the cursor on every pointer event**. Because the
touchscreen delivers each tap as a pointer event, the cursor:

- was drawn at boot until the idle timer first elapsed, and
- was redrawn on every tap, then waited out the timer again — causing the visible
  flash and the lingering pointer over open dropdowns.

The CSS rule `aquila_web/static/styles.css:4` (`* { cursor: none !important; }`) only
hides the cursor **inside the rendered page**, so it cannot cover the boot moment or
the X-server-level pointer. It is retained as defence-in-depth but is not sufficient
on its own.

---

## 4. Control Logic / Change

The fix moves cursor suppression from a timer/event-driven tool to the **X server
level**, where the pointer sprite is simply never rendered.

**LightDM seat configuration** — start X with `-nocursor`:

```
[Seat:*]
autologin-user=pi
autologin-session=openbox
xserver-command=X -nocursor
```

With `-nocursor`, the X server never draws a cursor sprite. It is absent at boot and
never reappears on pointer/touch events. Touch input is unaffected — `-nocursor`
disables only the *rendering* of the pointer, not pointer input.

**Openbox autostart** — the per-session `unclutter` invocation is removed and replaced
with a one-shot root-window cursor reset as a belt-and-suspenders backup:

```
xsetroot -cursor_name none
```

### Files changed

| File | Before | After |
|------|--------|-------|
| `scripts/deploy/update_kiosk_x11.sh` | `unclutter -idle 0.5 &` in autostart | `xserver-command=X -nocursor` in LightDM autologin.conf; `xsetroot -cursor_name none` in autostart |
| `scripts/deploy/deployment2.sh` | `unclutter -idle 0 -root -noevents &` in autostart | `xserver-command=X -nocursor` in both LightDM config files; `xsetroot -cursor_name none` in autostart |

> **Not changed:** `aquila_web/static/styles.css` already contains `* { cursor: none !important; }`
> (line 4), which hides the cursor *inside the rendered page*. It is left as-is and serves as
> in-page defence-in-depth, but it cannot cover the boot moment or the X-server-level pointer —
> which is why the X-server `-nocursor` change is required. **No CSS change is needed.**

### Net behaviour at startup and on interaction

- **Before:** cursor visible at boot until idle timer; reappears for ~1s on every tap;
  lingers over open dropdowns.
- **After:** cursor never rendered — not at boot, not on tap, not over dropdowns.

---

## 5. Communication Protocol

- None

---

## 6. Calibration

- None

---

## 7. Failure Modes

| Failure | Symptom | Cause | Recovery |
|---------|---------|-------|----------|
| `-nocursor` not applied | Cursor still visible after deploy | LightDM config not reloaded / X not restarted | Reboot the device (or restart LightDM) so X restarts with `-nocursor` |
| `xsetroot` missing | Autostart logs "command not found" | `x11-xserver-utils` not installed | `-nocursor` still hides the cursor; install `x11-xserver-utils` to restore the backup line |

---

## 8. Known Limitations

- The configuration is applied at **provisioning time** by the deploy scripts. An
  already-deployed SENTRI must have the LightDM config rewritten and **X restarted
  (reboot)** for the change to take effect; editing the file alone does not affect a
  running X session.
- `unclutter` remains installed by the deploy scripts (harmless) but is no longer
  invoked at runtime.

---

## 9. Testing in Simulation Mode

Which behaviors can be tested without hardware?

- The config-content assertions are covered by `run_test` checks inside the deploy
  scripts (e.g. `grep -q 'X -nocursor' .../autologin.conf`).
- The actual absence of the cursor at boot, on tap, and over dropdowns must be
  verified on a **physical SENTRI** with the touchscreen.

---

## 10. Related

- Boot splash spec: `specs/hardware/spec_boot_splash.md`
- Drawer auto-open removal (sibling removal spec): `specs/hardware/drawer-auto-open-removal.md`
- Source: `scripts/deploy/update_kiosk_x11.sh`, `scripts/deploy/deployment2.sh`, `aquila_web/static/styles.css`
