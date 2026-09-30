#!/usr/bin/env bash
# Unit tests for the deploy-script device-identity write (Phase A, Slice 3, #504).
#
# The deploy script writes /opt/aquila/config/device_identity.json write-once and
# makes it immutable. The script is fetched standalone (curl) and run from /tmp,
# so the logic lives INLINE in the deploy script — this harness sources ONLY the
# marked "device-identity lib" function block out of it, so we exercise the real
# code without running the whole root-only deploy.
#
# chattr/lsattr don't exist on macOS and would need root on Linux CI, so we shim
# them on PATH: chattr records the immutable request to a log; lsattr replays it.
#
# Run:  bash tests/deploy/test_device_identity.sh
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY="${HERE}/../../scripts/deploy/deployment3_greengrass.sh"

pass=0 fail=0
ok()   { echo "  ✓ $1"; pass=$((pass+1)); }
bad()  { echo "  ✗ $1"; fail=$((fail+1)); }
check(){ if eval "$2"; then ok "$1"; else bad "$1 — [$2]"; fi; }

# ── shim chattr/lsattr so immutability is observable off-device ────────────────
SHIMBIN="$(mktemp -d)"
cat > "${SHIMBIN}/chattr" <<'SH'
#!/usr/bin/env bash
# Records "+i <file>" requests so tests can assert immutability was set.
if [[ "$1" == "+i" ]]; then echo "$2" >> "${CHATTR_LOG}"; fi
SH
cat > "${SHIMBIN}/lsattr" <<'SH'
#!/usr/bin/env bash
# Prints an immutable-looking attr line iff chattr +i was recorded for the file.
f="${!#}"
if grep -qxF "${f}" "${CHATTR_LOG}" 2>/dev/null; then echo "----i---------e----- ${f}"
else echo "-------------e----- ${f}"; fi
SH
chmod +x "${SHIMBIN}/chattr" "${SHIMBIN}/lsattr"
export PATH="${SHIMBIN}:${PATH}"

# ── source ONLY the marked function block from the deploy script ───────────────
LIB="$(sed -n '/# >>> device-identity lib >>>/,/# <<< device-identity lib <<</p' "${DEPLOY}")"
if [[ -z "${LIB}" ]]; then
    bad "deploy script has a '# >>> device-identity lib >>>' function block"
    echo "FAIL (${fail})"; exit 1
fi
eval "${LIB}"

# ── each test gets a fresh temp config dir + chattr log ────────────────────────
# CHATTR_LOG lives OUTSIDE CFG so the "nothing else written" check stays honest.
new_cfg() { CFG="$(mktemp -d)"; export CHATTR_LOG="$(mktemp)"; }

# ══ Test 1 (tracer): writes a record naming the requested well count ══
new_cfg
write_device_identity "${CFG}" 15 "2026-09-30T00:00:00Z"
check "writes device_identity.json" "test -f '${CFG}/device_identity.json'"
check "record names wells=15 as an integer" \
    "python3 -c 'import json,sys; d=json.load(open(\"${CFG}/device_identity.json\")); sys.exit(0 if d[\"wells\"]==15 else 1)'"

# ══ Test 2: write-once — an existing record is never overwritten ══
new_cfg
write_device_identity "${CFG}" 4 "2026-09-30T00:00:00Z"
write_device_identity "${CFG}" 15 "2099-01-01T00:00:00Z" || true   # second attempt
check "existing record left untouched (still wells=4)" \
    "python3 -c 'import json,sys; d=json.load(open(\"${CFG}/device_identity.json\")); sys.exit(0 if d[\"wells\"]==4 else 1)'"

# ══ Test 3: an unsupported well count is rejected at write time ══
new_cfg
if write_device_identity "${CFG}" 5 "2026-09-30T00:00:00Z" 2>/dev/null; then
    bad "unsupported well count (5) is rejected (nonzero exit)"
else
    ok "unsupported well count (5) is rejected (nonzero exit)"
fi
check "no record written for an unsupported count" \
    "! test -e '${CFG}/device_identity.json'"

# ══ Test 4: the written record is made immutable ══
new_cfg
write_device_identity "${CFG}" 4 "2026-09-30T00:00:00Z"
check "chattr +i requested on the record" \
    "grep -qxF '${CFG}/device_identity.json' '${CHATTR_LOG}'"
check "lsattr reports the record immutable" \
    "lsattr '${CFG}/device_identity.json' | awk '{print \$1}' | grep -q i"

# ══ Test 5: an unset well count defaults to 4 (baseline build) ══
check "resolve_wells with no value defaults to 4" "[[ \"\$(resolve_wells '')\" == 4 ]]"
check "resolve_wells passes a stated value through" "[[ \"\$(resolve_wells 15)\" == 15 ]]"

# ══ Test 6: record carries schema + provisioned timestamp, and touches nothing else ══
new_cfg
write_device_identity "${CFG}" 15 "2026-09-30T12:34:56Z"
check "record carries schema version" \
    "python3 -c 'import json,sys; d=json.load(open(\"${CFG}/device_identity.json\")); sys.exit(0 if \"schema\" in d else 1)'"
check "record carries provisioned timestamp" \
    "python3 -c 'import json,sys; d=json.load(open(\"${CFG}/device_identity.json\")); sys.exit(0 if d.get(\"provisioned_utc\")==\"2026-09-30T12:34:56Z\" else 1)'"
check "writes device_identity.json and nothing else (separate from host_config/device.env)" \
    "[[ \"\$(ls -A '${CFG}')\" == 'device_identity.json' ]]"

echo ""
echo "PASS ${pass}  FAIL ${fail}"
[[ ${fail} -eq 0 ]]
