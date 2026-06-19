# Frontend / UI Spec: [Screen or Flow Name]

**Status:** Draft 
**Author:** Jack
**Last updated:** 2026-06-02
**GitHub issue:** #92
**Affected screens:** N/A
**Source file(s):** `sentri_web/static/help.html`

---

## 1. Overview

Renamed `Not Detected` to be `Undetected` under Results section of `sentri_web/static/help.html`. Additionally, added a section detailing extra steps if an `Unconclusive` status is given as a result.

---

## 2. Screen Inventory

| Screen ID | Name | Entry condition | Exit conditions |
|-----------|------|----------------|-----------------|
| `help` | Help | User taps the `?` Help link (`href="/help"`) from any page header | User taps a nav-header link (Run → `/run`, History → `/history`, Profiles → `/profiles-page`) |

### Tabs within the Help screen (client-side panels, no route change)

| Tab ID | Tab label | Content |
|--------|-----------|---------|
| `tab-run` | Run | Starting a run; profile, run name, drawer; **Detection Meanings** (Detected / Inconclusive / Undetected) and the **"If a Result Is Inconclusive"** next-steps |
| `tab-history` | History | Reviewing past runs, result summaries, delete |
| `tab-profiles` | Profiles | Creating/using profiles, bundled profiles |
| `tab-detail` | Run Detail | Metadata, amplification graph, metrics, QC status |
| `tab-wifi` | Wi-Fi &amp; System | Network status, scanning, system info |
| `tab-updates` | Updates | OTA update status and actions |

Default active tab on load: `tab-run`.

---

## 3. State Machine Transitions

- N/A

---

## 4. Screen Designs

### Screen: `help`

**Layout:**
- Body: Renamed `Not Detected` to follow similar naming convetions. Added additional help section under `Results` section.

**Dynamic content:**
- Following `Results` section, there is a section titled `If a Result is Inconclusive` that further explains what is means and how to approach it.

**User interactions:**
- N/A

**Error states:**
- N/A

---

## 5. Data Binding

- N/A

---

## 6. Accessibility / Kiosk Constraints

- `If a Result is Inconclusive` section follows `Results` section.

---

## 7. Assets

- N/A

---

## 8. Acceptance Criteria

- [ ] Fixed naming convetion
- [ ] Added additional help section for Inconclusive results.

---

## 9. Open Questions

