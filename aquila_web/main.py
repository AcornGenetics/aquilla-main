from fastapi import FastAPI, Form, Body, HTTPException, Query
from fastapi.responses import FileResponse, RedirectResponse
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
from aq_curve.curve import Curve

logger = logging.getLogger( __name__ )
logger.setLevel("WARNING")

app = FastAPI()
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

PLOTS_DIR.mkdir(parents=True, exist_ok=True)
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
    for path in profile_dir.glob("*.json"):
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

profile_dir = resolve_profile_dir()
run_requested = False
selected_profile = None
run_name = "run1"
run_counter = 1
drawer_open = False
drawer_close = False
exit_button = False
run_complete_ack = False
drawer_task = None
drawer_state_open = False
drawer_state_closed = False

class Item(BaseModel):
    title: str = "Arete Biosciences"
    text: str = "Cubit"
    screen: str = "init"

class TimerControl(BaseModel):
    action: str

class ProfileSelect(BaseModel):
    profile: str 

class ProfileSave(BaseModel):
    name: str
    chemistry: Optional[str] = None
    volume: Optional[str] = None
    profile_id: Optional[str] = None
    steps: Optional[list] = None
    fam_label: Optional[str] = None
    rox_label: Optional[str] = None

class ProfileDelete(BaseModel):
    profiles: list[str]

class ResultPath(BaseModel):
    path: str

current_item = Item( title = "title_bm", text = "text_bm", screen="init" )
#start_time = datetime.now()

def _sanitize_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_") or "run"

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
                elif value and value != "Not Detected":
                    try:
                        detected.add(int(col))
                    except ValueError:
                        continue
    detected -= inconclusive
    return _summarize_results(sorted(detected), sorted(inconclusive))

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

    run_in_progress = True
    run_complete_ack = False
    start_time = datetime.now()
    elapsed_time = 0
    timer_running = True
    current_item.screen = "running"
    state_change_event.set()
    state_change_event.clear()

    await asyncio.sleep(SIM_RUN_SECONDS)

    timer_running = False
    elapsed_time = SIM_RUN_SECONDS
    profile_slug = _sanitize_name(profile_name)
    run_slug = _sanitize_name(run_name)
    run_index = _next_run_index(profile_slug)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    results_file = RESULTS_DIR / f"{profile_slug}_{run_slug}.json"
    plot_filename = _plot_filename(profile_slug, run_slug)
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
    curve_runner = Curve(src_basedir=str(RESULTS_DIR))
    curve_runner.results_to_json(str(optics_path), results_file.name)
    PLOTS_DIR.mkdir(parents=True, exist_ok=True)
    labels = _load_profile_labels(profile_name)
    generate_optics_plot(str(optics_path), str(plot_path), labels=labels)
    detected_summary = _summarize_results_from_file(results_file)

    results_path = str(results_file.resolve())
    results_cleared = False

    history = _load_history()
    history.append({
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "profile": profile_name,
        "run_name": run_name,
        "result": detected_summary,
        "graph_path": f"/plots/{plot_filename}",
        "results_path": results_path,
        "labels": labels
    })
    _save_history(history)

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
    global current_item, start_time
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
    global results_path, results_cleared
    results_path = None
    results_cleared = True
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

@app.get("/results/get_path")
async def get_path():
    return {"path":results_path}

@app.get("/results/status")
async def get_results_status():
    return {"cleared": results_cleared}

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

@app.get("/dev/optics_path")
async def get_dev_optics_path():
    return {"path": dev_optics_path}

