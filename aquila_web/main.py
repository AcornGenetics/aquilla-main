from fastapi import FastAPI, Form, Body, HTTPException, Query
from aq_lib.device_id import inject_hw_serial_env
from aquila_web.local_db import enqueue_event, init_local_db
from aquila_web.profile_assembly import assemble_steps, validate_stages
from fastapi.responses import FileResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from fastapi import WebSocket
import asyncio
import logging
from datetime import datetime
import os
import sys
from pydantic import BaseModel
from typing import Optional
import json
import re
from aq_curve.analysis_service import AnalysisService

logger = logging.getLogger( __name__ )
logger.setLevel("WARNING")

app = FastAPI(redirect_slashes=False)
static_dir = Path(__file__).parent / "static"

state_change_event = asyncio.Event()
start_time = None
elapsed_time = 0
timer_running = None
#results_path = Path("/home/pi/aquilla-main/aquila_web/results.json")
results_path = None
results_cleared = False
DEV_SIMULATE = os.getenv("AQ_DEV_SIMULATE", "0") == "1"
SIM_RUN_SECONDS = float(os.getenv("AQ_DEV_RUN_DURATION", "8"))
DEV_OPTICS_PATH = os.getenv("AQ_DEV_OPTICS_PATH")
dev_optics_path = DEV_OPTICS_PATH
DEV_DRAWER_OPEN_SECONDS = float(os.getenv("AQ_DEV_DRAWER_OPEN_SECONDS", "3"))
DEV_DRAWER_CLOSE_SECONDS = float(os.getenv("AQ_DEV_DRAWER_CLOSE_SECONDS", "3"))
# Dev-simulation overrides — force UI states that normally require real hardware
# or external services, so they can be exercised locally. To add another, follow
# this same pattern (AQ_DEV_<THING> -> module flag) and honour it at the seam
# that produces the state. See get_update_status() for AQ_DEV_UPDATE_AVAILABLE.
DEV_UPDATE_AVAILABLE = os.getenv("AQ_DEV_UPDATE_AVAILABLE", "0") == "1"
run_in_progress = False
MODULE_BASE_DIR = Path(__file__).resolve().parents[1]
if str(MODULE_BASE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_BASE_DIR))
from config import get_src_basedir
BASE_DIR = Path(get_src_basedir()).expanduser()
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))
RESULTS_DIR = BASE_DIR / "logs" / "results"
PLOTS_DIR = BASE_DIR / "logs" / "plots"
HISTORY_PATH = BASE_DIR / "logs" / "history.json"
DEFAULT_PROFILE_DIR = BASE_DIR / "profiles"
LOCAL_PROFILE_DIR = MODULE_BASE_DIR / "profiles"
BUNDLED_PROFILE_DIR = DEFAULT_PROFILE_DIR / "bundled"
LOCAL_BUNDLED_PROFILE_DIR = LOCAL_PROFILE_DIR / "bundled"

PLOTS_DIR.mkdir(parents=True, exist_ok=True)
_analysis = AnalysisService(RESULTS_DIR)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
app.mount("/plots", StaticFiles(directory=str(PLOTS_DIR)), name="plots")

def resolve_profile_dir() -> Path:
    if DEFAULT_PROFILE_DIR.exists():
        return DEFAULT_PROFILE_DIR
    return LOCAL_PROFILE_DIR

def _load_profile_labels(profile_name: str | None) -> dict:
    if not profile_name:
        return {}
    profile_dir = resolve_profile_dir()
    if not profile_dir.exists():
        return {}
    for path in profile_dir.rglob("*.json"):
        try:
            with path.open() as f:
                data = json.load(f)
            title = data.get("title", path.stem)
            profile_title = data.get("name", title)
            if profile_title == profile_name or path.stem == profile_name or path.name == profile_name:
                labels = data.get("labels")
                return labels if isinstance(labels, dict) else {}
        except Exception:
            continue
    return {}

def _profile_rox_unavailable(profile_name: str | None) -> bool:
    if not profile_name:
        return False
    profile_dir = resolve_profile_dir()
    if not profile_dir.exists():
        return False
    for path in profile_dir.rglob("*.json"):
        try:
            with path.open() as f:
                data = json.load(f)
            title = data.get("title", path.stem)
            profile_title = data.get("name", title)
            if profile_title == profile_name or path.stem == profile_name or path.name == profile_name:
                return bool(data.get("rox_unavailable", False))
        except Exception:
            continue
    return False

def _resolve_profile_display_name(profile_ref: str | None) -> str:
    """Resolve a profile reference to its human-readable display name.

    ``profile_ref`` is normally the id stored by ``/profile/select`` — the
    relative path emitted by ``GET /profiles`` (e.g. ``local/A3_Invalid_Temp.json``).
    History must show the profile's ``name`` (e.g. ``A3 Invalid Temp``), never the
    ``local/`` prefix, the ``.json`` extension, or the filename's underscores
    (issue #267). Idempotent when given a value that is already a display name.
    See specs/backend/spec_history_profile_display_name.md.
    """
    if not profile_ref:
        return "--"
    profile_dir = resolve_profile_dir()
    # 1. Normal path: treat the ref as the relative-path id and read its JSON name.
    try:
        candidate = profile_dir / profile_ref
        if candidate.is_file():
            data = json.loads(candidate.read_text())
            name = data.get("name") or data.get("title")
            if name:
                return str(name)
    except Exception:
        pass
    # 2. Otherwise match by name/stem/filename/id across the profile tree.
    try:
        if profile_dir.exists():
            for path in profile_dir.rglob("*.json"):
                try:
                    data = json.loads(path.read_text())
                except Exception:
                    continue
                name = data.get("name") or data.get("title") or path.stem
                rel = str(path.relative_to(profile_dir))
                if profile_ref in (name, path.stem, path.name, rel):
                    return str(name)
    except Exception:
        pass
    # 3. Fallback: strip the directory and a trailing .json so a path is never
    #    shown, while preserving dots that are part of the name (e.g. "Cycle 2.5").
    return Path(profile_ref).name.removesuffix(".json")

def _all_bundled_filenames() -> set[str]:
    profile_groups_path = BASE_DIR / "config_files" / "profile_groups.json"
    try:
        groups = json.loads(profile_groups_path.read_text())
        result = set()
        for v in groups.values():
            if isinstance(v, list):
                result.update(v)
        return result
    except Exception:
        return set()


def _migrate_profiles() -> None:
    base = Path(BASE_DIR) / "profiles" if not str(BASE_DIR).endswith("profiles") else Path(BASE_DIR)
    # Use the resolved profile dir (may differ in dev mode)
    pdir = resolve_profile_dir()
    bundled_sub = pdir / "bundled"
    local_sub = pdir / "local"

    if bundled_sub.exists() and local_sub.exists():
        return

    known_bundled = _all_bundled_filenames()
    if not known_bundled:
        logger.warning("_migrate_profiles: profile_groups.json unreadable — skipping migration")
        return

    bundled_sub.mkdir(parents=True, exist_ok=True)
    local_sub.mkdir(parents=True, exist_ok=True)

    moved_bundled = 0
    moved_local = 0
    for flat_file in list(pdir.glob("*.json")):
        if flat_file.name in known_bundled:
            dest = bundled_sub / flat_file.name
            if dest.exists():
                flat_file.unlink(missing_ok=True)
            else:
                flat_file.rename(dest)
                moved_bundled += 1
        else:
            dest = local_sub / flat_file.name
            try:
                flat_file.rename(dest)
                moved_local += 1
            except Exception as e:
                logger.error("_migrate_profiles: failed to move %s to local/: %s", flat_file.name, e)

    logger.info("_migrate_profiles: moved %d → bundled/, %d → local/", moved_bundled, moved_local)


_migrate_profiles()

profile_dir = resolve_profile_dir()
run_requested = False
selected_profile = None
run_name = "run1"
run_counter = 1
drawer_open = False
drawer_close = False
exit_button = False
run_complete_ack = False
stop_requested = False
drawer_task = None
drawer_state_open = False
drawer_state_closed = False
sim_exit_pending = False
force_exit = False
DEFAULT_TUBE_NAMES = ["Tube 1", "Tube 2", "Tube 3", "Tube 4"]
current_tube_names = DEFAULT_TUBE_NAMES[:]

class Item(BaseModel):
    title: str = "Arete Biosciences"
    text: str = "Cubit"
    screen: str = "init"

class TimerControl(BaseModel):
    action: str

def estimated_minutes_to_seconds(minutes) -> Optional[int]:
    """Convert an optional estimated-completion time (minutes) to whole seconds.

    Returns None for missing / blank / non-positive / invalid input, which the
    caller treats as "no estimate" (Run screen falls back to the stopwatch).
    """
    if isinstance(minutes, bool):
        return None
    if not isinstance(minutes, (int, float)):
        return None
    if minutes != minutes:  # NaN
        return None
    if minutes in (float("inf"), float("-inf")):
        return None
    if minutes <= 0:
        return None
    return int(round(minutes)) * 60


