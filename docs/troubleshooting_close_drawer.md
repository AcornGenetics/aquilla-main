# Close Drawer Button Troubleshooting

## Symptom
- Clicking **Close Drawer** in the Run UI does not move the drawer.

## Root Cause
- The UI and FastAPI backend only set drawer flags; the assay loop (`application.py` → `state_run_assay.py`) must be running to act on them.
- If `run_complete_ack` is stuck `true`, `wait_for_button()` can return early and skip drawer actions unless the assay is in the `end` state.

## Verify Backend and Flags
- Confirm backend endpoint responds:
  - `curl -s -X POST http://127.0.0.1:8090/button/close`
- Check status flags:
  - `curl -s http://127.0.0.1:8090/button_status | python -m json.tool`
  - Expect `"drawer_close_status": true` after clicking.

## Reset `run_complete_ack`
- Clear the ack flag:
  - `curl -s -X POST http://127.0.0.1:8090/run/complete/ack/reset`
- Verify it cleared:
  - `curl -s http://127.0.0.1:8090/button_status | python -m json.tool`
  - Expect `"run_complete_ack": false`.

## Ensure the Assay Loop Is Running
- Check for the loop process:
  - `ps aux | grep -E "application.py" | grep -v grep`
- If it is not running, start it:
  - `cd /home/pi/aquilla-main && python application.py`

## Restart After Code Changes
- If `aq_lib/state_requests.py` or `state_run_assay.py` were modified, restart the loop:
  - `ps aux | grep -E "application.py" | grep -v grep`
  - `sudo kill <PID>`
  - `cd /home/pi/aquilla-main && python application.py`

## Notes
- The Run UI calls `notifyDrawerClose()` in `aquila_web/static/script.js` which posts to `/button/close`.
- The drawer actually moves in `state_run_assay.py` when the loop sees `drawer_close_status`.
