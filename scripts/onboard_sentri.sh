#!/usr/bin/env bash
# onboard_sentri.sh — operator-side: take ONE Sentri from "deployed" to "a Thing
# in a ring", end to end.
#
#   ./scripts/onboard_sentri.sh                 # prompts for Pi host + ring
#   ./scripts/onboard_sentri.sh sn11 pilot      # non-interactive
#
# Runs on the OPERATOR's machine — your AWS credentials are used for every IoT
# call and never touch the Pi. The Pi is reached over SSH as pi@<sn> and must be
# powered on and already deployed (deployment*.sh has generated the CSR).
#
# What it does, idempotently (safe to re-run):
#   1. Enroll the Device Certificate if the Pi doesn't already have a working one
#      (delegates to scripts/enroll.sh — mTLS-verifies against /renew).
#   2. Read the serial (cert CN = Thing name) and the cert PEM off the Pi.
#   3. Register the cert in AWS IoT (ACTIVE) if it isn't already.
#   4. Create the Thing (name = serial), attach the cert, attach the device policy.
#   5. Add the Thing to the requested ring (Thing group).
#
# The Thing is keyed on the SERIAL (permanent); the cert is the credential and
# rotates on renewal — the renew path re-attaches the new cert to the same Thing,
# so a device keeps its identity and ring across renewals. That's why step 4 keys
# the Thing on the serial, not the (ephemeral) cert id.
#
# Env overrides (all default to PROD / us-east-2):
#   AWS_REGION, ENROLL_ENDPOINT, RENEW_ENDPOINT, POLICY_NAME, SKIP_ENROLL=1
set -euo pipefail

# ── Inputs ────────────────────────────────────────────────────────────────────
SN="${1:-}"
RING="${2:-}"
[[ -z "$SN" ]]   && read -rp "Device serial-number host (e.g. sn11): " SN
[[ -z "$SN" ]]   && { echo "ERROR: no device given." >&2; exit 1; }
if [[ -z "$RING" ]]; then
    read -rp "Ring / Thing group [holding|sandbox|dev|pilot|prod] (default: holding): " RING
    RING="${RING:-holding}"
fi
case "$RING" in
    holding|sandbox|dev|pilot|prod) ;;
    *) echo "ERROR: '$RING' is not a valid ring (holding|sandbox|dev|pilot|prod)." >&2; exit 1 ;;
esac

PI="pi@${SN}"
REGION="${AWS_REGION:-us-east-2}"
POLICY_NAME="${POLICY_NAME:-acorn-sentri-device}"
RENEW_ENDPOINT="${RENEW_ENDPOINT:-https://renew.cloud.acorngenetics.com/renew}"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Temp file for the cert PEM pulled off the Pi; always cleaned up.
TMP_CRT="$(mktemp -t sentri-crt.XXXXXX)"
trap 'rm -f "$TMP_CRT"' EXIT

# ── Preflight ─────────────────────────────────────────────────────────────────
echo "==> preflight: AWS identity + SSH reachability"
ACCT="$(aws sts get-caller-identity --query Account --output text 2>/dev/null || true)"
[[ -z "$ACCT" ]] && { echo "ERROR: no working AWS credentials in this shell." >&2; exit 1; }
echo "    AWS account ${ACCT}, region ${REGION}"
ssh -o BatchMode=yes -o ConnectTimeout=10 "$PI" true 2>/dev/null \
    || { echo "ERROR: cannot SSH to ${PI} (powered on? Tailscale up?)." >&2; exit 1; }

# ── 1. Enroll the Device Certificate (skip if already valid) ───────────────────
already_enrolled() {
    # A cert is "good" if it exists on the Pi and authenticates over mTLS to /renew
    # (any HTTP status other than 000 means the handshake was accepted).
    ssh "$PI" 'sudo test -s /opt/aquila/config/device.crt' 2>/dev/null || return 1
    local code
    code="$(ssh "$PI" "sudo curl -sS -o /dev/null -w '%{http_code}' --max-time 15 \
        --cert /opt/aquila/config/device.crt --key /opt/aquila/config/device.key \
        -X POST '${RENEW_ENDPOINT}' -d '{}'" 2>/dev/null || true)"
    [[ -n "$code" && "$code" != "000" ]]
}

if [[ "${SKIP_ENROLL:-}" == "1" ]]; then
    echo "==> [1/5] SKIP_ENROLL=1 — assuming the cert is already enrolled"
