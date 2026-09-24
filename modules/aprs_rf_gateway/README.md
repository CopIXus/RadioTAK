# APRS RF Gateway (Raspberry Pi)

RX-only APRS decode via **Direwolf** into RadioTAK: positions use the same `sdr2tak.location.v1` schema and **LocationPipeline** as SDRTrunk (in-process — no TCP loopback), and APRS text messages become ATAK **GeoChat** in room `APRS`.

## Pi setup

1. Enroll your TAK Server in the RadioTAK **TAK** UI (mTLS already used for CoT).
2. Marketplace → install **APRS RF Gateway** (pulls `direwolf` + `rtl-sdr` via apt, installs `direwolf-aprs.service`).
3. Open **APRS** in the sidebar: set **MYCALL** to your amateur callsign-SSID for logging (RX-only).
4. Start **Direwolf**. RadioTAK’s in-process KISS client connects to `127.0.0.1:8001`.
5. Either enable **Auto-approve heard callsigns for TAK** (uses Settings default stale), or allowlist callsigns under **Units** (`RADIOTAK-APRS-{CALL}`) and enable **Forward to TAK**.

Default RF: **144.390 MHz**, 1200 baud, `rtl_fm` → Direwolf stdin.

```text
RTL-SDR → rtl_fm → Direwolf → KISS :8001 → aprs_rf_gateway
                                      ├─ positions → LocationPipeline → CoT
                                      └─ messages  → GeoChat b-t-f → tak_registry
```

### Feeds: SDRTrunk + APRS

| Combo | Works? | Notes |
|-------|--------|--------|
| **APRS-IS + SDRTrunk** | Yes | Internet feed needs no dongle. Enable IS; leave Direwolf stopped. |
| **APRS RF + SDRTrunk** | Needs 2 SDRs | Set **RTL device index** to the free stick. Soft exclusivity in the UI stops the peer only when a single tuner is present. |
| **APRS RF alone** | Yes | Start Direwolf; SDRTrunk must be stopped if only one stick. |

On VM 700 the passed-through stick is often an **Airspy** — the launcher auto-detects it and uses `airspy_rx | csdr | direwolf` (needs the `airspy` + `csdr` packages from apt).

### Marker colors

RF and APRS-IS positions use separate TAK marker colors (defaults green / blue) so you can tell them apart on the map. Set them on the APRS page; they override TAK **Marker Appearance** for APRS CoTs only.

### Optional APRS-IS

Enable on the APRS page with a geographic filter (e.g. `r/36.35/-82.21/50` for East TN). Passcode `-1` is fine for RX-only.

## License note

Receiving/decoding APRS does not require a license. **Transmitting** APRS, digipeating, or IGating does — an amateur license is required. GMRS (e.g. WSDU493) does **not** authorize APRS TX. This module is RX-only by design.

## Config paths (appliance)

| Path | Purpose |
|------|---------|
| `/var/lib/radiotak/modules/aprs_rf_gateway/direwolf.conf` | Direwolf (MYCALL, KISSPORT 8001) |
| `/var/lib/radiotak/modules/aprs_rf_gateway/settings.json` | UI settings |
| `/usr/local/bin/radiotak-direwolf-rtl` | `rtl_fm \| direwolf` launcher |
| `direwolf-aprs.service` | systemd unit |

## Out of scope

- APRS TX / digipeater / IGate from RadioTAK  
- TAK GeoChat → RF APRS  
- Using a handheld as the APRS modem  
