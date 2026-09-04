# SDRTrunk integration

RadioTAK does **not** reimplement P25/DMR demodulation. It uses [SDRTrunk](https://github.com/DSheirer/sdrtrunk) as the decoder engine.

## Runtime

- SDRTrunk Linux AArch64 bundle
- Run under **Xvfb** as `sdrtrunk.service` (JavaFX requires a display)
- Playlist is written from the RadioTAK **SDR** page (`/modules/sdr`): type control-channel MHz, save, start decoder
- File: `/var/lib/radiotak/.sdrtrunk/playlist/default.xml` (SDRTrunk playlist v2)
- Optional: x11vnc for the native SDRTrunk GUI if you need spectrum debugging

Do **not** enter a random voice frequency for trunked P25/DMR — enter the **control channel** (and alternates). GPS telemetry is decoded from the system, then allowlisted under **Units** before it is forwarded to TAK.

## Geo events

Upstream CSV event logs do not reliably carry lat/lon for all GPS paths. RadioTAK uses a small fork patch (`CopIXus/sdrtrunk`) that exports `PlottableDecodeEvent` as NDJSON:

```json
{
  "schema": "sdr2tak.location.v1",
  "decoder": "sdrtrunk",
  "protocol": "P25",
  "radio_id": "1234567",
  "latitude": 36.29531,
  "longitude": -82.27922,
  "observed_at": "2026-09-03T15:42:17.315Z"
}
```

Preferences: `geo_event_export_enabled`, `geo_event_export_host`, `geo_event_export_port`.

## Spectrum export (Phase 6b)

`DftFrameExporter` downsamples FFT bins (~512) and streams NDJSON to RadioTAK on **127.0.0.1:29501** by default. Enable with `spectrum_export_enabled` (and optional `spectrum_export_host` / `spectrum_export_port`).

### Canvas waterfall

The Console dashboard and **SDR** module render frames in a canvas waterfall (`waterfall.js` over WebSocket). Each frame carries `bins`, `f_min`, `f_max`, and optional `cc_hz` control-channel markers. Use it to confirm the decoder is centered on the expected spectrum segment.

### noVNC fallback

When you need the native SDRTrunk GUI (full spectrum view, channel editor, tuner dialogs), use the **noVNC** iframe on the Console dashboard. SDRTrunk still runs under Xvfb; x11vnc exposes the display for browser access.

### Hearing gauges

The Console **hearing gauges** summarize decoder activity without FFT:

- **Messages / min** — geo/decode events in the last 60 s window
- **CC lock** — proxy for control-channel activity (`locked` / `intermittent` / `listening` / `idle`)
- **Last event** — age of the most recent heard event

Gauges turn green when the decoder is running and traffic is recent; amber when intermittent; red when idle or decoder stopped.

## Fallback

`bin/radiotak replay tests/fixtures/*.jsonl` exercises the full pipeline without RF.
