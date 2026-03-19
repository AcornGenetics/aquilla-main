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

Monitoring (Grafana Labs)\
- Grafana Agent (Alloy) - Node Exporter - Grafana Cloud

Logging (Grafana Labs)\
- Grafana Agent (Alloy) → Loki (Grafana Cloud)

------------------------------------------------------------------------

# 1. System Architecture

Developer pushes code → GitHub Actions builds container → Image pushed
to GHCR → Watchtower (or manual pull) updates devices.

------------------------------------------------------------------------

# 2. What Runs On Each Device

Each Raspberry Pi runs:

  Component                Purpose
  ------------------------ --------------------------
  Docker                   container runtime
  Watchtower               OTA container updates
  Tailscale                secure device networking
  Grafana Agent (Alloy)    metrics + logs
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
        grafana-agent.yaml

Example docker-compose.yml:

``` yaml
version: "3.9"

services:

  app:
    image: ghcr.io/org/aquila-api:pilot
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

  grafana-agent:
    image: grafana/agent
    restart: unless-stopped
```

------------------------------------------------------------------------

# 5. OTA Deployment Flow

1.  Developer pushes code
2.  GitHub Actions builds container
3.  Image pushed to GHCR
4.  Devices update via Watchtower API or manual pull

Example OTA trigger:

    POST http://device-ip:8080/v1/update
    Authorization: Bearer TOKEN

------------------------------------------------------------------------

# 6. Device Grouping Strategy

Use deployment rings:

  Ring     Devices     Purpose
  -------- ----------- ------------------
  dev      5           internal testing
  pilot    30          wider rollout
  prod     remaining   full deployment

Devices use different tags:

    aquila-api:dev
    aquila-api:pilot
    aquila-api:prod

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
        docker build -t ghcr.io/org/aquila-api:${{ github.sha }} .
        docker push ghcr.io/org/aquila-api:${{ github.sha }}

    - name: Tag pilot
      run: |
        docker tag ghcr.io/org/aquila-api:${{ github.sha }} ghcr.io/org/aquila-api:pilot
        docker push ghcr.io/org/aquila-api:pilot
```

------------------------------------------------------------------------

# 9. Monitoring (Grafana Labs)

Use **Grafana Agent (Alloy)**.

Benefits:

-   buffers metrics locally
-   low memory footprint
-   forwards metrics to Grafana Cloud

Metrics collected:

-   CPU
-   memory
-   disk
-   temperature
-   container stats

------------------------------------------------------------------------

# 10. Logging (Grafana Labs)

Use **Grafana Agent (Alloy) + Loki**.

Architecture:

Containers → Grafana Agent (Alloy) → Loki (Grafana Cloud)

Example grafana-agent.yaml:

``` yaml
logs:
  configs:
    - name: default
      positions:
        filename: /tmp/positions.yaml
      scrape_configs:
        - job_name: docker
          docker_sd_configs:
            - host: unix:///var/run/docker.sock
      clients:
        - url: https://loki.example.com/loki/api/v1/push
```

------------------------------------------------------------------------

# 11. Rollback Strategy

Never deploy `latest`.

Use immutable versions:

    myapp:1.2.3
    myapp:1.2.4

Deployment tag:

    myapp:pilot

Rollback:

    docker tag myapp:1.2.3 myapp:pilot
    docker push myapp:pilot

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
  monitoring          Grafana Labs (Grafana Cloud)
  logs                Grafana Labs (Loki)
  rollout             ring deployments
  rollback            tag rollback
