#!/usr/bin/env bash
# --------------------------------------------------------------
# Usage: ./collect_metrics.sh start <run_id>
#        ./collect_metrics.sh stop  <run_id>
# --------------------------------------------------------------

set -euo pipefail

ACTION=$1
RUNID=$2
BASEDIR="metrics/${RUNID}"
mkdir -p "${BASEDIR}"

INTERFACE="${INTERFACE:-vmbr0.30}"   # override per host if needed

case "${ACTION}" in
    start)
        echo "Starting continuous collectors for ${RUNID}"
        sar -u 1 > "${BASEDIR}/cpu.sar" &
        echo $! > "${BASEDIR}/sar.pid"
        iostat -xz 1 > "${BASEDIR}/disk.iostat" &
        echo $! > "${BASEDIR}/iostat.pid"
        while true; do
            ifconfig "${INTERFACE}" | grep 'RX packets' >> "${BASEDIR}/net.txt"
            sleep 1
        done &
        echo $! > "${BASEDIR}/net.pid"
        ;;
    stop)
        echo "Stopping collectors for ${RUNID}"
        kill $(cat "${BASEDIR}"/*.pid) || true
        ;;
    *)
        echo "Invalid action. Use start|stop."
        exit 1
        ;;
esac