def _order_time_fields(profile: dict) -> dict:
    """Return a copy of *profile* with ``time_unavailable`` and
    ``estimated_completion_seconds`` placed immediately after ``rox_unavailable``
    (or after ``title`` when ``rox_unavailable`` is absent)."""
    time_unavailable = profile.get("time_unavailable", True)
    estimated = profile.get("estimated_completion_seconds")
    anchor = "rox_unavailable" if "rox_unavailable" in profile else "title"
    ordered: dict = {}
    inserted = False
    for key, value in profile.items():
        if key in ("time_unavailable", "estimated_completion_seconds"):
            continue
        ordered[key] = value
        if key == anchor:
            ordered["time_unavailable"] = time_unavailable
            ordered["estimated_completion_seconds"] = estimated
            inserted = True
    if not inserted:
        ordered["time_unavailable"] = time_unavailable
        ordered["estimated_completion_seconds"] = estimated
    return ordered


# Canonical top-level key order for structured profiles (issue #213 / A4):
# metadata first, then the human-authored stages, then the derived steps last.
CANONICAL_PROFILE_KEY_ORDER = (
    "output_dir",
    "post_in_gui",
    "title",
    "rox_unavailable",
    "time_unavailable",
    "estimated_completion_seconds",
    "labels",
    "stages",
    "steps",
)


def _order_profile_keys(profile: dict) -> dict:
    """Return a copy of *profile* with top-level keys in CANONICAL_PROFILE_KEY_ORDER.

    Only keys that are present are emitted (no injection). Any keys not in the
    canonical list are preserved and appended in their original relative order
    (never dropped). See spec_profile_key_order.md."""
    ordered: dict = {}
    for key in CANONICAL_PROFILE_KEY_ORDER:
        if key in profile:
            ordered[key] = profile[key]
    for key, value in profile.items():
        if key not in ordered:
            ordered[key] = value
    return ordered


class ProfileSelect(BaseModel):
    profile: str

class ProfileSave(BaseModel):
    name: str
    profile_id: Optional[str] = None
    steps: Optional[list] = None
    fam_label: Optional[str] = None
    rox_label: Optional[str] = None
    # Optional estimated completion time, in minutes. None clears any existing estimate.
    estimated_minutes: Optional[int] = None
    # Structured-editor source of truth (issue #197 contract). When present, the
    # profile is a Structured Profile; assembly/validation of these stages into
    # `steps` is handled separately (A1/A2/A3). Persisted verbatim here.
    stages: Optional[dict] = None

class ProfileDelete(BaseModel):
    profiles: list[str]

class ResultPath(BaseModel):
    path: str

current_item = Item( title = "title_bm", text = "text_bm", screen="init" )
#start_time = datetime.now()

def _sanitize_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_") or "run"

def _normalize_tube_names(names: list | None) -> list[str]:
    if not isinstance(names, list):
        return DEFAULT_TUBE_NAMES[:]
    resolved = []
    for index, fallback in enumerate(DEFAULT_TUBE_NAMES):
        value = names[index] if index < len(names) else None
        if isinstance(value, str) and value.strip():
            resolved.append(value.strip())
        else:
            resolved.append(fallback)
    return resolved

def _next_run_info(history: list[dict] | None = None) -> tuple[str, int]:
    if history is None:
        history = _load_history()
    used_numbers = set()
    for entry in history:
        name = str(entry.get("run_name") or "").strip()
        match = re.fullmatch(r"run(\d+)", name, flags=re.IGNORECASE)
        if match:
            used_numbers.add(int(match.group(1)))
    next_number = 1
    while next_number in used_numbers:
        next_number += 1
    return f"run{next_number}", next_number

def _default_run_name() -> str:
    return _next_run_info()[0]

def _set_run_name(value: str | None) -> str:
    global run_name
    if value and value.strip():
        run_name = value.strip()
    return run_name

def _advance_run_name() -> str:
    global run_counter, run_name
    run_name, run_counter = _next_run_info()
    return run_name

def _load_history() -> list[dict]:
    if not HISTORY_PATH.exists():
        return []
    try:
        with HISTORY_PATH.open() as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
    except Exception:
        return []
    return []

def _init_run_name() -> None:
    global run_name, run_counter
    run_name, run_counter = _next_run_info()

def _save_history(entries: list[dict]) -> None:
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with HISTORY_PATH.open("w") as f:
        json.dump(entries, f, indent=2)

def _latest_history_results_path() -> Path | None:
    history = _load_history()
    for entry in reversed(history):
        if not isinstance(entry, dict):
            continue
        path_value = entry.get("results_path")
        if not path_value:
            continue
        candidate = Path(path_value)
        if not candidate.is_absolute():
            candidate = BASE_DIR / path_value.lstrip("/")
        return candidate
    return None

def _resolve_results_path() -> Path | None:
    global results_path
    candidates = []
    if results_path:
        candidates.append(Path(results_path))
    else:
        history_path = _latest_history_results_path()
        if history_path:
            candidates.append(history_path)
    for candidate in candidates:
        if not candidate.is_absolute():
            candidate = BASE_DIR / str(candidate).lstrip("/")
        try:
            resolved = candidate.resolve()
        except Exception:
            continue
        if resolved.exists():
            resolved_value = str(resolved)
            if results_path != resolved_value:
                results_path = resolved_value
            return resolved
    return None

_init_run_name()

def _next_run_index(profile_name: str) -> int:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    prefix = f"{profile_name}_run"
    existing = []
    for path in RESULTS_DIR.glob(f"{prefix}*.json"):
        match = re.search(r"run(\d+)", path.stem)
        if match:
            existing.append(int(match.group(1)))
    return max(existing, default=0) + 1

def _build_results(detected_tubes: list[int]) -> dict:
    results = {}
    for row in range(1, 3):
        row_key = str(row)
        results[row_key] = {}
        for col in range(1, 5):
            value = "Detected" if col in detected_tubes else "Not Detected"
            results[row_key][str(col)] = value
    return results

def _summarize_results(detected_tubes: list[int], inconclusive_tubes: list[int] | None = None) -> str:
    detected_tubes = detected_tubes or []
    inconclusive_tubes = inconclusive_tubes or []
    if not detected_tubes and not inconclusive_tubes:
        return "No targets detected"
    parts = []
    if detected_tubes:
        labels = ", ".join([f"Tube {tube}" for tube in detected_tubes])
        parts.append(f"Detected: {labels}")
    if inconclusive_tubes:
        labels = ", ".join([f"Tube {tube} inconclusive" for tube in inconclusive_tubes])
        parts.append(labels)
    return " · ".join(parts)

def _summarize_results_from_file(path: Path) -> str:
    try:
        with path.open() as f:
            data = json.load(f)
    except Exception:
        return "Results unavailable"
    detected = set()
    inconclusive = set()
    if isinstance(data, dict):
        for row in data.values():
            if not isinstance(row, dict):
                continue
            for col, value in row.items():
                if value == "Inconclusive":
                    try:
                        inconclusive.add(int(col))
                    except ValueError:
                        continue
                elif isinstance(value, str) and value and value != "Not Detected":
                    try:
                        detected.add(int(col))
                    except ValueError:
                        continue
    detected -= inconclusive
    return _summarize_results(sorted(detected), sorted(inconclusive))

def _calls_from_file(path: Path) -> list[dict]:
    _CHANNEL = {"1": "fam", "2": "rox"}
    try:
        with path.open() as f:
            data = json.load(f)
    except Exception:
        return []
    calls = []
    cq_data = data.get("cq", {})
    for row_key, channel in _CHANNEL.items():
        row = data.get(row_key, {})
        if not isinstance(row, dict):
            continue
        cq_row = cq_data.get(row_key, {})
        for col_key, call_value in row.items():
            try:
                well = int(col_key)
            except ValueError:
                continue
            cq = cq_row.get(col_key)
            calls.append({
                "well": well,
                "channel": channel,
                "call": call_value,
                "cq": float(cq) if cq is not None else None,
            })
    return calls


def _plot_filename(profile_slug: str, run_slug: str) -> str:
    return f"{profile_slug}_{run_slug}.png"

async def _simulate_drawer(action: str) -> None:
    global drawer_open, drawer_close, drawer_state_open, drawer_state_closed
    if action == "open":
        drawer_open = False
        drawer_close = False
        await asyncio.sleep(DEV_DRAWER_OPEN_SECONDS)
        drawer_open = True
        drawer_close = False
        drawer_state_open = True
        drawer_state_closed = False
        return
    if action == "close":
        drawer_open = True
        drawer_close = False
        await asyncio.sleep(DEV_DRAWER_CLOSE_SECONDS)
        drawer_open = False
        drawer_close = True
        drawer_state_open = False
        drawer_state_closed = True

