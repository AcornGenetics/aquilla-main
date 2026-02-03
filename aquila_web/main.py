from fastapi import FastAPI, Form, Body
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from fastapi import WebSocket
import asyncio
import logging
from datetime import datetime
from pydantic import BaseModel
import json

logger = logging.getLogger( __name__ )
logger.setLevel("WARNING")

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")

state_change_event = asyncio.Event()
start_time = None
elapsed_time = 0
timer_running = None
#results_path = Path("/home/pi/aquila/aquila_web/results.json")
results_path = None
profile_dir = Path("/home/pi/aquila/profiles/")
run_requested = False
selected_profile = None
drawer_open = False
drawer_close = False
exit_button = False

class Item(BaseModel):
    title: str = "Arete Biosciences"
    text: str = "Cubit"
    screen: str = "init"

class TimerControl(BaseModel):
    action: str

class ProfileSelect(BaseModel):
    profile: str 

class ResultPath(BaseModel):
    path: str

current_item = Item( title = "title_bm", text = "text_bm", screen="init" )
#start_time = datetime.now()

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


@app.get("/results")
async def get_results():
    try:    
        path = Path(results_path)
        with path.open() as f:
            data = json.load(f)
    except Exception as e:
        return {
                "path": str(results_path),
                "data":{"failed"}
                }
    return data

@app.post("/results/path")
async def set_path(payload: ResultPath):
    global results_path
    results_path = payload.path
    logger.info("Selected path:", results_path)
    return {"ok":True}

@app.get("/results/get_path")
async def get_path():
    return {"path":results_path}

@app.get("/")
async def index():
    return FileResponse("static/index.html")

@app.get("/ready")
async def run_page():
    return FileResponse("static/ready.html")

@app.get("/run")
async def run_page_1():
    return FileResponse("static/run.html")

@app.get("/complete")
async def run_page_2():
    return FileResponse("static/complete.html")

@app.post("/button/open")
async def button_open():
    global drawer_open
    drawer_open = True
    logger.info("Drawer open pressed")
    return{"ok":True}

@app.post("/button/close")
async def button_close():
    global drawer_close
    drawer_close = True
    logger.info("Drawer close pressed")
    return{"ok":True}

@app.post("/drawer_status/reset")
async def button_open():
    global drawer_close, drawer_open
    drawer_close = False
    drawer_open = False
    logger.info("Drawer reset pressed")
    return{"ok":True}

@app.post("/button/run")
async def button_run():
    global run_requested
    run_requested = True
    logger.info("Run button pressed")
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
        "drawer_open_status":drawer_open,
        "drawer_close_status":drawer_close,
        "exit_button_status":exit_button
        }

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
    if not profile_dir.exists():
        return profiles
    for path in profile_dir.glob("*.json"):
        try:
            with path.open() as f:
                data = json.load(f)
            if data.get( "post_in_gui" ):
                label = data.get("title", path.stem)
            else:
                continue
        except Exception as e:
            logger.info("Error processing %s"%(path))

        profiles.append({
            "id": path.name,
            "label" : label
            })
    return profiles

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

            #await state_change_event.wait()
            #logger.info ( "Submitted state", current_item.dict() )
            await websocket.send_json( panel_with_timer )
            await asyncio.sleep(1)
            #logger.info ( "Sent" )
    except Exception as e:
        logger.warning("websocket failed") 

    logger.info ( "Websocket ended" )
