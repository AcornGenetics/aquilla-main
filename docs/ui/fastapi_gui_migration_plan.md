# FastAPI GUI Visual Update Plan

This checklist focuses on keeping the existing FastAPI app (`aquila-main/aquila_web`) while updating the UI to match the new design.

## 1) Inventory the current UI surface
- Identify the static pages served by FastAPI: `/`, `/ready`, `/run`, `/complete` in `aquila-main/aquila_web/main.py`.
- Review the markup for each screen in `aquila-main/aquila_web/static/index.html`, `ready.html`, `run.html`, and `complete.html`.
- Review the shared UI behavior in `aquila-main/aquila_web/static/script.js` (screen routing, button posts, results table, profile dropdown).

## 2) Decide the layout approach
- If you want a sidebar and multiple pages, decide whether to keep multiple static HTML files or move to a single page that conditionally renders sections.
- Keep the existing URL routes if you want to minimize backend changes, or add new routes to FastAPI for new pages.

## 3) Add a sidebar (layout-only)
- Add a sidebar container to each HTML page (or to a shared layout if you consolidate pages).
- Move existing content into a “main content” wrapper next to the sidebar.
- Copy visual styles (colors, spacing, fonts) from the new design into `aquila-main/aquila_web/static/styles.css`.

## 4) Add new pages
- Create new HTML files in `aquila-main/aquila_web/static/` for each new page (e.g., `settings.html`, `history.html`).
- Add new FastAPI routes in `aquila-main/aquila_web/main.py` that return those files.
- Update sidebar links to point at the new routes.

## 5) Change the start page
- Update the `/` route in `aquila-main/aquila_web/main.py` to return the new start page (e.g., `login.html` or `dashboard.html`).
- If you keep `/ready` as the first operational screen, link to it after login.

## 6) Add a login screen (visual + minimal logic)
- Create `login.html` in `aquila-main/aquila_web/static/` with the desired design.
- Add a FastAPI route `/login` to serve it.
- In `script.js`, add a lightweight client-side submit handler that navigates to `/ready` (or your new landing page).
- If you need real auth later, keep the markup but stub the handler for now.

## 7) Keep existing functional hooks
- Keep button endpoints (`/button/run`, `/button/open`, `/button/close`, `/button/exit`) unchanged so hardware logic stays intact.
- Keep profile loading (`/profiles`) and results (`/results`) as-is until you’re ready to change logic.
- If you rework the structure, ensure elements referenced in `script.js` keep the same IDs or update the JS accordingly.

## 8) Visual refresh steps (design-only)
- Update typography, colors, and spacing in `aquila-main/aquila_web/static/styles.css`.
- Update layout structure in the HTML files to match the new design (sidebar, panels, cards).
- Replace any inline styles in HTML with classes in `styles.css` for consistency.

## 9) Optional: consolidate JS for multiple pages
- If you add more pages, split `script.js` into page-specific scripts (e.g., `login.js`, `ready.js`, `run.js`) to avoid conditional logic.
- Keep shared utilities in a small `shared.js` file.

## 10) Smoke check on device
- Load each page route on the device and verify layout, navigation, and button clicks.
- Confirm the WebSocket and timer still update the running screen.

## Suggested order of work
1. Update `styles.css` with new palette, fonts, and layout primitives.
2. Add a sidebar to the existing pages.
3. Add a login page and point `/` at it.
4. Add new pages/routes and wire them into the sidebar.
5. Adjust `script.js` as needed for new DOM structure.