def _safe_unlink(path_value: str | None) -> None:
    if not path_value:
        return
    try:
        path = Path(path_value)
        if not path.is_absolute():
            path = BASE_DIR / path_value.lstrip("/")
        resolved = path.resolve()
        if BASE_DIR not in resolved.parents:
            return
        if resolved.exists():
            resolved.unlink()
    except Exception:
        logger.exception("Failed to delete file", extra={"path": path_value})

def _delete_history_artifacts(entry: dict) -> None:
    results_path = entry.get("results_path") if isinstance(entry, dict) else None
    graph_path = entry.get("graph_path") if isinstance(entry, dict) else None
    _safe_unlink(results_path)
    if graph_path:
        graph_file = PLOTS_DIR / Path(graph_path).name
        _safe_unlink(str(graph_file))

async def _simulate_run(profile_name: str) -> None:
    global start_time, elapsed_time, timer_running, current_item
    global results_path, run_requested, run_in_progress, results_cleared, run_complete_ack
    global stop_requested, current_tube_names

    run_in_progress = True
    run_complete_ack = False
    start_time = datetime.now()
    elapsed_time = 0
    timer_running = True
    current_item.screen = "running"
    state_change_event.set()
    state_change_event.clear()

    elapsed = 0.0
    while elapsed < SIM_RUN_SECONDS:
        if stop_requested:
            timer_running = False
            run_in_progress = False
            run_requested = False
            stop_requested = False
            elapsed_time = int(elapsed)
            current_item.screen = "ready"
            state_change_event.set()
            state_change_event.clear()
            return
        await asyncio.sleep(0.5)
        elapsed += 0.5

    timer_running = False
    elapsed_time = SIM_RUN_SECONDS
    profile_slug = _sanitize_name(profile_name)
    run_slug = _sanitize_name(run_name)
    run_index = _next_run_index(profile_slug)
    run_suffix = f"run{run_index}"
    if run_slug and run_slug != run_suffix:
        run_suffix = f"{run_suffix}_{run_slug}"
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    results_file = RESULTS_DIR / f"{profile_slug}_{run_suffix}.json"
    plot_filename = _plot_filename(profile_slug, run_suffix)
    plot_path = PLOTS_DIR / plot_filename
    optics_path = Path(dev_optics_path).expanduser() if dev_optics_path else None
    if not optics_path or not optics_path.exists():
        run_in_progress = False
        run_requested = False
        timer_running = False
        current_item.screen = "ready"
        state_change_event.set()
        state_change_event.clear()
        return
    PLOTS_DIR.mkdir(parents=True, exist_ok=True)
    labels = _load_profile_labels(profile_name)
    rox_unavailable = _profile_rox_unavailable(profile_name)
    _analysis.process_run(str(optics_path), results_file.name, str(plot_path), labels=labels, rox_unavailable=rox_unavailable)
    detected_summary = _summarize_results_from_file(results_file)

    results_path = str(results_file.resolve())
    results_cleared = False

    history = _load_history()
    history.append({
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "profile": _resolve_profile_display_name(profile_name),
        "run_name": run_name,
        "result": detected_summary,
        "graph_path": f"/plots/{plot_filename}",
        "results_path": results_path,
        "labels": labels,
        "tube_names": current_tube_names
    })
    _save_history(history)
    init_local_db()
    enqueue_event(
        "run_complete",
        {
            "run_name": run_name,
            "profile": profile_name,
            "result": detected_summary,
            "calls": _calls_from_file(results_file),
        },
    )

    current_item.screen = "complete"
    state_change_event.set()
    state_change_event.clear()
    run_requested = False
    run_in_progress = False
    _advance_run_name()
    while not run_complete_ack:
        await asyncio.sleep(0.5)
    run_complete_ack = False
    current_item.screen = "ready"
    state_change_event.set()
    state_change_event.clear()


@app.get("/change_title/{new_title}")
async def change_title( new_title: str ):
    logger.info ( "Change_title" )
    global current_item
    current_item.title = new_title
    state_change_event.set()
    state_change_event.clear()
    return current_item.json()

@app.get("/change_text/{new_text}")
async def change_text( new_text: str ):
    global current_item
    current_item.text = new_text
    state_change_event.set()
    state_change_event.clear()
    return current_item.json()


@app.get("/change_string")
async def change_screen():
    logger.info ( "Change_screen" )
    state_change_event.set()
    state_change_event.clear()
    return current_item.json()

@app.post("/change_screen/")
async def change_screen(state: Item ):
    logger.info ( "Change_screen" )
    global current_item, start_time, current_tube_names
    current_item = state
    #start_time = datetime.now()
    state_change_event.set()
    state_change_event.clear()
    logger.info ( "Screen changed" )
    return current_item.json()

"""@app.post("/change_screen/")
async def change_screen(state: Item ):
    logger.info ( "Change_screen" )
    state_change_event.set()
    state_change_event.clear()
    global current_item
    current_item = state
    logger.info ( "Screen changed" )
    return current_item.json()"""

@app.post("/timer")
async def timer(payload: TimerControl):
    action = payload.action
    global start_time, elapsed_time, timer_running

    if action == "start":
        start_time = datetime.now()
        timer_running = True
        return {"message": "Timer Started"}
    
    elif action == "stop":
        if start_time and timer_running:
            elapsed_time = ( datetime.now() - start_time ).total_seconds() 
            timer_running = False
            return {"message": "Timer stopped", "elapsed": elapsed_time}
        return {"message": "Timer Stopped"}
    elif action == "reset":
        start_time = None
        elapsed_time = 0
        timer_running = False
        return {"message": "Timer reset"}
    
    else:
        raise HTTPException(status_code=400, detail="Invalid action")


@app.get("/health")
async def health_check():
    return {"status": "ok"}


@app.get("/version")
async def version_check():
    return {"version": os.getenv("AQ_APP_VERSION", "unknown")}


@app.get("/results")
async def get_results():
    try:    
        path = _resolve_results_path()
        if not path:
            raise FileNotFoundError("No results path available")
        with path.open() as f:
            data = json.load(f)
    except Exception as e:
        return {
                "path": str(results_path),
                "data": {"failed": True}
                }
    return data

@app.post("/results/path")
async def set_path(payload: ResultPath):
    global results_path, results_cleared
    results_path = payload.path
    results_cleared = False
    logger.info("Selected path:", results_path)
    return {"ok":True}

@app.post("/results/clear")
async def clear_results():
    global results_path, results_cleared, current_tube_names
    results_path = None
    results_cleared = True
    current_tube_names = DEFAULT_TUBE_NAMES[:]
    return {"ok": True}

@app.post("/run/complete/ack")
async def acknowledge_run_complete():
    global run_complete_ack
    run_complete_ack = True
    return {"ok": True}

@app.post("/run/complete/ack/reset")
async def reset_run_complete_ack():
    global run_complete_ack
    run_complete_ack = False
    return {"ok": True}


class _RunCompleteEventRequest(BaseModel):
    run_name: str
    profile: str
    results_path: Optional[str] = None


@app.post("/events/run_complete")
async def events_run_complete(req: _RunCompleteEventRequest):
    init_local_db()
    results_file = Path(req.results_path) if req.results_path else None
    result = _summarize_results_from_file(results_file) if results_file else ""
    event_id = enqueue_event(
        "run_complete",
        {
            "run_name": req.run_name,
            "profile": req.profile,
            "result": result,
            "calls": _calls_from_file(results_file) if results_file else [],
        },
    )
    return {"ok": True, "event_id": event_id}

@app.get("/results/get_path")
async def get_path():
    return {"path":results_path}

@app.get("/results/by-path")
async def get_results_by_path(path: str):
    try:
        resolved = Path(path).resolve()
        if not resolved.is_file():
            return {"data": {"failed": True}}
        with resolved.open() as f:
            data = json.load(f)
        return data
    except Exception:
        return {"data": {"failed": True}}

@app.get("/results/status")
async def get_results_status():
    return {"cleared": results_cleared}

@app.get("/tube_names")
async def get_tube_names():
    return {"names": current_tube_names}

@app.post("/tube_names")
async def set_tube_names(payload: dict):
    global current_tube_names
    names = payload.get("names") if isinstance(payload, dict) else None
    current_tube_names = _normalize_tube_names(names)
    return {"names": current_tube_names}

@app.get("/history/data")
async def history_data():
    return _load_history()

@app.post("/history/clear")
async def clear_history():
    _save_history([])
    return {"ok": True}