@app.post("/dev/optics_path")
async def set_dev_optics_path(payload: dict):
    global dev_optics_path
    path = payload.get("path") if isinstance(payload, dict) else None
    dev_optics_path = path.strip() if path else None
    return {"path": dev_optics_path}

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
    profile = payload.get("profile") or "--"
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
    history.append({
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "profile": profile,
        "run_name": run_label,
        "result": result_text,
        "graph_path": graph_path,
        "results_path": path_value
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

@app.get("/history")
async def history_page():
    return FileResponse(static_dir / "history.html")

@app.get("/history/run")
async def history_run_page():
    return FileResponse(static_dir / "history_detail.html")

@app.get("/help")
async def help_page():
    return FileResponse(static_dir / "help.html")

@app.post("/button/open")
async def button_open():
    global drawer_open, drawer_close, drawer_task
    if DEV_SIMULATE:
        if drawer_task and not drawer_task.done():
            drawer_task.cancel()
        drawer_task = asyncio.create_task(_simulate_drawer("open"))
    else:
        drawer_open = True
        drawer_close = False
    logger.info("Drawer open pressed")
    return{"ok":True}

@app.post("/button/close")
async def button_close():
    global drawer_open, drawer_close, drawer_task
    if DEV_SIMULATE:
        if drawer_task and not drawer_task.done():
            drawer_task.cancel()
        drawer_task = asyncio.create_task(_simulate_drawer("close"))
    else:
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
    global run_requested
    run_requested = True
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

@app.post("/exit/reset")
async def exit_button_reset():
    global exit_button
    exit_button = False
    logger.info("Exit reset")
    return{"ok":True}

@app.post("/button/exit")
async def button_exit():
    global exit_button
    exit_button = True
    logger.info("exit button pressed")
    return{"ok":True}

@app.get("/button_status")
async def button_status():
    return {
        "run_requested": run_requested,
        "profile": selected_profile,
        "run_name": run_name,
        "drawer_open_status":drawer_open,
        "drawer_close_status":drawer_close,
        "exit_button_status":exit_button,
        "run_complete_ack": run_complete_ack,
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

@app.get("/profiles")
async def list_profiles():
    profiles = []
    profile_dir = resolve_profile_dir()
    if not profile_dir.exists():
        return profiles
    for path in profile_dir.glob("*.json"):
        try:
            with path.open() as f:
                data = json.load(f)
            if "post_in_gui" in data and str(data.get("post_in_gui")).lower() != "true":
                continue
        except Exception as e:
            logger.info("Error processing %s"%(path))

        if "configuration" in data and "name" in data:
            created_at = data.get("createdAt") or int(path.stat().st_ctime * 1000)
            modified_at = data.get("modifiedAt") or int(path.stat().st_mtime * 1000)
            profiles.append({
                "id": data.get("id", path.name),
                "name": data.get("name"),
                "label": data.get("name"),
                "createdAt": created_at,
                "modifiedAt": modified_at,
                "configuration": data.get("configuration", {})
            })
        else:
            created_at = int(path.stat().st_ctime * 1000)
            modified_at = int(path.stat().st_mtime * 1000)
            profiles.append({
                "id": path.name,
                "name": data.get("title", path.stem),
                "label": data.get("title", path.stem),
                "createdAt": created_at,
                "modifiedAt": modified_at,
                "configuration": _convert_legacy_steps_to_run_config(
                    data.get("steps", []),
                    data.get("chemistry"),
                    data.get("volume")
                )
            })
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

def _convert_legacy_steps_to_run_config(steps: list, chemistry: str | None, volume: str | None) -> dict:
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

    volume_value = 0
    if volume not in (None, ""):
        try:
            volume_value = float(volume)
        except (TypeError, ValueError):
            volume_value = 0

    return {
        "chemistry": chemistry or "",
        "volume": volume_value,
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
    if payload.profile_id:
        profile_path = profile_dir / payload.profile_id
        if not profile_path.name.endswith(".json"):
            profile_path = profile_path.with_suffix(".json")

    base_profile = None
    if profile_path and profile_path.exists():
        try:
            with profile_path.open() as f:
                base_profile = json.load(f)
        except Exception:
            raise HTTPException(status_code=400, detail="Failed to read existing profile")
    else:
        template_path = profile_dir / "acorn_pcr_profile.json"
        if template_path.exists():
            with template_path.open() as f:
                base_profile = json.load(f)
        else:
            base_profile = {"output_dir": "pcr_data", "steps": []}

    base_profile["title"] = payload.name
    base_profile["post_in_gui"] = "True"
    if payload.chemistry is not None:
        base_profile["chemistry"] = payload.chemistry
    if payload.volume is not None:
        base_profile["volume"] = payload.volume
    if payload.steps is not None:
        base_profile["steps"] = payload.steps
    labels = {}
    if isinstance(base_profile.get("labels"), dict):
        labels.update(base_profile.get("labels", {}))
    if payload.fam_label is not None:
        labels["fam"] = payload.fam_label
    if payload.rox_label is not None:
        labels["rox"] = payload.rox_label
    if labels:
        base_profile["labels"] = labels

    if not profile_path:
        file_name = sanitize_name(payload.name)
        profile_path = profile_dir / f"{file_name}.json"
        if profile_path.exists():
            profile_path = profile_dir / f"{file_name}_{int(datetime.now().timestamp())}.json"

    try:
        with profile_path.open("w") as f:
            json.dump(base_profile, f, indent=2)
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to save profile")

    return {"ok": True, "id": profile_path.name}

@app.post("/profiles/delete")
async def delete_profiles(payload: ProfileDelete):
    profile_dir = resolve_profile_dir()
    deleted = []
    missing = []

    for profile_id in payload.profiles:
        if not profile_id:
            continue
        safe_name = Path(profile_id).name
        profile_path = profile_dir / safe_name
        if profile_path.suffix != ".json":
            profile_path = profile_path.with_suffix(".json")
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
            "id": data.get("id", profile_path.name),
            "title": data.get("name"),
            "chemistry": data.get("configuration", {}).get("chemistry"),
            "volume": data.get("configuration", {}).get("volume"),
            "labels": data.get("labels", {}),
            "steps": _convert_run_config_to_steps(data.get("configuration", {}))
        }

    return {
        "id": profile_path.name,
        "title": data.get("title", profile_path.stem),
        "chemistry": data.get("chemistry"),
        "volume": data.get("volume"),
        "labels": data.get("labels", {}),
        "steps": data.get("steps", [])
    }

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
from aq_curve.main import results_to_json
from aq_lib.plot_utils import generate_optics_plot
