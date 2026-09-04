# SDRTrunk integration

RadioTAK does **not** reimplement P25/DMR demodulation. It uses [SDRTrunk](https://github.com/DSheirer/sdrtrunk) as the decoder engine.

## Runtime

- SDRTrunk Linux AArch64 bundle
- Run under **Xvfb** as `sdrtrunk.service` (JavaFX requires a display)
- Playlist is written from the RadioTAK **SDR** page (`/modules/sdr`): type control-channel MHz, save, start decoder
- File: `/var/lib/radiotak/SDRTrunk/playlist/default.xml` (SDRTrunk playlist v4 — this is the path SDRTrunk actually loads)
- RadioTAK **Listen** toggles write that file and restart `sdrtrunk`. Only listening systems are included. One RTL-SDR typically runs one trunked system at a time.
- Optional: x11vnc for the native SDRTrunk GUI if you need spectrum debugging

Do **not** enter a random voice frequency for trunked P25/DMR — enter the **control channel** (and alternates). GPS telemetry is decoded from the system, then allowlisted under **Units** before it is forwarded to TAK.

## Geo events

GPS on P25/DMR is a **separate TCP path** from the waterfall. RadioTAK listens on **127.0.0.1:29500** for `sdr2tak.location.v1` NDJSON. Stock SDRTrunk never sends that. The CopIXus fork's `GeoEventJsonExporter` exports `PlottableDecodeEvent` when a radio reports a valid lat/lon:

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

Until a patched build is installed, Live Events and Units stay empty even while the decoder is running. Preferences: `geo_event_export_enabled`, `geo_event_export_host`, `geo_event_export_port`. RadioTAK writes those into `SDRTrunk.properties` when it writes the playlist.

## Spectrum export

`DftFrameExporter` downsamples FFT bins (~512) and streams NDJSON to RadioTAK on **127.0.0.1:29501**. Enable with `spectrum_export_enabled`. Installer tag: `v0.6.2-radiotak.1` from `CopIXus/sdrtrunk` releases. Stock 0.6.1 leaves the canvas black.

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