@app.post("/history/delete")
async def delete_history(payload: dict):
    indices = payload.get("indices", []) if isinstance(payload, dict) else []
    if not isinstance(indices, list):
        raise HTTPException(status_code=400, detail="indices must be a list")
    history = _load_history()
    index_set = {idx for idx in indices if isinstance(idx, int)}
    for idx in sorted(index_set):
        if 0 <= idx < len(history):
            _delete_history_artifacts(history[idx])
    remaining = [entry for idx, entry in enumerate(history) if idx not in index_set]
    _save_history(remaining)
    return {"ok": True, "remaining": len(remaining)}

OPTICS_PATHS_PATH = BASE_DIR / "logs" / "optics_paths.json"
OPTICS_PATHS_LIMIT = 20


def _merge_optics_history(history, path):
    """Pure: return new most-recent-first history with ``path`` merged in.

    Blank/whitespace/None ``path`` is a no-op and returns the history unchanged.
    Otherwise the (stripped) path is deduped and prepended, capped at the limit.
    """
    cleaned = (path or "").strip()
    if not cleaned:
        return list(history)
    deduped = [p for p in history if p != cleaned]
    return [cleaned, *deduped][:OPTICS_PATHS_LIMIT]


def _load_optics_history() -> list:
    if not OPTICS_PATHS_PATH.exists():
        return []
    try:
        with OPTICS_PATHS_PATH.open() as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
    except Exception:
        return []
    return []


def _save_optics_history(history) -> None:
    OPTICS_PATHS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OPTICS_PATHS_PATH.open("w") as f:
        json.dump(history, f, indent=2)


@app.get("/dev/optics_path")
async def get_dev_optics_path():
    return {"path": dev_optics_path, "history": _load_optics_history()}

@app.post("/dev/optics_path")
async def set_dev_optics_path(payload: dict):
    global dev_optics_path
    path = payload.get("path") if isinstance(payload, dict) else None
    cleaned = path.strip() if path else None
    dev_optics_path = cleaned or None
    history = _merge_optics_history(_load_optics_history(), cleaned)
    _save_optics_history(history)
    return {"path": dev_optics_path, "history": history}

@app.get("/run/name")
async def get_run_name():
    return {"name": run_name}

@app.post("/run/name")
async def set_run_name(payload: dict):
    name = payload.get("name") if isinstance(payload, dict) else None
    return {"name": _set_run_name(name)}

@app.post("/run/name/advance")
async def advance_run_name():
    return {"name": _advance_run_name()}

@app.post("/history/append")
async def append_history(payload: dict):
    global results_path, results_cleared
    path_value = payload.get("results_path")
    profile = _resolve_profile_display_name(payload.get("profile"))
    run_label = payload.get("run_name") or "--"
    graph_path = payload.get("graph_path")
    result_path = None
    if path_value:
        candidate_path = Path(path_value)
        if not candidate_path.is_absolute():
            candidate_path = BASE_DIR / path_value.lstrip("/")
        result_path = candidate_path
    result_text = _summarize_results_from_file(result_path) if result_path else "Results unavailable"
    history = _load_history()
    tube_names = payload.get("tube_names") if isinstance(payload, dict) else None
    history.append({
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "profile": profile,
        "run_name": run_label,
        "result": result_text,
        "graph_path": graph_path,
        "results_path": path_value,
        "tube_names": _normalize_tube_names(tube_names or current_tube_names)
    })
    _save_history(history)
    if result_path:
        results_path = str(result_path.resolve())
        results_cleared = False
    return {"ok": True}

@app.get("/")
async def index():
    return FileResponse(static_dir / "login.html")

@app.get("/complete")
async def run_page_2():
    return FileResponse(static_dir / "complete.html")

@app.get("/login")
async def login_page():
    return FileResponse(static_dir / "login.html")

@app.get("/run")
async def run_page():
    return FileResponse(static_dir / "run.html")

@app.get("/dashboard")
async def dashboard_page():
    return RedirectResponse(url="/run")

@app.get("/profiles-page")
async def profiles_page():
    return FileResponse(static_dir / "profiles/index.html")

@app.get("/profiles/edit")
async def profiles_edit_page():
    return FileResponse(
        static_dir / "profiles/edit_form.html",
        headers={"Cache-Control": "no-store"}
    )

@app.get("/profiles/edit-form")
async def profiles_edit_form_page():
    return FileResponse(
        static_dir / "profiles/edit_form.html",
        headers={"Cache-Control": "no-store"}
    )

@app.get("/profiles/builder")
async def profiles_builder_page():
    # Structured profile editor (issue #197). Serves the shell; the Stage UI,
    # validation, and save wiring are layered on in the frontend route (B1/B2/B3).
    return FileResponse(
        static_dir / "profiles/builder.html",
        headers={"Cache-Control": "no-store"}
    )

@app.get("/history")
async def history_page():
    return FileResponse(static_dir / "history.html")

@app.get("/history/run")
async def history_run_page():
    return FileResponse(static_dir / "history_detail.html")

@app.get("/help")
async def help_page():
    return FileResponse(static_dir / "help.html")

@app.get("/settings")
async def settings_page():
    return FileResponse(static_dir / "settings.html")

@app.post("/button/open")
async def button_open():
    global drawer_open, drawer_close, drawer_task
    if DEV_SIMULATE:
        if drawer_task and not drawer_task.done():
            return {"ok": True}
        drawer_task = asyncio.create_task(_simulate_drawer("open"))
    else:
        if drawer_state_open or drawer_open:
            logger.info("Drawer open ignored — already open or movement pending")
            return {"ok": True}
        drawer_open = True
        drawer_close = False
    logger.info("Drawer open pressed")
    return{"ok":True}

@app.post("/button/close")
async def button_close():
    global drawer_open, drawer_close, drawer_task
    if DEV_SIMULATE:
        if drawer_task and not drawer_task.done():
            return {"ok": True}
        drawer_task = asyncio.create_task(_simulate_drawer("close"))
    else:
        if drawer_state_closed or drawer_close:
            logger.info("Drawer close ignored — already closed or movement pending")
            return {"ok": True}
        drawer_close = True
        drawer_open = False
    logger.info("Drawer close pressed")
    return{"ok":True}

@app.post("/drawer_status/reset")
async def button_open():
    global drawer_close, drawer_open, drawer_task
    if drawer_task and not drawer_task.done():
        drawer_task.cancel()
        drawer_task = None
    drawer_close = False
    drawer_open = False
    logger.info("Drawer reset pressed")
    return{"ok":True}

@app.post("/button/run")
async def button_run():
    global run_requested, stop_requested
    run_requested = True
    stop_requested = False
    logger.info("Run button pressed")
    if not selected_profile:
        run_requested = False
        return {"ok": False, "message": "Select a profile before running"}
    if not run_name or not run_name.strip():
        run_requested = False
        return {"ok": False, "message": "Enter a run name before running"}
    if drawer_state_open and not drawer_state_closed:
        run_requested = False
        return {"ok": False, "message": "Close the drawer before running"}
    if DEV_SIMULATE:
        if run_in_progress:
            return {"ok": False, "message": "Run already in progress"}
        if not selected_profile:
            return {"ok": False, "message": "No profile selected"}
        if not dev_optics_path:
            return {"ok": False, "message": "Optics log path required"}
        asyncio.create_task(_simulate_run(selected_profile))
    return{"ok":True}

@app.post("/button/stop")
async def button_stop():
    global stop_requested
    stop_requested = True
    logger.info("Stop button pressed")
    return {"ok": True}

@app.post("/stop/reset")
async def stop_button_reset():
    global stop_requested
    stop_requested = False
    logger.info("Stop reset")
    return {"ok": True}

@app.post("/exit/reset")
async def exit_button_reset():
    global exit_button
    exit_button = False
    logger.info("Exit reset")
    return{"ok":True}

@app.post("/button/exit")
async def button_exit():
    global exit_button, sim_exit_pending
    exit_button = True
    logger.info("exit button pressed")
    try:
        await _kiosk_post("/exit-kiosk", {})
    except Exception as e:
        logger.warning("kiosk-control exit failed: %s", e)
    if DEV_SIMULATE:
        if sim_exit_pending:
            sim_exit_pending = False
            asyncio.create_task(_simulate_exit_confirmed())
        else:
            sim_exit_pending = True
            asyncio.create_task(_simulate_exit_warning())
    return{"ok":True}

async def _simulate_exit_warning() -> None:
    global exit_button, current_item, sim_exit_pending
    exit_button = False
    current_item = Item(title="EXIT?", text="Press Exit again to close the GUI", screen="init")
    state_change_event.set()
    state_change_event.clear()
    await asyncio.sleep(10)
    if sim_exit_pending:
        sim_exit_pending = False
        current_item = Item(title="READY TO RUN", text='Select profile then select "Run" to start', screen="ready")
        state_change_event.set()
        state_change_event.clear()

