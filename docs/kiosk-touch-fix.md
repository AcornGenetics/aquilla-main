# Kiosk Touch Input — Diagnosis & Fix

## Symptoms

- Dragging finger selects text in blue instead of scrolling
- Can only scroll using scrollbars on the side — swipe does nothing
- Screen glitches/flickers when changing pages
- No momentum or tactile feel like a mobile browser

---

## Root Causes

### Problem 1 — Wrong browser engine (primary cause)

`server_web/autostart` launches `kiosk.py`, which uses **WebKit2GTK** — a GTK-wrapped
browser engine, not Chromium. WebKit2GTK on Linux has poor touch support:

| Symptom | Why |
|---|---|
| Drag selects text in blue | Touch events are mapped to mouse events — drag = click+drag = text selection |
| Swipe does not scroll | No native touch pan/scroll — only mouse-driven scrollbars work |
| No momentum or iPhone feel | WebKit2GTK has no touch physics engine |
| Screen flicker on transitions | GTK compositor causes repaints that Chromium handles natively |

`server_web/autostart_4b` shows a previous attempt to use Chromium directly, but
it points to the wrong port (`localhost:3000` instead of `8090`) and is missing
all touch-specific launch flags.

### Problem 2 — CSS has no touch directives

The app CSS has no `touch-action`, `user-select: none`, or
`-webkit-overflow-scrolling` declarations. Even with a touch-capable browser,
the app itself needs these to suppress text selection and enable momentum
scrolling on scrollable containers.

---

## Fix 1 — Switch autostart from WebKit2GTK to Chromium

**File:** `server_web/autostart`

Replace:
```bash
sleep 3
python3 /home/pi/kiosk.py &
```

With:
```bash
sleep 3
chromium-browser --kiosk \
  --touch-events=enabled \
  --enable-touch-drag-drop \
  --disable-pinch \
  --overscroll-history-navigation=0 \
  --no-first-run \
  --disable-infobars \
  --disable-session-crashed-bubble \
  --check-for-update-interval=31536000 \
  http://localhost:8090 &
```

### Flag reference

| Flag | Purpose |
|---|---|
| `--touch-events=enabled` | Critical — without this Chromium treats all touch as mouse |
| `--enable-touch-drag-drop` | Enables touch-based drag interactions |
| `--disable-pinch` | Prevents accidental pinch-to-zoom on the touchscreen |
| `--overscroll-history-navigation=0` | Disables swipe-left/right triggering browser back/forward |
| `--no-first-run` | Suppresses the "Welcome to Chrome" overlay on first boot |
| `--disable-infobars` | Hides the "Chrome is being controlled" info bar |
| `--disable-session-crashed-bubble` | Suppresses crash restore prompt after unclean shutdown |
| `--check-for-update-interval=31536000` | Disables auto-update checks (1 year interval) |

---

## Fix 2 — Add touch CSS to styles.css

**File:** `sentri_web/static/styles.css`

Add to the top of the file:

```css
/* Prevent text selection on touch drag */
body, button, a, div {
  -webkit-user-select: none;
  user-select: none;
}

/* Allow text selection inside inputs only */
input, textarea {
  -webkit-user-select: text;
  user-select: text;
}

/* Prevent double-tap zoom, improve tap response */
button, a {
  touch-action: manipulation;
}

/* Momentum scrolling on scrollable containers */
main,
section,
.help-content,
.history-list,
.scrollable {
  -webkit-overflow-scrolling: touch;
  overflow-y: auto;
}
```

---

## Fix summary

| Symptom | Cause | Fix |
|---|---|---|
| Text selects in blue on drag | WebKit2GTK maps touch → mouse | Switch to Chromium + `--touch-events=enabled` |
| Only scrollbars work | No touch scroll in WebKit2GTK | Chromium handles natively |
| Screen flickers on transition | GTK compositing | Chromium compositing is clean |
| No momentum / feel | No physics in WebKit2GTK | Chromium + `-webkit-overflow-scrolling: touch` |

---

## Deployment

1. Update `server_web/autostart` on the Pi (copy from repo or edit in place)
2. Rebuild the image if `styles.css` change is included
3. Reboot the Pi — Openbox reads `autostart` on session start

```bash
sudo reboot
```

After reboot, Chromium launches instead of the GTK window. Touch scroll,
momentum, and tap behavior should match a standard mobile browser.

---

## Notes

- `kiosk.py` (WebKit2GTK) can be kept in the repo as a fallback but should not
  be the primary launcher
- If `chromium-browser` is not found, try `chromium` (command name varies by
  Pi OS version)
- The `autostart_4b` file was a previous Chromium attempt — it can be updated
  to match the new command and used as the canonical file going forward
