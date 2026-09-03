#!/usr/bin/env bash
set -euo pipefail
systemctl stop sdrtrunk.service 2>/dev/null || true
systemctl disable sdrtrunk.service 2>/dev/null || true
rm -f /etc/systemd/system/sdrtrunk.service
systemctl daemon-reload
echo "SDR Location Gateway uninstalled (SDRTrunk files in /var/lib/radiotak/sdrtrunk retained)."