async def _simulate_exit_confirmed() -> None:
    global exit_button, current_item
    exit_button = False
    current_item = Item(title="EXIT", text="Closing GUI...", screen="init")
    state_change_event.set()
    state_change_event.clear()
    await asyncio.sleep(3)
    current_item = Item(title="READY TO RUN", text='Select profile then select "Run" to start', screen="ready")
    state_change_event.set()
    state_change_event.clear()

@app.post("/button/exit/force")
async def button_exit_force():
    global force_exit
    force_exit = True
    logger.info("Force exit requested")
    try:
        await _kiosk_post("/exit-kiosk", {})
    except Exception as e:
        logger.warning("kiosk-control exit failed: %s", e)
    if DEV_SIMULATE:
        asyncio.create_task(_simulate_exit_confirmed())
    return {"ok": True}

@app.post("/exit/force/reset")
async def exit_force_reset():
    global force_exit
    force_exit = False
    return {"ok": True}

@app.get("/button_status")
@app.get("/button_status/")
async def button_status():
    return {
        "run_requested": run_requested,
        "profile": selected_profile,
        "run_name": run_name,
        "drawer_open_status":drawer_open,
        "drawer_close_status":drawer_close,
        "exit_button_status":exit_button,
        "force_exit": force_exit,
        "run_complete_ack": run_complete_ack,
        "stop_requested": stop_requested,
        "dev_simulate": DEV_SIMULATE
        }

@app.get("/drawer/state")
async def get_drawer_state():
    return {
        "open": drawer_state_open,
        "closed": drawer_state_closed
    }

@app.post("/drawer/state")
async def set_drawer_state(payload: dict):
    global drawer_state_open, drawer_state_closed
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Invalid payload")
    drawer_state_open = bool(payload.get("open"))
    drawer_state_closed = bool(payload.get("closed"))
    return {"ok": True}

@app.post("/profile/select")
async def select_profile(payload: ProfileSelect):
    global selected_profile
    selected_profile = payload.profile
    logger.info("Selected profile:", selected_profile)
    return {"ok":True}

@app.post("/run_status/reset")
async def run_status_reset():
    global run_requested, selected_profile
    run_requested = False
    selected_profile = None
    logger.info("Run button reset, profile reset")
    return{"ok":True}

def resolve_device_profiles() -> "set[str] | None":
    import socket
    hostname = os.getenv("DEVICE_HOSTNAME") or socket.gethostname()
    device_profiles_path = BASE_DIR / "config_files" / "device_profiles.json"
    profile_groups_path = BASE_DIR / "config_files" / "profile_groups.json"
    try:
        device_profiles = json.loads(device_profiles_path.read_text())
    except Exception:
        logger.warning("Could not load device_profiles.json; showing all profiles")
        return None
    device_entry = device_profiles.get(hostname)
    if device_entry is None:
        return None
    try:
        profile_groups = json.loads(profile_groups_path.read_text())
    except Exception:
        logger.warning("Could not load profile_groups.json; showing all profiles")
        return None
    group_name = device_entry.get("profile_group")
    group_value = profile_groups.get(group_name)
    if group_value is None:
        return None
    allowed = list(group_value)
    allowed.extend(device_entry.get("extra_profiles", []))
    return set(allowed)


def resolve_profile_editing_disabled() -> bool:
    """True when profile building (edit/new) is disabled for the running device.

    Reads the `profile_editing_disabled` flag from the device's entry in
    config_files/device_profiles.json. Fails OPEN (returns False) on unknown
    hostname, missing flag, or unreadable config so editing stays enabled by
    default — matching the fail-open behavior of resolve_device_profiles().
    """
    import socket
    hostname = os.getenv("DEVICE_HOSTNAME") or socket.gethostname()
    device_profiles_path = BASE_DIR / "config_files" / "device_profiles.json"
    try:
        device_profiles = json.loads(device_profiles_path.read_text())
    except Exception:
        logger.warning("Could not load device_profiles.json; profile editing enabled")
        return False
    device_entry = device_profiles.get(hostname)
    if not isinstance(device_entry, dict):
        return False
    return bool(device_entry.get("profile_editing_disabled", False))


@app.get("/profiles")
async def list_profiles():
    profiles = []
    profile_dir = resolve_profile_dir()
    if not profile_dir.exists():
        return profiles
    allowed = resolve_device_profiles()

    # Collect local filenames first for deduplication — local takes priority over bundled
    local_filenames: set[str] = {p.name for p in (profile_dir / "local").glob("*.json")} if (profile_dir / "local").exists() else set()

    # local/ first, then bundled/, then anything flat (dev/legacy)
    search_paths = []
    local_dir = profile_dir / "local"
    bundled_dir = profile_dir / "bundled"
    if local_dir.exists():
        search_paths.extend(sorted(local_dir.glob("*.json")))
    if bundled_dir.exists():
        search_paths.extend(sorted(bundled_dir.glob("*.json")))
    # fallback: flat files not in either subdir (dev simulate or pre-migration)
    search_paths.extend(p for p in sorted(profile_dir.glob("*.json")) if p.is_file())

    for path in search_paths:
        is_bundled = "bundled" in path.parts

        # Deduplicate: skip bundled file if a local version exists with same filename
        if is_bundled and path.name in local_filenames:
            continue

        # Device allowlist: only filter bundled profiles
        if allowed is not None and is_bundled and path.name not in allowed:
            continue

        try:
            with path.open() as f:
                data = json.load(f)
            if "post_in_gui" in data and str(data.get("post_in_gui")).lower() != "true":
                continue
        except Exception:
            logger.info("Error processing %s", path)
            continue

        if "configuration" in data and "name" in data:
            created_at = data.get("createdAt") or int(path.stat().st_ctime * 1000)
            modified_at = data.get("modifiedAt") or int(path.stat().st_mtime * 1000)
            profiles.append({
                "id": str(path.relative_to(profile_dir)),
                "name": data.get("name"),
                "label": data.get("name"),
                "bundled": is_bundled,
                "structured": "stages" in data,
                "createdAt": created_at,
                "modifiedAt": modified_at,
                "configuration": data.get("configuration", {})
            })
        else:
            created_at = int(path.stat().st_ctime * 1000)
            modified_at = int(path.stat().st_mtime * 1000)
            profiles.append({
                "id": str(path.relative_to(profile_dir)),
                "name": data.get("title", path.stem),
                "label": data.get("title", path.stem),
                "bundled": is_bundled,
                "structured": "stages" in data,
                "createdAt": created_at,
                "modifiedAt": modified_at,
                "configuration": _convert_legacy_steps_to_run_config(
                    data.get("steps", [])
                )
            })

    name_counts = {}
    for profile in profiles:
        name = profile.get("name") or profile.get("label") or profile.get("id") or "profile"
        name_counts[name] = name_counts.get(name, 0) + 1
    for profile in profiles:
        name = profile.get("name") or profile.get("label") or profile.get("id") or "profile"
        profile_id = str(profile.get("id") or "").removesuffix(".json")
        if name_counts.get(name, 0) > 1 and profile_id:
            profile["display_name"] = f"{name} ({profile_id})"
        else:
            profile["display_name"] = name
    return profiles

def _sanitize_profile_filename(name: str) -> str:
    clean = "".join(ch.lower() if ch.isalnum() else "_" for ch in name).strip("_")
    if not clean:
        clean = "profile"
    return f"{clean}.json"

def _seconds_to_duration(seconds: int | float | None) -> str:
    if seconds is None:
        return "00:00:00"
    total = int(round(float(seconds)))
    hrs = total // 3600
    mins = (total % 3600) // 60
    secs = total % 60
    return f"{hrs:02d}:{mins:02d}:{secs:02d}"

def _duration_to_seconds(value: str | None) -> int:
    if not value:
        return 0
    parts = value.split(":")
    if len(parts) != 3:
        return 0
    try:
        hrs, mins, secs = [int(part) for part in parts]
    except ValueError:
        return 0
    return hrs * 3600 + mins * 60 + secs

def _convert_legacy_steps_to_run_config(steps: list) -> dict:
    stages = []
    stage_index = 1

    for step in steps:
        if not isinstance(step, dict):
            continue
        if isinstance(step.get("repeat"), list):
            repeat_steps = []
            step_index = 1
            for repeat_step in step.get("repeat", []):
                if not isinstance(repeat_step, dict):
                    continue
                if "setpoint" not in repeat_step:
                    continue
                repeat_steps.append({
                    "id": f"stage-{stage_index}-step-{step_index}",
                    "sequenceNumber": step_index,
                    "temperature": repeat_step.get("setpoint"),
                    "duration": _seconds_to_duration(repeat_step.get("duration"))
                })
                step_index += 1
            if repeat_steps:
                stages.append({
                    "id": f"stage-{stage_index}",
                    "name": f"STAGE {stage_index}",
                    "sequenceNumber": stage_index,
                    "multiplier": int(step.get("cycles", 1) or 1),
                    "steps": repeat_steps
                })
                stage_index += 1
            continue

        if "setpoint" in step:
            stages.append({
                "id": f"stage-{stage_index}",
                "name": f"STAGE {stage_index}",
                "sequenceNumber": stage_index,
                "multiplier": 1,
                "steps": [{
                    "id": f"stage-{stage_index}-step-1",
                    "sequenceNumber": 1,
                    "temperature": step.get("setpoint"),
                    "duration": _seconds_to_duration(step.get("duration"))
                }]
            })
            stage_index += 1

    return {
        "stages": stages
    }

