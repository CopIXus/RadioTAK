#!/usr/bin/env bash
# Pipe SDR FM demod into Direwolf (US VHF APRS 144.390 MHz). RX-only.
# Prefers RTL-SDR (rtl_fm). Falls back to Airspy (airspy_rx + csdr) when present.
set -euo pipefail

CONF="${RADIOTAK_DIREWOLF_CONF:-/var/lib/radiotak/modules/aprs_rf_gateway/direwolf.conf}"
SETTINGS="${RADIOTAK_APRS_SETTINGS:-/var/lib/radiotak/modules/aprs_rf_gateway/settings.json}"
RATE="${APRS_SAMPLE_RATE:-24000}"

FREQ="${APRS_FREQ_HZ:-144390000}"
GAIN="${APRS_RTL_GAIN:-40}"
DEVICE="${APRS_RTL_DEVICE:-0}"
BACKEND="${APRS_SDR_BACKEND:-auto}"

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
print(f'BACKEND={str(d.get("sdr_backend") or "auto")!r}')
PY
)"
fi

command -v direwolf >/dev/null || { echo "direwolf not found" >&2; exit 1; }
[[ -f "$CONF" ]] || { echo "missing Direwolf config: $CONF" >&2; exit 1; }

pick_backend() {
  case "$BACKEND" in
    rtl|rtl-sdr|rtlsdr) echo rtl; return ;;
    airspy) echo airspy; return ;;
  esac
  if lsusb 2>/dev/null | grep -qiE '0bda:283[28]|Realtek.*RTL283'; then
    echo rtl
    return
  fi
  if lsusb 2>/dev/null | grep -qiE '1d50:60a1|Airspy'; then
    echo airspy
    return
  fi
  if command -v rtl_fm >/dev/null 2>&1; then
    echo rtl
    return
  fi
  if command -v airspy_rx >/dev/null 2>&1; then
    echo airspy
    return
  fi
  echo none
}

BE=$(pick_backend)
echo "aprs-direwolf: backend=$BE freq=$FREQ rate=$RATE" >&2

case "$BE" in
  rtl)
    command -v rtl_fm >/dev/null || { echo "rtl_fm not found (install rtl-sdr)" >&2; exit 1; }
    exec rtl_fm -d "$DEVICE" -f "$FREQ" -M fm -s "$RATE" -g "$GAIN" - \
      | direwolf -c "$CONF" -r "$RATE" -t 0 -
    ;;
  airspy)
    command -v airspy_rx >/dev/null || { echo "airspy_rx not found (install airspy)" >&2; exit 1; }
    command -v csdr >/dev/null || { echo "csdr not found (needed for Airspy FM demod → Direwolf)" >&2; exit 1; }
    # Debian airspy_rx: -f is MHz, -a sample rate, -r output file, -g linearity 0-21, -t 2=INT16_IQ
    AIRSPY_RATE=2500000
    DECIM=100
    AUDIO_RATE=$((AIRSPY_RATE / DECIM))
    FREQ_MHZ=$(python3 -c "print(f'{int(\"$FREQ\")/1e6:.6f}')")
    AG=${GAIN}
    if [[ "$AG" -gt 21 ]]; then AG=15; fi
    export LD_LIBRARY_PATH="/usr/local/lib:${LD_LIBRARY_PATH:-}"
    echo "aprs-direwolf: airspy ${FREQ_MHZ} MHz rate=${AIRSPY_RATE} → audio ${AUDIO_RATE}" >&2
    exec airspy_rx -r /dev/stdout -f "$FREQ_MHZ" -a "$AIRSPY_RATE" -t 2 -g "$AG" \
      | csdr convert -i s16 -o float \
      | csdr firdecimate "$DECIM" 0.05 \
      | csdr fmdemod \
      | csdr limit \
      | csdr convert -i float -o s16 \
      | direwolf -c "$CONF" -r "$AUDIO_RATE" -t 0 -
    ;;
  *)
    echo "No usable SDR backend (need RTL-SDR or Airspy)" >&2
    exit 1
    ;;
esac
