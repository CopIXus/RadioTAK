# SDRTrunk integration

RadioTAK does **not** reimplement P25/DMR demodulation. It uses [SDRTrunk](https://github.com/DSheirer/sdrtrunk) as the decoder engine.

## Runtime

- SDRTrunk Linux AArch64 bundle
- Run under **Xvfb** as `sdrtrunk.service` (JavaFX requires a display)
- Optional noVNC embed for native spectrum/waterfall debugging

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

`DftFrameExporter` downsamples FFT bins for the web canvas waterfall.

## Fallback

`bin/radiotak replay tests/fixtures/*.jsonl` exercises the full pipeline without RF.
