"""
Unit tests: the app layer must never hide the mouse cursor (#285).

Cursor hiding on the physical SENTRI is handled entirely at the X-server level
(`xserver-command=X -nocursor`, PR #153 / specs/hardware/mouse-cursor-removal.md).
The in-page CSS rule from PR #126 (`* { cursor: none !important; }`) was removed
because it also hid the cursor in the dev environment; every fleet device has
been provisioned with the X-server fix, so the CSS layer is redundant.

These tests pin that invariant: no app CSS or page may reintroduce
`cursor: none`, and the interim dev-cursor.js shim must stay gone.

Spec: specs/frontend/spec_dev_cursor_visible.md
"""
import re
from pathlib import Path

STATIC_DIR = Path(__file__).parent.parent / "aquila_web" / "static"

CURSOR_NONE_RE = re.compile(r"cursor\s*:\s*none")


def test_app_stylesheets_never_hide_the_cursor():
    """No shipped stylesheet may set cursor: none — device hiding is X-server-level."""
    offenders = [
        str(p.relative_to(STATIC_DIR))
        for p in STATIC_DIR.rglob("*.css")
        if CURSOR_NONE_RE.search(p.read_text(encoding="utf-8"))
    ]
    assert not offenders, (
        f"stylesheets hide the cursor (breaks dev; device uses X -nocursor): {offenders}"
    )


def test_no_page_hides_the_cursor_inline():
    """No HTML page (splash included) may set cursor: none in inline styles."""
    offenders = [
        str(p.relative_to(STATIC_DIR))
        for p in STATIC_DIR.rglob("*.html")
        if CURSOR_NONE_RE.search(p.read_text(encoding="utf-8"))
    ]
    assert not offenders, (
        f"pages hide the cursor inline (breaks dev; device uses X -nocursor): {offenders}"
    )


def test_dev_cursor_shim_is_fully_removed():
    """The interim dev-cursor.js shim and all references to it are gone.

    It existed only to undo the CSS hiding rule in dev; with the rule removed
    it is dead weight, and a stale <script> include would 404 on every page.
    """
    assert not (STATIC_DIR / "dev-cursor.js").exists(), "dev-cursor.js must be deleted"
    referencing = [
        str(p.relative_to(STATIC_DIR))
        for p in STATIC_DIR.rglob("*.html")
        if "dev-cursor.js" in p.read_text(encoding="utf-8")
    ]
    assert not referencing, f"pages still reference dev-cursor.js: {referencing}"
