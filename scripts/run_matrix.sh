#!/usr/bin/env bash
# --------------------------------------------------------------
# Usage: ./run_matrix.sh <reps> <duration_seconds> <fio_job_file> <scenario1> [scenario2 ...]
# Env:
#   MODES=baseline,adaptive
#   CEPHKEEL_SERVICE=cephkeel.service
#   SKIP_CEPHKEEL_TOGGLE=0
#   PAUSE_BETWEEN=30
#   INTERFACE=ens3
#   OSD_ID=2
#   STATUS_INTERVAL=5
#   PG_DUMP_INTERVAL=0
# --------------------------------------------------------------

set -euo pipefail

if [ "$#" -lt 4 ]; then
    echo "Usage: $0 <reps> <duration_seconds> <fio_job_file> <scenario1> [scenario2 ...]"
    exit 1
fi

REPS=$1
DURATION=$2
FIO_JOB=$3
shift 3
SCENARIOS=("$@")

MODES=${MODES:-baseline,adaptive}
CEPHKEEL_SERVICE=${CEPHKEEL_SERVICE:-cephkeel.service}
SKIP_CEPHKEEL_TOGGLE=${SKIP_CEPHKEEL_TOGGLE:-0}
PAUSE_BETWEEN=${PAUSE_BETWEEN:-30}

unit_exists() {
    systemctl list-unit-files --type=service "${CEPHKEEL_SERVICE}" --no-legend 2>/dev/null | awk '{print $1}' | grep -qx "${CEPHKEEL_SERVICE}"
}

set_mode() {
    local mode=$1
    if [ "${SKIP_CEPHKEEL_TOGGLE}" -eq 1 ]; then
        echo "Skipping CephKeel toggle (SKIP_CEPHKEEL_TOGGLE=1)"
        return
    fi
    if unit_exists; then
        if [ "${mode}" = "baseline" ]; then
            echo "Stopping ${CEPHKEEL_SERVICE} for baseline"
            sudo systemctl stop "${CEPHKEEL_SERVICE}" || true
        else
            echo "Starting ${CEPHKEEL_SERVICE} for adaptive"
            sudo systemctl start "${CEPHKEEL_SERVICE}" || true
        fi
        systemctl is-active "${CEPHKEEL_SERVICE}" || true
    else
        echo "Service ${CEPHKEEL_SERVICE} not found; continuing"
    fi
}

IFS=',' read -ra MODE_LIST <<< "${MODES}"
for mode in "${MODE_LIST[@]}"; do
    set_mode "${mode}"
    for scenario in "${SCENARIOS[@]}"; do
        for rep in $(seq 1 "${REPS}"); do
            echo "Running ${mode} ${scenario} rep ${rep}/${REPS}"
            MODE="${mode}" ./scripts/run_experiment.sh "${scenario}" "${DURATION}" "${FIO_JOB}"
            sleep "${PAUSE_BETWEEN}"
        done
    done
    sleep "${PAUSE_BETWEEN}"
 done
