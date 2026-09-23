#!/usr/bin/env bash
set -euo pipefail
systemctl stop direwolf-aprs.service 2>/dev/null || true
systemctl disable direwolf-aprs.service 2>/dev/null || true
rm -f /etc/systemd/system/direwolf-aprs.service
rm -f /usr/local/bin/radiotak-direwolf-rtl
systemctl daemon-reload
echo "APRS RF Gateway uninstalled (config under /var/lib/radiotak/modules/aprs_rf_gateway retained)."
