# Raspberry Pi Fleet Deployment System

Production-grade deployment architecture for managing **100+ Raspberry
Pi edge devices** with OTA updates, monitoring, rollback, and security.

## Technology Stack

Connectivity\
- Tailscale

Deployment\
- Docker - Watchtower

CI/CD\
- GitHub Actions

Registry\
- GitHub Container Registry (GHCR)

Monitoring (offline-friendly)\
- VictoriaMetrics Agent - Node Exporter - Grafana Cloud (optional)

Logging\
- Vector → Loki

------------------------------------------------------------------------

# 1. System Architecture

Developer pushes code → GitHub Actions builds container → Image pushed
to GHCR → Watchtower pulls update → Devices update containers.

------------------------------------------------------------------------

# 2. What Runs On Each Device

Each Raspberry Pi runs:

  Component                Purpose
  ------------------------ --------------------------
  Docker                   container runtime
  Watchtower               OTA container updates
  Tailscale                secure device networking
  Vector                   log shipping
  VictoriaMetrics Agent    metrics buffering
  Node Exporter            system metrics
  Application containers   business logic

------------------------------------------------------------------------

# 3. Raspberry Pi Base Setup

Install **Raspberry Pi OS Lite (64-bit)**.

``` bash
sudo apt update && sudo apt upgrade -y
```

Install Docker:

``` bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
```

Install Docker Compose:

``` bash
sudo apt install docker-compose-plugin
```

Install Tailscale:

``` bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
```

------------------------------------------------------------------------

# 4. Device Configuration

Directory structure:

    /opt/fleet
        docker-compose.yml
        vector.yaml
        vmagent.yaml

Example docker-compose.yml:

``` yaml
version: "3.9"

services:

  app:
    image: ghcr.io/org/myapp:stable
    restart: unless-stopped
    labels:
      - "com.centurylinklabs.watchtower.enable=true"
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/health"]
      interval: 30s
      timeout: 5s
      retries: 3
    mem_limit: 256m

  watchtower:
    image: containrrr/watchtower
    restart: unless-stopped
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
    environment:
      WATCHTOWER_LABEL_ENABLE: "true"
      WATCHTOWER_HTTP_API_UPDATE: "true"
      WATCHTOWER_HTTP_API_TOKEN: "replace-with-secret"
      WATCHTOWER_CLEANUP: "true"
    command: --label-enable --http-api-update --cleanup

  node-exporter:
    image: prom/node-exporter
    restart: unless-stopped
    network_mode: host

  vmagent:
    image: victoriametrics/vmagent
    restart: unless-stopped
```

------------------------------------------------------------------------

# 5. OTA Deployment Flow

1.  Developer pushes code
2.  GitHub Actions builds container
3.  Image pushed to GHCR
4.  CI triggers Watchtower API
5.  Devices pull updated container

Example OTA trigger:

    POST http://device-ip:8080/v1/update
    Authorization: Bearer TOKEN

------------------------------------------------------------------------

# 6. Device Grouping Strategy

Use deployment rings:

  Ring     Devices     Purpose
  -------- ----------- ------------------
  dev      5           internal testing
  canary   10          early production
  beta     30          wider rollout
  prod     remaining   full deployment

Devices use different tags:

    myapp:dev
    myapp:canary
    myapp:stable

------------------------------------------------------------------------

# 7. Progressive Rollout

Example deployment sequence:

    5 devices → wait 1 hour
    10 devices → wait 3 hours
    all devices

CI promotes images across rings once health metrics pass.

------------------------------------------------------------------------

# 8. GitHub Actions CI/CD

Create:

    .github/workflows/build.yml

Example pipeline:

``` yaml
name: Build and Deploy

on:
  push:
    branches: [ main ]

jobs:

  build:
    runs-on: ubuntu-latest

    permissions:
      packages: write
      contents: read

    steps:

    - uses: actions/checkout@v3

    - uses: docker/setup-buildx-action@v2

    - uses: docker/login-action@v2
      with:
        registry: ghcr.io
        username: ${{ github.actor }}
        password: ${{ secrets.GITHUB_TOKEN }}

    - name: Build image
      run: |
        docker build -t ghcr.io/org/myapp:${{ github.sha }} .
        docker push ghcr.io/org/myapp:${{ github.sha }}

    - name: Tag stable
      run: |
        docker tag ghcr.io/org/myapp:${{ github.sha }} ghcr.io/org/myapp:stable
        docker push ghcr.io/org/myapp:stable
```

------------------------------------------------------------------------

# 9. Monitoring (Offline Friendly)

Use **VictoriaMetrics Agent**.

Benefits:

-   buffers metrics locally
-   low memory footprint
-   forwards metrics when internet reconnects

Metrics collected:

-   CPU
-   memory
-   disk
-   temperature
-   container stats

------------------------------------------------------------------------

# 10. Logging

Use **Vector + Loki**.

Architecture:

Containers → Vector → Local Buffer → Loki

Example vector.yaml:

``` yaml
sources:
  docker_logs:
    type: docker_logs

sinks:
  loki:
    type: loki
    endpoint: https://loki.example.com
```

------------------------------------------------------------------------

# 11. Rollback Strategy

Never deploy `latest`.

Use immutable versions:

    myapp:1.2.3
    myapp:1.2.4

Deployment tag:

    myapp:stable

Rollback:

    docker tag myapp:1.2.3 myapp:stable
    docker push myapp:stable

Devices automatically downgrade.

------------------------------------------------------------------------

# 12. Health Checks

Example:

``` yaml
healthcheck:
  test: ["CMD", "curl", "-f", "http://localhost:8080/health"]
  interval: 30s
  timeout: 5s
  retries: 3
```

Health checks should verify:

-   service readiness
-   database connectivity
-   disk availability

------------------------------------------------------------------------

# 13. Security Setup

### Tailscale ACL

Restrict update triggers to CI servers.

### Secure Watchtower

    WATCHTOWER_HTTP_API_TOKEN

### SSH Hardening

Disable password login.

    PasswordAuthentication no

Use SSH keys only.

### Firewall

    sudo ufw allow ssh
    sudo ufw enable

------------------------------------------------------------------------

# 14. Device Provisioning

For each device:

1.  Flash Raspberry Pi OS
2.  Install Docker
3.  Install Tailscale
4.  Clone fleet repo
5.  Start services

```{=html}
<!-- -->
```
    git clone https://github.com/org/fleet-config
    cd fleet-config
    docker compose up -d

Device automatically joins the fleet.

------------------------------------------------------------------------

# 15. Observability

Grafana dashboards track:

-   device uptime
-   CPU usage
-   memory usage
-   disk usage
-   container restarts
-   OTA success rates

------------------------------------------------------------------------

# 16. Disaster Recovery

If a device fails:

1.  Reflash SD card
2.  Reinstall base software
3.  Re-run provisioning

Device automatically rejoins fleet.

------------------------------------------------------------------------

# Final System Summary

  Feature             Solution
  ------------------- ------------------
  connectivity        Tailscale
  container runtime   Docker
  OTA updates         Watchtower
  CI/CD               GitHub Actions
  registry            GHCR
  monitoring          VictoriaMetrics
  logs                Vector + Loki
  rollout             ring deployments
  rollback            tag rollback