elif already_enrolled; then
    echo "==> [1/5] ${SN}: cert already present and valid (mTLS OK) — skipping enroll"
else
    echo "==> [1/5] ${SN}: enrolling Device Certificate"
    "$REPO/scripts/enroll.sh" "$SN"
fi

# ── 2. Read serial (CN = Thing name) and cert PEM off the Pi ───────────────────
echo "==> [2/5] ${SN}: reading serial + cert from the Pi"
ssh "$PI" 'sudo cat /opt/aquila/config/device.crt' > "$TMP_CRT" 2>/dev/null
[[ -s "$TMP_CRT" ]] || { echo "ERROR: could not read device.crt from ${PI}." >&2; exit 1; }
SERIAL="$(openssl x509 -in "$TMP_CRT" -noout -subject 2>/dev/null \
            | sed -n 's/.*CN *= *\([^,/]*\).*/\1/p' | tr -d '[:space:]')"
[[ -n "$SERIAL" ]] || { echo "ERROR: could not parse serial (CN) from the cert." >&2; exit 1; }
# AWS IoT's certificateId is the lowercase-hex SHA-256 of the DER-encoded cert.
CERT_ID="$(openssl x509 -in "$TMP_CRT" -outform DER 2>/dev/null | openssl dgst -sha256 | awk '{print $NF}')"
[[ -n "$CERT_ID" ]] || { echo "ERROR: could not compute cert id." >&2; exit 1; }
CERT_ARN="arn:aws:iot:${REGION}:${ACCT}:cert/${CERT_ID}"
echo "    serial (Thing name): ${SERIAL}"
echo "    cert id:             ${CERT_ID}"

# ── 3. Register the cert in IoT (ACTIVE) if not already ────────────────────────
echo "==> [3/5] ${SN}: ensuring the cert is registered ACTIVE in IoT"
if aws iot describe-certificate --certificate-id "$CERT_ID" --region "$REGION" >/dev/null 2>&1; then
    echo "    already registered"
else
    aws iot register-certificate-without-ca \
        --certificate-pem "file://${TMP_CRT}" --status ACTIVE --region "$REGION" >/dev/null
    echo "    registered ACTIVE"
fi

# ── 4. Create the Thing, attach the cert + policy (all idempotent) ─────────────
echo "==> [4/5] ${SN}: Thing '${SERIAL}' + cert + policy"
if aws iot describe-thing --thing-name "$SERIAL" --region "$REGION" >/dev/null 2>&1; then
    echo "    Thing exists"
else
    aws iot create-thing --thing-name "$SERIAL" --region "$REGION" >/dev/null
    echo "    Thing created"
fi
# AttachThingPrincipal / AttachPolicy are idempotent — re-attaching is a no-op.
aws iot attach-thing-principal --thing-name "$SERIAL" --principal "$CERT_ARN" --region "$REGION"
aws iot attach-policy --policy-name "$POLICY_NAME" --target "$CERT_ARN" --region "$REGION"
echo "    cert attached to Thing; policy '${POLICY_NAME}' attached to cert"

# ── 5. Ring membership (one ring per device) ───────────────────────────────────
echo "==> [5/5] ${SN}: adding Thing to ring '${RING}'"
# One-ring rule: a Sentri must be in exactly one ring. Warn if it's already in a
# different ring so conflicting deployments don't stack up (move it deliberately).
CURRENT_RINGS="$(aws iot list-thing-groups-for-thing --thing-name "$SERIAL" --region "$REGION" \
                    --query 'thingGroups[].groupName' --output text 2>/dev/null || true)"
for g in $CURRENT_RINGS; do
    if [[ "$g" != "$RING" ]] && [[ "$g" =~ ^(holding|sandbox|dev|pilot|prod)$ ]]; then
        echo "    ⚠ already in ring '${g}' — a device should be in ONE ring." \
             "Remove it with: aws iot remove-thing-from-thing-group --thing-name ${SERIAL} --thing-group-name ${g} --region ${REGION}"
    fi
done
aws iot add-thing-to-thing-group --thing-name "$SERIAL" --thing-group-name "$RING" --region "$REGION"

echo ""
echo "✅ ${SN} onboarded — Thing '${SERIAL}' is in ring '${RING}'."
[[ "$RING" == "holding" ]] && echo "   Note: 'holding' has no deployment; move it to sandbox/dev/pilot/prod for the app to land."
