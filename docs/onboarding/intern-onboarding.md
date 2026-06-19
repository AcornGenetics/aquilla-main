# Intern Onboarding Guide

**Last updated:** 2026-05-30
**For:** Engineering interns (software, hardware/software, or analysis track)

If something in this guide is wrong or out of date, fix it. You're not the last person who will read this.

---

## Day 1: Get Running

### 1. Clone the repo

```bash
git clone https://github.com/AcornGenetics/aquilla-main.git
cd aquilla-main
```

### 2. Set up your Python environment

```bash
python3 -m venv venv
source venv/bin/activate

# Mac/local development — use these (requirements.txt and requirements-backend.txt
# include RPi.GPIO and spidev which are Pi-only and won't install on macOS)
pip install -r requirements-mac.txt   # core app, Mac-safe
pip install -r requirements-test.txt  # test dependencies — always install this
```

### 3. Run the tests (your baseline)

```bash
 pytest tests unit_tests -v -m "not hardware and not e2e"
```

### 4. Set `src_basedir` for local development

`src_basedir` is the root directory the app uses to read/write logs, results, profiles, and the local database. **You must set this manually in two places to run locally.**

**1. `config.json`** — change `src_basedir` to your local repo path:

```json
{
  "src_basedir": "/Users/yourname/aquilla-main/"
}
```

**2. `config.py`** — change `DEFAULT_SRC_BASEDIR` to the same path:

```python
DEFAULT_SRC_BASEDIR = "/Users/yourname/aquilla-main/"
```

Verify it resolved correctly:

```bash
python -c "from config import get_src_basedir; print(get_src_basedir())"
# Should print your local repo path
```

> **Important:** Do not commit either of these changes. Both files are set to `/opt/aquila` for the Pi — restore them before pushing, or add `config.json` and `config.py` to your local `.git/info/exclude`.

### 5. Run the app in simulation mode

```bash
AQ_DEV_SIMULATE=1 AQ_DEV_RUN_DURATION=3 uvicorn sentri_web.main:app --host 127.0.0.1 --port 8090
```
Open `http://localhost:8090` in a browser. You should see the UI.
---

## Understanding the Codebase

The codebase has five main bounded contexts. Learn the one relevant to your work first.

| Directory | What it does |
|-----------|-------------|
| `sentri_lib/` | Hardware device control — thermal, motor, LED, ADC, lid sensor |
| `sentri_curve/` | PCR curve analysis — sigmoid fitting, Cq calculation, R² |
| `sentri_web/` | FastAPI backend + WebSocket + local/cloud DB |
| `sentri_web/static/` | Kiosk frontend — plain HTML/JS, no build step |
| `tests/` + `unit_tests/` | Test suite |

Key files to read on day 1:
- `CLAUDE.md` — engineering rules 
- `docs/architecture/` — system overview
- `docs/adr/` — why things are the way they are
- `specs/` — what features are supposed to do

---

## How We Work

### Communication

- **Primary:** GitHub (issues, PRs, comments)
- **Async updates:** Slack `#aquila-dev` — post your daily update by noon
- **Escalation:** Direct message your lead, or `@` them in Slack

### Git Workflow

- Branch off `main`
- Branch names: `short-description`
- One PR per feature/fix
- Rebase or merge main into your branch before opening a PR
- Never force-push to main

### Code Style

- Python: follow existing style (no linter enforced, but match the surrounding code)
- No new dependencies without approval
- No hardcoded values — put config in `config.json` or environment variables

---

## If You're Stuck

1. Read the relevant spec in `specs/`
2. Read the debugging guide in `docs/debugging/`
3. Check `docs/debugging/known-issues.md`
4. Search closed GitHub issues
5. Ask in Slack — include what you tried and what you expected

Do not spend more than 30 min stuck on the same thing without asking!

---