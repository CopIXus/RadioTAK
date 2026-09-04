# SDRTrunk geo / spectrum export patch notes

This directory documents the planned patch for `CopIXus/sdrtrunk` (GPLv3).

## GeoEventJsonExporter

Hook where `MapService.receive` accepts `PlottableDecodeEvent`:

- Prefer: implement `IDecodeEventListener` / mirror MapService subscription
- Emit NDJSON to `geo_event_export_host:geo_event_export_port` when enabled
- Schema: see `event-schema.json`

## DftFrameExporter (Phase 6b)

Subscribe to `DFTResultsListener` from `ComplexDftProcessor`, downsample to ~512 bins @ 5–10 fps, and emit one NDJSON line per frame over TCP.

Example frame (schema `sdr2tak.spectrum.v1`):

```json
{
  "schema": "sdr2tak.spectrum.v1",
  "bins": [ -72.1, -71.8, -70.5 ],
  "f_min": 850500000,
  "f_max": 852000000,
  "cc_hz": [851012500, 851512500],
  "ts": 1725372137.315
}
```

- `bins`: magnitude array, target length **512** after downsampling in the exporter (RadioTAK may downsample further if oversized).
- `f_min` / `f_max`: sweep edges in Hz for the canvas waterfall axis labels.
- `cc_hz`: optional control-channel markers (cyan vertical lines on the waterfall).
- Default listener: **`127.0.0.1:29501`** (`SpectrumHub` in RadioTAK).

## Preferences

- `geo_event_export_enabled` (bool)
- `geo_event_export_host` (default 127.0.0.1)
- `geo_event_export_port` (default 29500)
- `spectrum_export_enabled` (bool)
- `spectrum_export_host` (default 127.0.0.1)
- `spectrum_export_port` (default **29501**)

RadioTAK mirrors spectrum prefs in `settings.json` under the `spectrum` key (`enabled`, `host`, `port`).

Do not change decoder or audio behavior. Keep patch isolated for easy rebase.
