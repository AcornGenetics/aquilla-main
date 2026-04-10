#!/usr/bin/env python3
"""
kiosk_control.py — Host-side control service for Chromium kiosk management.

Runs as a systemd service on the Pi host (NOT inside Docker).
Listens only on 127.0.0.1:9191 so it is reachable by Docker containers via
host.docker.internal (requires --add-host=host.docker.internal:host-gateway in
docker-compose) but NOT reachable from the network.

Endpoints:
    POST /exit-kiosk  — kill the Chromium kiosk process
    POST /start-kiosk — launch Chromium in kiosk mode
    GET  /health      — liveness check
"""

import logging
import os
import signal
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

# ---------------------------------------------------------------------------
# Configuration — edit these to match your deployment
# ---------------------------------------------------------------------------

LISTEN_HOST = "127.0.0.1"
LISTEN_PORT = int(os.environ.get("KIOSK_CONTROL_PORT", "9191"))

# URL Chromium should open in kiosk mode.
# deployment2.sh points Chromium at :8090 (the backend directly).
KIOSK_URL = os.environ.get("KIOSK_URL", "http://localhost:8090")

# User that runs the desktop session (needed for DISPLAY/XAUTHORITY env vars
# when launching Chromium)
KIOSK_USER = os.environ.get("KIOSK_USER", "pi")

# Chromium binary name — deployment2.sh installs "chromium" (not chromium-browser)
CHROMIUM_BIN = os.environ.get("CHROMIUM_BIN", "chromium")

# Allowed caller IPs — Docker bridge + loopback.
# 172.17.0.0/16 covers the default Docker bridge; tighten if you use a custom
# network with a known gateway (e.g. 172.20.0.1).
ALLOWED_PREFIXES = ("127.", "172.17.", "172.18.", "172.19.", "172.20.", "10.")

# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("kiosk-control")


def _is_allowed(addr: str) -> bool:
    return any(addr.startswith(prefix) for prefix in ALLOWED_PREFIXES)


def _kill_chromium() -> tuple[bool, str]:
    """Send SIGTERM to every Chromium process; fall back to SIGKILL."""
    patterns = [CHROMIUM_BIN, "chromium"]
    killed_any = False
    for pattern in patterns:
        result = subprocess.run(
            ["pkill", "-TERM", "-f", pattern],
            capture_output=True,
        )
        if result.returncode == 0:
            killed_any = True
    if not killed_any:
        # Nothing matched — not necessarily an error
        return True, "no chromium process found"
    return True, "chromium terminated"


def _start_chromium() -> tuple[bool, str]:
    """Launch Chromium in kiosk mode as the kiosk user."""
    env = os.environ.copy()
    env["DISPLAY"] = ":0"
    env["XAUTHORITY"] = f"/home/{KIOSK_USER}/.Xauthority"

    # Run as the desktop user if we are root; otherwise run directly.
    if os.geteuid() == 0:
        cmd = [
            "sudo", "-u", KIOSK_USER, "-E",
            CHROMIUM_BIN,
            "--kiosk",
            "--noerrdialogs",
            "--disable-infobars",
            "--ozone-platform=wayland",
            "--password-store=basic",
            "--touch-events=enabled",
            "--enable-touch-drag-drop",
            "--disable-pinch",
            "--overscroll-history-navigation=0",
            "--no-first-run",
            "--disable-session-crashed-bubble",
            KIOSK_URL,
        ]
    else:
        cmd = [
            CHROMIUM_BIN,
            "--kiosk",
            "--noerrdialogs",
            "--disable-infobars",
            "--ozone-platform=wayland",
            "--password-store=basic",
            "--touch-events=enabled",
            "--enable-touch-drag-drop",
            "--disable-pinch",
            "--overscroll-history-navigation=0",
            "--no-first-run",
            "--disable-session-crashed-bubble",
            KIOSK_URL,
        ]

    subprocess.Popen(cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return True, "chromium launched"


class KioskHandler(BaseHTTPRequestHandler):
    """Minimal HTTP handler — no external dependencies required."""

    def log_message(self, fmt, *args):  # suppress default access log spam
        log.info("request from %s: %s", self.client_address[0], fmt % args)

    def _check_origin(self) -> bool:
        addr = self.client_address[0]
        if not _is_allowed(addr):
            log.warning("rejected request from %s", addr)
            self._respond(403, {"error": "forbidden"})
            return False
        return True

    def _respond(self, code: int, body: dict) -> None:
        import json
        payload = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        if self.path == "/health":
            self._respond(200, {"ok": True})
        else:
            self._respond(404, {"error": "not found"})

    def do_POST(self):
        if not self._check_origin():
            return

        if self.path == "/exit-kiosk":
            ok, msg = _kill_chromium()
            log.info("exit-kiosk: %s", msg)
            self._respond(200 if ok else 500, {"ok": ok, "message": msg})

        elif self.path == "/start-kiosk":
            ok, msg = _start_chromium()
            log.info("start-kiosk: %s", msg)
            self._respond(200 if ok else 500, {"ok": ok, "message": msg})

        else:
            self._respond(404, {"error": "not found"})


def main():
    server = HTTPServer((LISTEN_HOST, LISTEN_PORT), KioskHandler)
    log.info("kiosk-control listening on %s:%d", LISTEN_HOST, LISTEN_PORT)

    def _shutdown(signum, frame):
        log.info("shutting down")
        server.shutdown()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    server.serve_forever()


if __name__ == "__main__":
    main()
