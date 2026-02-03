# Aquila device container layout

## 1) What runs in each container

### Backend container (required)
- **Process**: FastAPI/Uvicorn API + device orchestration scripts.
- **Code**: `aquila_web/` for API + any runtime modules in repo root (assay logic, hardware control, etc.).
- **Port**: `8090` (matches `aquila_web/aquila_web.service`).
- **Notes**: This container is the “brain” of the device and should own access to GPIO/I2C/serial as needed.

### UI container (optional)
- **Static UI**: If you keep the current static HTML in `aquila_web/static`, you can serve it from the backend container (no separate UI container required).
- **Streamlit UI**: If you want Streamlit dashboards (`PCR_plot.py`, `aquila_web/stream/*.py`), run Streamlit in a separate container.
- **Port**: `8501` (Streamlit default).

### Reverse proxy (optional)
- Use Nginx or Caddy to present a single port (80/443) and route `/api` → backend, `/` → UI.
- Skip this if you are fine exposing `8090` and/or `8501` directly.

## 2) Runtime needs (ports, data, env)

### Ports
- Backend API: `8090`
- Streamlit UI (optional): `8501`

### Persistent data (volumes)
- Results and run artifacts: `./data/results:/opt/aquila/results`
- Logs: `./data/logs:/opt/aquila/logs`
- Profiles: `./data/profiles:/opt/aquila/profiles`
- Configs/calibration: `./data/config:/opt/aquila/config`

### Environment variables
- `DEVICE_ID` (serial number or unique ID)
- `DATA_DIR=/opt/aquila` (base path for logs/results)
- `PROFILE_DIR=/opt/aquila/profiles`
- `RESULTS_PATH=/opt/aquila/results/results.json` (if you use `results_path` in `aquila_web/main.py`)
- `RUN_MODE=prod` (prod vs dev)

## 3) Backend Dockerfile (template)

Create `Dockerfile.backend` at repo root:

```dockerfile
FROM python:3.11-slim-bookworm

WORKDIR /opt/aquila

# System deps if needed (example: gcc for scientific libs)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# TODO: add requirements.txt (see note below)
COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV DATA_DIR=/opt/aquila \
    PROFILE_DIR=/opt/aquila/profiles \
    RESULTS_PATH=/opt/aquila/results/results.json

EXPOSE 8090

CMD ["uvicorn", "aquila_web.main:app", "--host", "0.0.0.0", "--port", "8090"]
```

**Requirements file**: this repo does not include `requirements.txt`. Generate one from your dev env (or define a curated one) before building containers.

Example:
```bash
python -m pip freeze > requirements.txt
```

## 4) Streamlit Dockerfile (optional)

Create `Dockerfile.ui` if you want Streamlit dashboards:

```dockerfile
FROM python:3.11-slim-bookworm

WORKDIR /opt/aquila

COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8501

CMD ["streamlit", "run", "PCR_plot.py", "--server.port=8501", "--server.address=0.0.0.0"]
```

## 5) Compose file (stack definition)

Create `docker-compose.yml` at repo root:

```yaml
version: "3.9"

services:
  backend:
    build:
      context: .
      dockerfile: Dockerfile.backend
    ports:
      - "8090:8090"
    environment:
      DEVICE_ID: "arete-0001"
      RUN_MODE: "prod"
      DATA_DIR: "/opt/aquila"
      PROFILE_DIR: "/opt/aquila/profiles"
      RESULTS_PATH: "/opt/aquila/results/results.json"
    volumes:
      - ./data/results:/opt/aquila/results
      - ./data/logs:/opt/aquila/logs
      - ./data/profiles:/opt/aquila/profiles
      - ./data/config:/opt/aquila/config
    restart: unless-stopped

  ui:
    build:
      context: .
      dockerfile: Dockerfile.ui
    ports:
      - "8501:8501"
    environment:
      DEVICE_ID: "arete-0001"
      RUN_MODE: "prod"
    volumes:
      - ./data/results:/opt/aquila/results
    restart: unless-stopped

# Optional reverse proxy could be added here (nginx/caddy)
```

If you are serving the static UI via FastAPI (current `aquila_web/static`), you can omit the `ui` service entirely.

## 6) Build, run, and test locally

```bash
docker compose build
docker compose up
```

- API: `http://localhost:8090/`
- Streamlit (if enabled): `http://localhost:8501/`

## 7) Publish images (example using GHCR)

```bash
docker buildx build --platform linux/arm64 -f Dockerfile.backend -t ghcr.io/ORG/aquila-backend:v1.0.0 --push .
docker buildx build --platform linux/arm64 -f Dockerfile.ui -t ghcr.io/ORG/aquila-ui:v1.0.0 --push .
```

Update your Compose to reference the pushed images:

```yaml
backend:
  image: ghcr.io/ORG/aquila-backend:v1.0.0
ui:
  image: ghcr.io/ORG/aquila-ui:v1.0.0
```

## 8) Update workflow

1. Build and push a new version tag in CI.
2. On devices: `docker compose pull && docker compose up -d`.
3. Verify logs: `docker compose logs -f backend`.
```
