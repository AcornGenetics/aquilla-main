# Aquila Web UI Overview

This document summarizes how the `aquila_web` UI is structured and how to edit or extend it.

## Architecture
- **Backend**: FastAPI app in `aquila-main/aquila_web/main.py` serves static HTML/CSS/JS and exposes JSON endpoints for run status, profiles, and history.
- **Frontend**: Pure static files in `aquila-main/aquila_web/static` (no build step).
- **Assets**: Served under `/static` via FastAPI `StaticFiles` mount.
- **Plots**: Rendered images served under `/plots` from `logs/plots`.

## Page map (routes → files)
- `/` and `/login` → `aquila-main/aquila_web/static/login.html`
- `/run` → `aquila-main/aquila_web/static/run.html`
- `/history` → `aquila-main/aquila_web/static/history.html`
- `/history/run` → `aquila-main/aquila_web/static/history_detail.html`
- `/profiles-page` → `aquila-main/aquila_web/static/profiles/index.html`
- `/profiles/edit` and `/profiles/edit-form` → `aquila-main/aquila_web/static/profiles/edit_form.html`
- `/help` → `aquila-main/aquila_web/static/help.html`

## Key UI files
- **Styles**: `aquila-main/aquila_web/static/styles.css`
- **Run page logic**: `aquila-main/aquila_web/static/script.js`
- **History list**: `aquila-main/aquila_web/static/history.js`
- **History detail**: `aquila-main/aquila_web/static/history_detail.js`
- **Profiles edit UI**: `aquila-main/aquila_web/static/profiles/edit_form.html`

## Data flow highlights
- **Run state**: `POST /button/run`, `GET /button_status`, and `POST /timer` update the run UI.
- **Profiles**: `GET /profiles` and `POST /profiles` read/save profile JSON.
- **History**: `GET /history/data`, `POST /history/append`, `POST /history/delete` manage the run list.
- **Results**: `GET /results` and `POST /results/path` are used by the run/plot flow.

## Editing the UI
1. **HTML layout**: edit the page under `aquila-main/aquila_web/static`.
2. **Styles**: change `aquila-main/aquila_web/static/styles.css`.
3. **Behavior**: adjust the page’s JS file (e.g., `script.js`, `history.js`).
4. **Cache busting**: update the `?v=` query on the stylesheet/script tags so the device refreshes cached assets.

## Adding a new page
1. Create a new HTML file under `aquila-main/aquila_web/static`.
2. Add a new FastAPI route in `aquila-main/aquila_web/main.py` that returns `FileResponse` pointing to the file.
3. Link to it from existing navigation (usually in `run.html` or other page headers).

## Running locally
From `aquila-main/aquila_web`:

```
uvicorn main:app --reload --host 127.0.0.1
```

The service version runs on port `8090` per `aquila-main/aquila_web/aquila_web.service`.
