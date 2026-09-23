#!/usr/bin/env bash
# Pipe RTL-SDR FM demod into Direwolf at 24 kHz (US VHF APRS 144.390 MHz).
# RX-only — no TX, digipeat, or IGate.
set -euo pipefail

CONF="${RADIOTAK_DIREWOLF_CONF:-/var/lib/radiotak/modules/aprs_rf_gateway/direwolf.conf}"
SETTINGS="${RADIOTAK_APRS_SETTINGS:-/var/lib/radiotak/modules/aprs_rf_gateway/settings.json}"
RATE="${APRS_SAMPLE_RATE:-24000}"

# Defaults; overridden from settings.json when present
FREQ="${APRS_FREQ_HZ:-144390000}"
GAIN="${APRS_RTL_GAIN:-40}"
DEVICE="${APRS_RTL_DEVICE:-0}"

if [[ -f "$SETTINGS" ]] && command -v python3 >/dev/null; then
  eval "$(python3 - <<PY
import json
from pathlib import Path
p = Path("$SETTINGS")
try:
    d = json.loads(p.read_text(encoding="utf-8"))
except Exception:
    raise SystemExit(0)
print(f'FREQ={int(d.get("frequency_hz") or 144390000)}')
print(f'GAIN={int(d.get("rtl_gain") or 40)}')
print(f'DEVICE={str(d.get("rtl_device") or "0")!r}')
PY
)"
fi

command -v rtl_fm >/dev/null || { echo "rtl_fm not found (install rtl-sdr)" >&2; exit 1; }
command -v direwolf >/dev/null || { echo "direwolf not found" >&2; exit 1; }
[[ -f "$CONF" ]] || { echo "missing Direwolf config: $CONF" >&2; exit 1; }

exec rtl_fm -d "$DEVICE" -f "$FREQ" -M fm -s "$RATE" -g "$GAIN" - \
  | direwolf -c "$CONF" -r "$RATE" -t 0 -
