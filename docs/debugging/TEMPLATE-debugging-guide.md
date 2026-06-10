# Debugging Guide: [Subsystem or Symptom Name]

**Author:** [Name]
**Last updated:** YYYY-MM-DD
**Applies to:** [Device generation / software version / OS]

---

## Symptom

Describe what the engineer or operator sees. Use exact language — error messages, LED states, screen text, log lines.

```
Example: Device shows "Thermal error" on kiosk screen after lid close.
Example: pytest test_thermal fails with: AssertionError: expected temp 60.0, got 0.0
```

---

## Quick Triage

Run these first to narrow down the cause:

```bash
# Check application logs
tail -n 100 logs/aquila.log

# Check hardware state via API
curl http://localhost:8000/api/status

# Check if running in simulation mode
echo $SIMULATION

# Check device is reachable (for Pi deployments)
ping [device-hostname].local
```

---

## Likely Causes (ordered by frequency)

### 1. [Most common cause]

**Signs:** [How to tell this is the cause]

**Root cause:** [Why this happens]

**Fix:**
```bash
# Command or steps
```

**Verify fix:**
```bash
# How to confirm it's resolved
```

---

### 2. [Second most common cause]

[Same format]

---

### 3. [Less common / hardware-specific cause]

[Same format]

---

## Log Locations

| Log | Path | Contains |
|-----|------|----------|
| App log | `logs/aquila.log` | General runtime events |
| Thermal log | `logs/thermal.log` | TEC control loop data |
| [other] | | |

---

## Useful Commands

```bash
# Restart the application service (Pi only)
sudo systemctl restart aquila

# Check service status
sudo systemctl status aquila

# View recent logs with timestamps
journalctl -u aquila -n 50 --no-pager

# Run in simulation mode locally
SIMULATION=true python application.py

# Force hardware re-init (if ADC/serial stuck)
# [specific command or procedure]
```

---

## When to Escalate

- If the issue persists after all steps above
- If you see log lines containing: `CRITICAL` or `HardwareFault`
- If the physical device is unresponsive after power cycle

Escalate to: [name / Slack channel]

---

## Related

- Spec: `specs/hardware/[subsystem].md`
- ADR: `docs/adr/ADR-XXX-[relevant].md`
- Known issues: `docs/debugging/known-issues.md`
