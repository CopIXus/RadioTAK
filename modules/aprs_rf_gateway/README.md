# APRS RF Gateway (Raspberry Pi)

RX-only APRS decode via **Direwolf** into RadioTAK: positions use the same `sdr2tak.location.v1` schema and **LocationPipeline** as SDRTrunk (in-process — no TCP loopback), and APRS text messages become ATAK **GeoChat** in room `APRS`.

## Pi setup

1. Enroll your TAK Server in the RadioTAK **TAK** UI (mTLS already used for CoT).
2. Marketplace → install **APRS RF Gateway** (pulls `direwolf` + `rtl-sdr` via apt, installs `direwolf-aprs.service`).
3. Open **APRS** in the sidebar: set **MYCALL** to your amateur callsign-SSID for logging (RX-only).
4. Start **Direwolf**. RadioTAK’s in-process KISS client connects to `127.0.0.1:8001`.
5. Allowlist heard callsigns under **Units** (`RADIOTAK-APRS-{CALL}`) and enable **Forward to TAK**.

Default RF: **144.390 MHz**, 1200 baud, `rtl_fm` → Direwolf stdin.

```text
RTL-SDR → rtl_fm → Direwolf → KISS :8001 → aprs_rf_gateway
                                      ├─ positions → LocationPipeline → CoT
                                      └─ messages  → GeoChat b-t-f → tak_registry
```

### Dongle conflict

`direwolf-aprs.service` **Conflicts** with `sdrtrunk.service`. Use a **second RTL-SDR** for APRS, or stop SDRTrunk while listening to APRS. Sound-card audio from a radio speaker is also fine: edit `/var/lib/radiotak/modules/aprs_rf_gateway/direwolf.conf` to set `ADEVICE` and run Direwolf without the rtl_fm wrapper.

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
