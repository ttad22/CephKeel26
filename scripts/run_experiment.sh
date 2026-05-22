#!/usr/bin/env bash
# --------------------------------------------------------------
# Usage: ./run_experiment.sh <scenario> <duration_seconds> <fio_job_file>
# --------------------------------------------------------------

set -euo pipefail

SCENARIO=$1          # e.g. bw_200m, loss_1pct, jitter_50, osd_restart, link_down
DURATION=$2          # how long the workload should run (seconds)
FIO_JOB=$3           # absolute path to the fio job description

TIMESTAMP=$(date +%s)
MODE="${MODE:-}"
PREFIX=""
if [ -n "${MODE}" ]; then
    PREFIX="${MODE}_"
fi
LOGDIR="data/${PREFIX}${SCENARIO}_${TIMESTAMP}"
mkdir -p "${LOGDIR}"

# ----------- timeline logging ----------------------
STATUS_INTERVAL="${STATUS_INTERVAL:-5}"
PG_DUMP_INTERVAL="${PG_DUMP_INTERVAL:-0}"
CEPH_STATUS_TIMELINE="${LOGDIR}/ceph_status_timeline.log"
touch "${CEPH_STATUS_TIMELINE}"

log_event() {
    echo "EVENT $(date --iso-8601=seconds) $1" >> "${CEPH_STATUS_TIMELINE}"
}

status_logger() {
    while true; do
        echo "=== $(date --iso-8601=seconds) ===" >> "${CEPH_STATUS_TIMELINE}"
        ceph -s >> "${CEPH_STATUS_TIMELINE}"
        sleep "${STATUS_INTERVAL}"
    done
}

pg_dump_logger() {
    while true; do
        ts=$(date +%s)
        ceph pg dump --format=json > "${LOGDIR}/pg_dump_${ts}.json"
        sleep "${PG_DUMP_INTERVAL}"
    done
}

# ----------- baseline system collectors -------------
ceph -s > "${LOGDIR}/ceph_status_pre.log"
sar -u 1 > "${LOGDIR}/cpu_pre.sar" &
SAR_PID=$!
iostat -xz 1 > "${LOGDIR}/disk_pre.iostat" &
IOSTAT_PID=$!

status_logger &
STATUS_PID=$!
if [ "${PG_DUMP_INTERVAL}" -gt 0 ]; then
    pg_dump_logger &
    PG_PID=$!
else
    PG_PID=""
fi
log_event "experiment_start"
if [ -n "${MODE}" ]; then
    log_event "mode ${MODE}"
fi

# ----------- apply the selected impairment ----------
INTERFACE="${INTERFACE:-vmbr0.30}"   # override per host (e.g., INTERFACE=ens3)
OSD_ID="${OSD_ID:-0}"

case "${SCENARIO}" in
    no_fault)
        # No impairment; real-world baseline with guards/services active
        ;;
    bw_200m)
        sudo tc qdisc add dev "${INTERFACE}" root handle 1: tbf rate 200mbit burst 32kbit latency 400ms
        ;;
    loss_1pct)
        sudo tc qdisc add dev "${INTERFACE}" root netem loss 1%
        ;;
    jitter_50)
        sudo tc qdisc add dev "${INTERFACE}" root netem delay 20ms 50ms distribution normal
        ;;
    osd_restart)
        sudo systemctl restart "ceph-osd@${OSD_ID}"
        ;;
    link_down)
        sudo ip link set dev "${INTERFACE}" down
        ;;
    *)
        echo "Unknown scenario: ${SCENARIO}"
        exit 1
        ;;
esac
log_event "impairment_applied ${SCENARIO}"

# --------------- run the client workload ------------
if [ "${DURATION}" -gt 600 ]; then
    echo "Duration must be <= 600 seconds"
    exit 1
fi
TIMEOUT=$((DURATION + 60))
if [ "${TIMEOUT}" -gt 600 ]; then
    TIMEOUT=600
fi
timeout "${TIMEOUT}" fio --output-format=json --output "${LOGDIR}/fio.json" "${FIO_JOB}" \
    > "${LOGDIR}/fio.out" 2> "${LOGDIR}/fio.err" || true
log_event "workload_complete"

# --------------- clean up the impairment -----------
sudo tc qdisc del dev "${INTERFACE}" root || true
sudo ip link set dev "${INTERFACE}" up || true
log_event "impairment_cleared"

# --------------- stop baseline collectors ----------
kill ${SAR_PID} ${IOSTAT_PID} || true
kill ${STATUS_PID} || true
if [ -n "${PG_PID}" ]; then
    kill ${PG_PID} || true
fi

# --------------- post-run Ceph state -----------------
ceph -s > "${LOGDIR}/ceph_status_post.log"
ceph osd dump --format=json-pretty > "${LOGDIR}/osd_dump.json"