def _convert_run_config_to_steps(configuration: dict) -> list:
    steps = []
    for stage in configuration.get("stages", []) or []:
        stage_steps = []
        for step in stage.get("steps", []) or []:
            stage_steps.append({
                "setpoint": step.get("temperature"),
                "duration": _duration_to_seconds(step.get("duration"))
            })
        multiplier = int(stage.get("multiplier") or 1)
        if stage_steps and multiplier > 1:
            steps.append({"repeat": stage_steps, "cycles": multiplier})
        else:
            steps.extend(stage_steps)
    return steps

@app.post("/profiles")
async def save_profile(payload: ProfileSave):
    profile_dir = resolve_profile_dir()
    profile_dir.mkdir(parents=True, exist_ok=True)
    def sanitize_name(value: str) -> str:
        sanitized = re.sub(r"[^a-zA-Z0-9_-]+", "_", value).strip("_")
        return sanitized or "profile"

    profile_path = None
    original_profile_path = None
    if payload.profile_id:
        profile_path = profile_dir / payload.profile_id
        if not profile_path.name.endswith(".json"):
            profile_path = profile_path.with_suffix(".json")
        if "bundled" in profile_path.parts:
            raise HTTPException(status_code=403, detail="Bundled profiles are read-only.")

    base_profile = None
    if profile_path and profile_path.exists():
        try:
            with profile_path.open() as f:
                base_profile = json.load(f)
            original_profile_path = profile_path
        except Exception:
            raise HTTPException(status_code=400, detail="Failed to read existing profile")
    else:
        template_path = profile_dir / "acorn_pcr_profile.json"
        if template_path.exists():
            with template_path.open() as f:
                base_profile = json.load(f)
        else:
            base_profile = {"output_dir": "pcr_data", "steps": []}

    requested_title = payload.name.strip() if payload.name else ""
    base_profile["title"] = requested_title or payload.name
    base_profile["post_in_gui"] = "True"
    if payload.steps is not None:
        base_profile["steps"] = payload.steps
    # Structured Profile (issue #201): validate the stages, then regenerate steps
    # from them (stages is the source of truth; any client-sent steps is ignored).
    # validate_stages runs first so assemble_steps only ever sees valid input.
    if payload.stages is not None:
        stage_errors = validate_stages(payload.stages)
        if stage_errors:
            raise HTTPException(status_code=400, detail={"errors": stage_errors})
        base_profile["stages"] = payload.stages
        base_profile["steps"] = assemble_steps(payload.stages)
    labels = {}
    if isinstance(base_profile.get("labels"), dict):
        labels.update(base_profile.get("labels", {}))
    if payload.fam_label is not None:
        labels["fam"] = payload.fam_label
    if payload.rox_label is not None:
        labels["rox"] = payload.rox_label
    if labels:
        base_profile["labels"] = labels

    # Estimated completion time. The JSON always carries both (time_unavailable
    # mirrors the rox_unavailable convention — True means no estimate is set):
    #   time_unavailable              -> bool, True when NO estimate is set
    #   estimated_completion_seconds  -> int seconds when set, else None
    # When the caller sends the field we use it; when omitted we keep whatever the
    # existing profile already had. Either way both keys are always written.
    fields_set = getattr(payload, "model_fields_set", None) or getattr(payload, "__fields_set__", set())
    if "estimated_minutes" in fields_set:
        estimate_seconds = estimated_minutes_to_seconds(payload.estimated_minutes)
    else:
        existing = base_profile.get("estimated_completion_seconds")
        estimate_seconds = existing if (
            isinstance(existing, (int, float))
            and not isinstance(existing, bool)
            and existing > 0
        ) else None
    base_profile["time_unavailable"] = estimate_seconds is None
    base_profile["estimated_completion_seconds"] = estimate_seconds

    if not profile_path:
        local_dir = profile_dir / "local"
        local_dir.mkdir(parents=True, exist_ok=True)
        file_name = sanitize_name(payload.name)
        profile_path = local_dir / f"{file_name}.json"
        if profile_path.exists():
            profile_path = local_dir / f"{file_name}_{int(datetime.now().timestamp())}.json"
    elif requested_title:
        sanitized_title = sanitize_name(requested_title)
        if sanitized_title and profile_path.stem != sanitized_title:
            # Rename within the profile's own directory (e.g. local/) rather than
            # the profiles root, so editing+renaming doesn't relocate the file (#218 review).
            rename_dir = profile_path.parent
            candidate_path = rename_dir / f"{sanitized_title}.json"
            if candidate_path.exists() and candidate_path != profile_path:
                candidate_path = rename_dir / f"{sanitized_title}_{int(datetime.now().timestamp())}.json"
            profile_path = candidate_path

    # Structured profiles (issue #213) get the full canonical key order; legacy
    # steps-based saves keep the narrower time-field ordering unchanged.
    if "stages" in base_profile:
        base_profile = _order_profile_keys(base_profile)
    else:
        base_profile = _order_time_fields(base_profile)

    # Serialize first with allow_nan=False so a non-finite value (NaN/Infinity)
    # anywhere — including a disabled stage that validation skips — fails loudly
    # with a 400 instead of writing invalid JSON that 500s on every later read.
    # Serializing before opening the file also prevents truncating an existing
    # profile when re-saving an edit that turns out to be invalid.
    try:
        profile_text = json.dumps(base_profile, indent=2, allow_nan=False)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail={"errors": ["Profile contains non-finite numeric values (NaN/Infinity)."]},
        )
    try:
        with profile_path.open("w") as f:
            f.write(profile_text)
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to save profile")

    if original_profile_path and original_profile_path != profile_path:
        try:
            original_profile_path.unlink(missing_ok=True)
        except Exception:
            logger.warning("Failed to remove old profile %s", original_profile_path)

    return {"ok": True, "id": str(profile_path.relative_to(profile_dir))}

@app.post("/profiles/delete")
async def delete_profiles(payload: ProfileDelete):
    profile_dir = resolve_profile_dir()
    deleted = []
    missing = []

    for profile_id in payload.profiles:
        if not profile_id:
            continue
        # profile_id may be a relative path like "local/foo.json" or just "foo.json"
        candidate = profile_dir / profile_id
        if candidate.suffix != ".json":
            candidate = candidate.with_suffix(".json")
        # Reject attempts to delete bundled profiles
        if "bundled" in candidate.parts:
            raise HTTPException(status_code=403, detail="Bundled profiles cannot be deleted.")
        safe_name = candidate.name
        profile_path = candidate
        if not profile_path.exists():
            # fallback: check local/ subdir
            profile_path = profile_dir / "local" / safe_name
        if not profile_path.exists():
            missing.append(safe_name)
            continue
        try:
            profile_path.unlink()
            deleted.append(safe_name)
        except Exception:
            missing.append(safe_name)

    return {"ok": True, "deleted": deleted, "missing": missing}

