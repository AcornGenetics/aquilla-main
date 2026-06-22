"""
D2 — systemd service-unit reference integrity (rebrand #187, ADR-016).

Deploy scripts install/enable/restart units by literal filename, guarded by
`[[ -f ... ]]`. If a unit file is renamed but a script reference is missed, the
guard silently skips it and the service is never installed — a silent no-op on
device. After the rebrand no `aquila`-named unit may remain, and the shipped
units must be named `sentri_*`.
"""
import re
from pathlib import Path

SCAN_DIRS = [Path("scripts"), Path("config_files")]
SERVICE_FILES = list(Path(".").glob("**/*.service"))
AQUILA_UNIT_RE = re.compile(r"aquila[-_][A-Za-z0-9-]*\.service")

# Units shipped as files in the repo that the rebrand renames.
RENAMED_UNIT_FILES = [
    Path("config_files/sentri_app.service"),
    Path("sentri_web/sentri_web.service"),
]


def _text_files():
    for d in SCAN_DIRS:
        for p in d.rglob("*"):
            if p.is_file():
                yield p
    yield from SERVICE_FILES


def test_no_aquila_named_service_units():
    offenders = {}
    for p in _text_files():
        try:
            hits = AQUILA_UNIT_RE.findall(p.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, IsADirectoryError):
            continue
        if hits:
            offenders[str(p)] = sorted(set(hits))
    assert not offenders, "stale aquila-named .service references:\n" + "\n".join(
        f"  - {f}: {names}" for f, names in sorted(offenders.items())
    )


def test_renamed_unit_files_exist():
    missing = [str(f) for f in RENAMED_UNIT_FILES if not f.exists()]
    assert not missing, f"renamed unit file(s) not found: {missing}"
