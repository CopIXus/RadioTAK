#!/usr/bin/env bash
# Install Direwolf + rtl-sdr and wire direwolf-aprs.service for RadioTAK (Pi/Debian).
set -euo pipefail

INSTALL_DIR="${RADIOTAK_INSTALL_DIR:-/opt/radiotak}"
DATA_DIR="${RADIOTAK_DATA_DIR:-/var/lib/radiotak}"
MOD_DIR="$DATA_DIR/modules/aprs_rf_gateway"
SRC="$INSTALL_DIR/modules/aprs_rf_gateway"

die() { echo "aprs-install: $*" >&2; exit 1; }

export DEBIAN_FRONTEND=noninteractive

echo "Installing direwolf, rtl-sdr, airspy, sox…"
apt-get install -y -qq direwolf rtl-sdr sox || die "apt-get install failed (need direwolf)"
apt-get install -y -qq airspy libairspy0 || echo "airspy package skipped" >&2
# csdr is not in Debian bookworm — Airspy RF needs a separate build; APRS-IS still works.

# APRS packet parse dependency for the in-process gateway
if [[ -x "$INSTALL_DIR/.venv/bin/pip" ]]; then
  echo "Installing aprslib into RadioTAK venv…"
  "$INSTALL_DIR/.venv/bin/pip" install -q 'aprslib>=0.7.2' || die "pip install aprslib failed"
fi

mkdir -p "$MOD_DIR/logs"
if [[ -f "$SRC/direwolf/direwolf.conf" ]]; then
  if [[ ! -f "$MOD_DIR/direwolf.conf" ]]; then
    cp "$SRC/direwolf/direwolf.conf" "$MOD_DIR/direwolf.conf"
  fi
fi
install -m 0755 "$SRC/scripts/start-direwolf-rtl.sh" /usr/local/bin/radiotak-direwolf-rtl

# Same RTL blacklist as SDR module — userspace rtl_fm needs the stick free of DVB drivers.
cat > /etc/modprobe.d/radiotak-rtl-blacklist.conf <<'EOF'
blacklist dvb_usb_rtl28xxu
blacklist rtl2832_sdr
blacklist rtl2832
blacklist dvb_usb_v2
EOF
for m in dvb_usb_rtl28xxu rtl2832_sdr rtl2832 dvb_usb_v2 dvb_core; do
  rmmod "$m" 2>/dev/null || true
done
udevadm control --reload-rules 2>/dev/null || true
udevadm trigger --subsystem-match=usb 2>/dev/null || true

usermod -aG audio,plugdev radiotak 2>/dev/null || true
chown -R radiotak:radiotak "$MOD_DIR" 2>/dev/null || true

# Default settings.json if missing
if [[ ! -f "$MOD_DIR/settings.json" ]]; then
  cat > "$MOD_DIR/settings.json" <<'JSON'
{
  "mycall": "N0CALL-15",
  "kiss_host": "127.0.0.1",
  "kiss_port": 8001,
  "enable_rf": true,
  "enable_is": true,
  "aprs_is_server": "rotate.aprs2.net",
  "aprs_is_port": 14580,
  "aprs_is_passcode": -1,
  "aprs_is_filter": "r/36.35/-82.21/50",
  "chatroom": "APRS",
  "marti_dest_group": "",
  "rtl_device": "0",
  "rtl_gain": 40,
  "frequency_hz": 144390000,
  "sdr_backend": "auto"
}
JSON
  chown radiotak:radiotak "$MOD_DIR/settings.json"
fi

# Apply MYCALL from settings into direwolf.conf when present
python3 - <<'PY' || true
import json, re
from pathlib import Path
mod = Path("/var/lib/radiotak/modules/aprs_rf_gateway")
conf = mod / "direwolf.conf"
settings = mod / "settings.json"
if conf.exists() and settings.exists():
    data = json.loads(settings.read_text(encoding="utf-8"))
    call = (data.get("mycall") or "N0CALL-15").strip().upper()
    text = conf.read_text(encoding="utf-8")
    text2 = re.sub(r"(?m)^MYCALL\s+\S+", f"MYCALL {call}", text)
    if text2 != text:
        conf.write_text(text2, encoding="utf-8")
PY

cat > /etc/systemd/system/direwolf-aprs.service <<EOF
[Unit]
Description=Direwolf APRS RX (RadioTAK) via RTL-SDR/Airspy
After=network.target
Conflicts=sdrtrunk.service

[Service]
Type=simple
User=radiotak
Group=radiotak
SupplementaryGroups=audio plugdev
Environment=RADIOTAK_DIREWOLF_CONF=$MOD_DIR/direwolf.conf
Environment=HOME=$DATA_DIR
WorkingDirectory=$MOD_DIR
ExecStart=/usr/local/bin/radiotak-direwolf-rtl
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable direwolf-aprs.service || true
# Do not auto-start — operator starts from the APRS UI (avoids stealing the SDR from SDRTrunk).
echo "APRS RF Gateway dependencies installed."
echo "Configure MYCALL on the APRS page, then start direwolf-aprs.service."
echo "Note: direwolf-aprs Conflicts with sdrtrunk — use a second RTL-SDR or stop SDRTrunk first."