@app.get("/profiles/details")
async def profile_details(id: str | None = Query(default=None), name: str | None = Query(default=None)):
    if not id and not name:
        raise HTTPException(status_code=400, detail="id or name is required")

    profile_dir = resolve_profile_dir()
    profile_dir.mkdir(parents=True, exist_ok=True)
    profile_path = None

    if id:
        profile_path = profile_dir / id
        if not profile_path.exists():
            raise HTTPException(status_code=404, detail="Profile not found")
    else:
        for path in profile_dir.glob("*.json"):
            try:
                with path.open() as f:
                    data = json.load(f)
                title = data.get("title", path.stem)
                profile_name = data.get("name", title)
                if profile_name == name or path.stem == name:
                    profile_path = path
                    break
            except Exception:
                continue
        if profile_path is None:
            raise HTTPException(status_code=404, detail="Profile not found")

    with profile_path.open() as f:
        data = json.load(f)

    if "configuration" in data and "name" in data:
        return {
            "id": profile_path.name,
            "title": data.get("name"),
            "labels": data.get("labels", {}),
            "rox_unavailable": bool(data.get("rox_unavailable", False)),
            "time_unavailable": bool(data.get("time_unavailable", data.get("estimated_completion_seconds") is None)),
            "estimated_completion_seconds": data.get("estimated_completion_seconds"),
            "steps": _convert_run_config_to_steps(data.get("configuration", {}))
        }

    details = {
        "id": profile_path.name,
        "title": data.get("title", profile_path.stem),
        "labels": data.get("labels", {}),
        "rox_unavailable": bool(data.get("rox_unavailable", False)),
        "time_unavailable": bool(data.get("time_unavailable", data.get("estimated_completion_seconds") is None)),
        "estimated_completion_seconds": data.get("estimated_completion_seconds"),
        "steps": data.get("steps", [])
    }
    # Structured Profiles carry the `stages` source of truth; Legacy Profiles
    # omit it entirely so the editor can branch on its presence (issue #197).
    if data.get("stages") is not None:
        details["stages"] = data["stages"]
    return details

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    logger.info ( "Websocket started" )
    await websocket.accept( )
    #await websocket.send_json( current_item.dict() )
    logger.info ( "Websocket accepted" )
    
    try:
        while True:
            panel_with_timer = current_item.dict()
            if timer_running and start_time:
                panel_with_timer["elapsed"] = int((datetime.now() - start_time).total_seconds())
            else:
                panel_with_timer["elapsed"] = int(elapsed_time)

            panel_with_timer["drawer_state_open"] = drawer_state_open
            panel_with_timer["drawer_state_closed"] = drawer_state_closed

            #await state_change_event.wait()
            #logger.info ( "Submitted state", current_item.dict() )
            await websocket.send_json( panel_with_timer )
            await asyncio.sleep(1)
            #logger.info ( "Sent" )
    except Exception as e:
        logger.warning("websocket failed") 

    logger.info ( "Websocket ended" )

# ---------------------------------------------------------------------------
# WiFi — proxy to kiosk-control host service
# ---------------------------------------------------------------------------

KIOSK_CONTROL_URL = os.getenv("KIOSK_CONTROL_URL", "http://127.0.0.1:9191")

import httpx

async def _kiosk_get(path: str) -> dict:
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(f"{KIOSK_CONTROL_URL}{path}")
        return r.json()

async def _kiosk_post(path: str, body: dict) -> dict:
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(f"{KIOSK_CONTROL_URL}{path}", json=body)
        return r.json()

@app.get("/wifi")
async def wifi_page():
    # Wi-Fi UI now lives under Settings (ADR-012). Keep /wifi working for any
    # old bookmark/deep link by redirecting to the consolidated page.
    return RedirectResponse(url="/settings")

@app.get("/wifi/status")
async def wifi_status():
    try:
        return await _kiosk_get("/wifi/status")
    except Exception as e:
        return {"connected": False, "ssid": None, "signal": None, "error": str(e)}

@app.get("/wifi/scan")
async def wifi_scan():
    try:
        return await _kiosk_get("/wifi/scan")
    except Exception as e:
        return {"networks": [], "error": str(e)}

class WifiConnect(BaseModel):
    ssid: str
    password: str = ""

@app.post("/wifi/connect")
async def wifi_connect(body: WifiConnect):
    try:
        return await _kiosk_post("/wifi/connect", {"ssid": body.ssid, "password": body.password})
    except Exception as e:
        return {"ok": False, "error": str(e)}

class WifiForget(BaseModel):
    ssid: str

@app.post("/wifi/forget")
async def wifi_forget(body: WifiForget):
    try:
        return await _kiosk_post("/wifi/forget", {"ssid": body.ssid})
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.get("/wifi/saved")
async def wifi_saved():
    try:
        return await _kiosk_get("/wifi/saved")
    except Exception as e:
        return {"profiles": [], "error": str(e)}


# ---------------------------------------------------------------------------
# OTA Update — manual approval flow
# ---------------------------------------------------------------------------

import base64

WATCHTOWER_URL = os.getenv("WATCHTOWER_URL", "http://aquila-watchtower:8080")
WATCHTOWER_TOKEN = os.getenv("WATCHTOWER_HTTP_API_TOKEN", "")
_OTA_GHCR_USER = os.getenv("GHCR_USERNAME", "")
_OTA_GHCR_TOKEN = os.getenv("GHCR_TOKEN", "")
_OTA_GHCR_BASE = os.getenv("GHCR_REPO", "acorngenetics/aquilla-main")
_OTA_GHCR_REPO_API = _OTA_GHCR_BASE + "-api"
_OTA_GHCR_REPO_UI  = _OTA_GHCR_BASE + "-ui"
_OTA_IMAGE_TAG = os.getenv("IMAGE_TAG", "")   # dev | pilot | prod — set by device.env
_OTA_POLL_INTERVAL = int(os.getenv("UPDATE_CHECK_INTERVAL", "300"))  # seconds

_update_available: bool = False
_update_dismissed: bool = False
_update_status: str = "idle"   # idle | checking | available | updating | error
_update_error: str | None = None
_update_last_checked: str | None = None
# Digests of the images actually running — injected at deploy time via env vars.
# Fall back to the first GHCR poll result if not set.
_startup_image_digest: str | None = os.getenv("RUNNING_IMAGE_DIGEST") or None
_startup_image_digest_ui: str | None = os.getenv("RUNNING_IMAGE_DIGEST_UI") or None
_latest_ghcr_digest: str | None = None
_latest_ghcr_digest_ui: str | None = None

# --- OTA auto-reboot completion sentinel (issue #183, ADR-018) ----------------
from aquila_web import update_sentinel as _sentinel

# Lives on the /opt/fleet host volume so it survives the container swap + reboot.
_UPDATE_SENTINEL_PATH = os.getenv("AQ_UPDATE_SENTINEL_PATH", "/opt/fleet/last_update.json")
# Short TTL: a sentinel older than this is stale and must not pop a modal.
_UPDATE_SENTINEL_TTL = int(os.getenv("AQ_UPDATE_SENTINEL_TTL", "600"))


def _utcnow_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _trigger_host_reboot() -> bool:
    """Best-effort: ask the host kiosk-control service to reboot the device.

    Synchronous + swallows errors: the process is about to die anyway, and a
    failure must not crash startup (it degrades to 'modal on next manual reset').
    """
    try:
        headers = {"Authorization": f"Bearer {WATCHTOWER_TOKEN}"} if WATCHTOWER_TOKEN else {}
        with httpx.Client(timeout=10.0) as client:
            client.post(f"{KIOSK_CONTROL_URL}/reboot", json={}, headers=headers)
        return True
    except Exception as e:  # noqa: BLE001 - never let a reboot failure crash boot
        logger.warning("host reboot request failed: %s", e)
        return False


def _resolve_startup_update_state() -> None:
    """On boot, advance the update sentinel state machine.

    reboot_pending -> persist show_complete, then reboot the host (once).
    show_complete  -> surface the completion modal (_update_status = 'complete').
    none/stale     -> clear the sentinel.
    """
    global _update_status
    record = _sentinel.read_sentinel(_UPDATE_SENTINEL_PATH)
    action = _sentinel.next_startup_action(record, datetime.utcnow(), _UPDATE_SENTINEL_TTL)
    if action == "reboot":
        # Don't reboot mid-run; a fresh post-update boot has no active run anyway.
        if current_item.screen == "running":
            return
        _sentinel.write_sentinel(_UPDATE_SENTINEL_PATH, "show_complete", _utcnow_iso())
        _update_status = "updating"
        _trigger_host_reboot()
    elif action == "show_complete":
        _update_status = "complete"
    else:
        _sentinel.clear_sentinel(_UPDATE_SENTINEL_PATH)
# ------------------------------------------------------------------------------


async def _ghcr_bearer_token(user: str, token: str, repo: str) -> str | None:
    """Exchange Basic credentials for a short-lived GHCR Bearer token."""
    cred = base64.b64encode(f"{user}:{token}".encode()).decode()
    owner = repo.split("/")[0]
    name = "/".join(repo.split("/")[1:]) or repo
    url = f"https://ghcr.io/token?service=ghcr.io&scope=repository:{owner}/{name}:pull"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(url, headers={"Authorization": f"Basic {cred}"})
        if r.status_code == 200:
            return r.json().get("token")
    except Exception:
        pass
    return None


