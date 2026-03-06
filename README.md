# Aquila
Aquila PCR system project

## Docker
- API Dockerfile: `docker/Dockerfile.api`
- UI Dockerfile: `docker/Dockerfile.ui`
- Compose: `docker/docker-compose.yml`

## Wi-Fi configuration (Pi)
- Edit `config_files/wifi.json` with `ssid` and `psk`.
- Run `update.sh` (or `sudo python3 scripts/apply_wifi.py`) to apply the config.
