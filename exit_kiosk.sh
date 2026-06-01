#!/bin/bash
export DISPLAY=:0
export XAUTHORITY=${XAUTHORITY:-/home/pi/.Xauthority}

if command -v sudo >/dev/null 2>&1 && sudo -n true 2>/dev/null; then
  sudo pkill -f "chromium" || true
  sudo pkill -f "chromium-browser" || true
else
  pkill -f "chromium" || true
  pkill -f "chromium-browser" || true
fi