async def _ghcr_manifest_digest(repo: str, tag: str, user: str, token: str) -> str | None:
    """Return the manifest digest for a GHCR image tag without pulling it."""
    bearer = await _ghcr_bearer_token(user, token, repo)
    if bearer is None:
        return None
    owner = repo.split("/")[0]
    name = "/".join(repo.split("/")[1:]) or repo
    url = f"https://ghcr.io/v2/{owner}/{name}/manifests/{tag}"
    headers = {
        "Authorization": f"Bearer {bearer}",
        "Accept": (
            "application/vnd.oci.image.index.v1+json,"
            "application/vnd.docker.distribution.manifest.list.v2+json,"
            "application/vnd.docker.distribution.manifest.v2+json"
        ),
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.head(url, headers=headers, follow_redirects=True)
        return r.headers.get("docker-content-digest")
    except Exception:
        return None


async def _do_check_update() -> None:
    global _update_available, _update_status, _update_error, _update_last_checked
    global _startup_image_digest, _startup_image_digest_ui, _latest_ghcr_digest, _latest_ghcr_digest_ui
    _update_status = "checking"
    try:
        if not _OTA_GHCR_TOKEN or not _OTA_IMAGE_TAG:
            _update_status = "idle"
            _update_error = "Registry credentials or IMAGE_TAG not configured"
            return
        latest_api, latest_ui = await asyncio.gather(
            _ghcr_manifest_digest(_OTA_GHCR_REPO_API, _OTA_IMAGE_TAG, _OTA_GHCR_USER, _OTA_GHCR_TOKEN),
            _ghcr_manifest_digest(_OTA_GHCR_REPO_UI,  _OTA_IMAGE_TAG, _OTA_GHCR_USER, _OTA_GHCR_TOKEN),
        )
        _update_last_checked = datetime.utcnow().isoformat() + "Z"
        if latest_api is None and latest_ui is None:
            _update_status = "idle"
            _update_error = "Registry unreachable or credentials invalid"
            return
        if latest_api is not None:
            _latest_ghcr_digest = latest_api
        if latest_ui is not None:
            _latest_ghcr_digest_ui = latest_ui
        if _startup_image_digest is None:
            _startup_image_digest = latest_api
        if _startup_image_digest_ui is None:
            _startup_image_digest_ui = latest_ui
        api_changed = latest_api is not None and latest_api != _startup_image_digest
        ui_changed  = latest_ui  is not None and latest_ui  != _startup_image_digest_ui
        if api_changed or ui_changed:
            _update_available = True
            _update_status = "available"
        else:
            _update_available = False
            _update_status = "idle"
        _update_error = None
    except Exception as e:
        _update_status = "error"
        _update_error = str(e)


@app.get("/update/status")
async def get_update_status():
    available = _update_available
    status = _update_status
    # Dev simulation (AQ_DEV_UPDATE_AVAILABLE): force an available update so the
    # nav badge, the Updates sub-tab dot, and the apply-flow can be exercised
    # locally without real registry credentials. Honours dismissal, and
    # /update/reset clears the dismissal — so the full lifecycle stays testable.
    if DEV_UPDATE_AVAILABLE and not _update_dismissed:
        available = True
        status = "available"
    return {
        "available": available,
        "dismissed": _update_dismissed,
        "status": status,
        "error": _update_error,
        "last_checked": _update_last_checked,
    }


@app.post("/update/check")
async def trigger_update_check():
    if not _OTA_GHCR_TOKEN or not _OTA_IMAGE_TAG:
        return {"ok": False, "error": "Registry credentials or IMAGE_TAG not configured"}
    asyncio.create_task(_do_check_update())
    return {"ok": True, "message": "checking"}


@app.post("/update/apply")
async def apply_update():
    global _update_status, _update_error, _startup_image_digest, _startup_image_digest_ui, _update_available
    if current_item.screen == "running":
        return JSONResponse(
            status_code=409,
            content={"ok": False, "error": "Cannot update during an active run. Stop the run first."},
        )
    # Breadcrumb the new container reads on startup to drive the auto-reboot (#183).
    # Written before triggering Watchtower so a kill mid-swap still leaves it behind.
    try:
        _sentinel.write_sentinel(_UPDATE_SENTINEL_PATH, "reboot_pending", _utcnow_iso())
    except OSError:
        logger.warning("could not write update sentinel at %s", _UPDATE_SENTINEL_PATH)
    _update_status = "updating"
    headers = {"Authorization": f"Bearer {WATCHTOWER_TOKEN}"} if WATCHTOWER_TOKEN else {}
    try:
        # Write new digests to /opt/fleet/.env before triggering Watchtower so the
        # restarted container picks up the correct baseline even if we are killed mid-restart.
        _fleet_env = "/opt/fleet/.env"
        if (_latest_ghcr_digest or _latest_ghcr_digest_ui) and os.path.exists(_fleet_env):
            try:
                with open(_fleet_env, "r") as f:
                    lines = f.readlines()
                updated = []
                for line in lines:
                    if line.startswith("RUNNING_IMAGE_DIGEST=") and not line.startswith("RUNNING_IMAGE_DIGEST_UI=") and _latest_ghcr_digest:
                        updated.append(f"RUNNING_IMAGE_DIGEST={_latest_ghcr_digest}\n")
                    elif line.startswith("RUNNING_IMAGE_DIGEST_UI=") and _latest_ghcr_digest_ui:
                        updated.append(f"RUNNING_IMAGE_DIGEST_UI={_latest_ghcr_digest_ui}\n")
                    else:
                        updated.append(line)
                with open(_fleet_env, "w") as f:
                    f.writelines(updated)
            except OSError:
                pass
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(f"{WATCHTOWER_URL}/v1/update", headers=headers)
        if r.status_code == 200:
            if _latest_ghcr_digest:
                _startup_image_digest = _latest_ghcr_digest
            if _latest_ghcr_digest_ui:
                _startup_image_digest_ui = _latest_ghcr_digest_ui
            _update_available = False
            _update_status = "updating"
            # If containers don't restart (nothing to update), the in-memory status
            # would stay "updating" until the next 5-min poller tick. Schedule a
            # check after 3 minutes so the UI gets a timely resolution either way.
            async def _deferred_status_reset() -> None:
                await asyncio.sleep(180)
                if _update_status == "updating":
                    await _do_check_update()
            asyncio.create_task(_deferred_status_reset())
            return {"ok": True, "message": "Update triggered — containers will restart shortly."}
        _update_status = "error"
        _update_error = f"Watchtower returned HTTP {r.status_code}"
        return {"ok": False, "error": _update_error}
    except Exception as e:
        _update_status = "error"
        _update_error = str(e)
        return {"ok": False, "error": str(e)}


@app.post("/update/dismiss")
async def dismiss_update():
    global _update_dismissed
    _update_dismissed = True
    return {"ok": True}


@app.post("/update/reset")
async def reset_update_state():
    """Test/dev helper — resets all update state."""
    global _update_available, _update_dismissed, _update_status, _update_error
    global _update_last_checked, _startup_image_digest, _startup_image_digest_ui
    _update_available = False
    _update_dismissed = False
    _update_status = "idle"
    _update_error = None
    _update_last_checked = None
    _startup_image_digest = None
    _startup_image_digest_ui = None
    return {"ok": True}


@app.post("/update/ack-complete")
async def ack_update_complete():
    """Operator dismissed the 'Update Complete' modal. Fire-once: clear sentinel."""
    global _update_status
    _sentinel.clear_sentinel(_UPDATE_SENTINEL_PATH)
    if _update_status == "complete":
        _update_status = "idle"
    return {"ok": True}


@app.post("/reboot")
async def reboot_device():
    """Proxy a host reboot request to the kiosk-control service."""
    ok = _trigger_host_reboot()
    return {"ok": ok}


async def _background_update_poller() -> None:
    """Poll GHCR every UPDATE_CHECK_INTERVAL seconds. Never pulls the image."""
    while True:
        if _OTA_GHCR_TOKEN and _OTA_IMAGE_TAG:
            await _do_check_update()
        await asyncio.sleep(_OTA_POLL_INTERVAL)


_SYNC_INTERVAL_SECONDS = int(os.getenv("AQ_SYNC_INTERVAL_SECONDS", "900"))


async def _background_sync_poller() -> None:
    """Flush SQLite event queue to AWS ingest endpoint every AQ_SYNC_INTERVAL_SECONDS."""
    while True:
        await asyncio.sleep(_SYNC_INTERVAL_SECONDS)
        try:
            from aquila_web.sync import sync_pending_events
            sync_pending_events()
        except Exception as exc:
            logger.warning("Background sync error: %s", exc)


@app.post("/sync/flush")
async def sync_flush():
    from aquila_web.sync import sync_pending_events
    synced = sync_pending_events()
    return {"synced": synced}


@app.on_event("startup")
async def _inject_device_id() -> None:
    inject_hw_serial_env()


@app.on_event("startup")
async def _inject_device_id() -> None:
    inject_hw_serial_env()


@app.on_event("startup")
async def resolve_update_completion() -> None:
    """On boot, advance the OTA sentinel: reboot if an update just applied, or
    surface the 'Update Complete' state if we just came back from that reboot (#183)."""
    try:
        _resolve_startup_update_state()
    except Exception as e:  # noqa: BLE001 - never block startup on this
        logger.warning("update sentinel resolution failed: %s", e)


@app.on_event("startup")
async def start_background_update_poller() -> None:
    asyncio.create_task(_background_update_poller())


@app.on_event("startup")
async def start_background_sync_poller() -> None:
    asyncio.create_task(_background_sync_poller())
