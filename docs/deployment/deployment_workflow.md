# Multi-device container deployment plan

## Goal
Push updated containers from a laptop (or CI) and sync many devices worldwide.

## Overview
- **Registry**: Store images in GHCR/Docker Hub.
- **Build pipeline**: Build ARM images and push with version tags.
- **Devices**: Run a fixed `docker-compose.prod.yml` that pulls registry images.
- **Updates**: Devices pull new tags and restart containers.

## 1) Set up the registry
Choose one:
- GitHub Container Registry (GHCR)
- Docker Hub

Example image names:
- `ghcr.io/ORG/aquila-backend`
- `ghcr.io/ORG/aquila-ui`
- `ghcr.io/ORG/aquila-streamlit` (optional)

## 2) Image build + push workflow
### Manual (laptop)
```bash
docker buildx build --platform linux/arm64 \
  -f docker/Dockerfile.backend -t ghcr.io/ORG/aquila-backend:v1.0.0 --push .

docker buildx build --platform linux/arm64 \
  -f docker/Dockerfile.ui -t ghcr.io/ORG/aquila-ui:v1.0.0 --push .

docker buildx build --platform linux/arm64 \
  -f docker/Dockerfile.streamlit -t ghcr.io/ORG/aquila-streamlit:v1.0.0 --push .
```

### CI (recommended)
- GitHub Actions builds and pushes on every tag.
- Tags: `v1.0.0`, `v1.0.1`, plus `latest`.

## 3) Device compose file (registry images)
Create `docker-compose.prod.yml` on each device:

```yaml
services:
  backend:
    image: ghcr.io/ORG/aquila-backend:v1.0.0
    ports:
      - "8090:8090"
    volumes:
      - /data/results:/opt/aquila/results
      - /data/logs:/opt/aquila/logs
      - /data/profiles:/opt/aquila/profiles
      - /data/config:/opt/aquila/config
    devices:
      - "/dev/ttyACM0:/dev/ttyACM0"
      - "/dev/i2c-1:/dev/i2c-1"
      - "/dev/spidev0.0:/dev/spidev0.0"
      - "/dev/spidev0.1:/dev/spidev0.1"
      - "/dev/gpiomem:/dev/gpiomem"
    privileged: true
    restart: unless-stopped

  ui:
    image: ghcr.io/ORG/aquila-ui:v1.0.0
    ports:
      - "8080:80"
    restart: unless-stopped

  # optional, only if you want Streamlit deployed
  streamlit:
    image: ghcr.io/ORG/aquila-streamlit:v1.0.0
    ports:
      - "8501:8501"
    restart: unless-stopped
```

Start once:
```bash
docker compose -f docker-compose.prod.yml up -d
```

## 4) Update workflow
### Manual update on devices
```bash
docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml up -d
```

### Auto-update options
**Option A: Watchtower**
- Runs on each device and auto-pulls new tags.

**Option B: Fleet manager**
- Balena, Mender, or Portainer to push updates centrally.

**Option C: Custom updater**
- Devices poll an API for “latest version.”
- When version changes, run `pull + up -d`.

## 5) Best practices
- Use **versioned tags** for rollbacks.
- Keep **backend updates rare**, UI updates frequent.
- Maintain a **stable** tag for production devices.
- Log container versions on boot for traceability.
