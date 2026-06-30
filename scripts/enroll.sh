#!/usr/bin/env bash
# enroll.sh — operator-side: enrol + verify ONE Sentri's Device Certificate.
#
#   ./scripts/enroll.sh sn03
#
# Pass just the serial-number host (e.g. sn03); it's reached over Tailscale SSH as
# pi@<sn>. Runs on the OPERATOR's machine — your AWS credentials are used to sign
# the /enroll request and never touch the Pi. The Pi must be powered on and
# already deployed (deployment2.sh has generated /opt/aquila/config/device.csr).
#
# Wraps the three manual steps:
#   1. confirm the CSR exists on the Pi
#   2. enrol it against acorn-ca /enroll (scripts/enroll_device.py)
#   3. verify the issued cert authenticates over mTLS to /renew
#
# Endpoints default to PROD; override via env for another environment:
#   ENROLL_ENDPOINT=https://<id>.execute-api.us-east-2.amazonaws.com/enroll \
#   RENEW_ENDPOINT=https://renew-dev.cloud.acorngenetics.com/renew \
#   ./scripts/enroll.sh sn03
set -euo pipefail

SN="${1:-}"
if [[ -z "$SN" ]]; then
    read -rp "Device serial-number host (e.g. sn03): " SN
fi
[[ -z "$SN" ]] && { echo "ERROR: no device given." >&2; exit 1; }
PI="pi@${SN}"
REGION="${AWS_REGION:-us-east-2}"
ENROLL_ENDPOINT="${ENROLL_ENDPOINT:-https://1x9561i626.execute-api.us-east-2.amazonaws.com/enroll}"
RENEW_ENDPOINT="${RENEW_ENDPOINT:-https://renew.cloud.acorngenetics.com/renew}"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "==> [1/3] ${SN}: confirm CSR exists"
if ! ssh "$PI" 'sudo test -s /opt/aquila/config/device.csr'; then
    echo "ERROR: no CSR on ${SN} — run deployment2.sh on the Pi first." >&2
    exit 1
fi
printf '    CSR '
ssh "$PI" 'sudo openssl req -in /opt/aquila/config/device.csr -noout -subject'

echo "==> [2/3] ${SN}: enrol against acorn-ca (SigV4 with your AWS creds)"
python3 "$REPO/scripts/enroll_device.py" \
    --pi "$PI" --endpoint "$ENROLL_ENDPOINT" --region "$REGION"

echo "==> [3/3] ${SN}: verify the cert authenticates over mTLS to /renew"
ssh "$PI" "cd /opt/aquila && sudo bash -c 'set -a && . config/device.env && \
    python scripts/verify_device_cert.py --renew-endpoint ${RENEW_ENDPOINT}'"

echo "✅ ${SN}: enrolled + verified"
