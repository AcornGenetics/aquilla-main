# Aquila Web UI (FastAPI)

Quick start commands for the FastAPI UI server.

## Local development
From `aquila-main/aquila_web`:

```
uvicorn main:app --reload --host 127.0.0.1
```

## Device/systemd
The bundled service runs Uvicorn on port 8090:

```
/home/pi/aquila/bin/uvicorn main:app --host 0.0.0.0 --port 8090
```

If you install the service file, start it with:

```
sudo systemctl start aquila_web.service
```
