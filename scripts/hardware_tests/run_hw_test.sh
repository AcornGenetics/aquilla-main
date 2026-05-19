#!/usr/bin/env bash
# Usage:
#   run_hw_test.sh raster_detailed_log_centered fam
#   run_hw_test.sh raster_detailed_log_centered rox
#   run_hw_test.sh raster_detailed_log_centered both   ← runs fam then rox back to back
#   run_hw_test.sh motor_drawer home
#   run_hw_test.sh motor_drawer open
#   run_hw_test.sh motor_drawer read
#   run_hw_test.sh motor_axis
#   run_hw_test.sh test_adc4_logged fam
#   run_hw_test.sh test_adc4_logged rox
#   run_hw_test.sh run_lid_heater
#   run_hw_test.sh lod_verification_all
#   run_hw_test.sh led_current_verification fam
#   run_hw_test.sh led_current_verification rox

set -euo pipefail

CONTAINER="aquila-app"
HW_TESTS="scripts/hardware_tests"

TEST="${1:-}"
shift || true

if [[ -z "$TEST" ]]; then
    echo "Usage: $0 <test> [args...]"
    echo "Tests: raster_detailed_log_centered, motor_drawer, motor_axis,"
    echo "       test_adc4_logged, run_lid_heater, lod_verification_all, led_current_verification"
    exit 1
fi

_run_raster() {
    local dye="$1"
    IMAGE=$(docker inspect "$CONTAINER" --format '{{.Config.Image}}')
    echo "Stopping $CONTAINER..."
    docker stop "$CONTAINER"
    echo "Running raster scan ($dye)..."
    docker run --rm -it --privileged \
        -v /dev:/dev \
        -v /opt/aquila/config:/opt/aquila/config \
        -v /opt/aquila/logs:/opt/aquila/logs \
        -w /opt/aquila \
        -e CONFIG_DIR=/opt/aquila/config \
        -e DEVICE_HOSTNAME="$(hostname)" \
        -e PYTHONPATH=/opt/aquila \
        "$IMAGE" \
        python3 "$HW_TESTS/raster_detailed_log_centered.py" "$dye"
}

case "$TEST" in
    raster_detailed_log_centered)
        DYE="${1:-fam}"
        if [[ "$DYE" == "both" ]]; then
            _run_raster fam
            _run_raster rox
        else
            _run_raster "$DYE"
        fi
        echo "Restarting $CONTAINER..."
        docker start "$CONTAINER"
        ;;
    motor_drawer)
        docker exec -e PYTHONPATH=/opt/aquila "$CONTAINER" \
            python3 "$HW_TESTS/motor_drawer.py" "$@"
        ;;
    motor_axis)
        docker exec -e PYTHONPATH=/opt/aquila "$CONTAINER" \
            python3 "$HW_TESTS/motor_axis.py" "$@"
        ;;
    test_adc4_logged)
        docker exec -e PYTHONPATH=/opt/aquila "$CONTAINER" \
            python3 "$HW_TESTS/test_adc4_logged.py" "$@"
        ;;
    run_lid_heater)
        docker exec -e PYTHONPATH=/opt/aquila "$CONTAINER" \
            python3 "$HW_TESTS/run_lid_heater.py" "$@"
        ;;
    lod_verification_all)
        docker exec -e PYTHONPATH=/opt/aquila "$CONTAINER" \
            python3 "$HW_TESTS/lod_verification_all.py" "$@"
        ;;
    led_current_verification)
        docker exec -e PYTHONPATH=/opt/aquila "$CONTAINER" \
            python3 "$HW_TESTS/led_current_verification.py" "$@"
        ;;
    *)
        echo "Unknown test: $TEST"
        exit 1
        ;;
esac
