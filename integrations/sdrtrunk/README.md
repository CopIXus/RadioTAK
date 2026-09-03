# SDRTrunk geo / spectrum export patch notes

This directory documents the planned patch for `CopIXus/sdrtrunk` (GPLv3).

## GeoEventJsonExporter

Hook where `MapService.receive` accepts `PlottableDecodeEvent`:

- Prefer: implement `IDecodeEventListener` / mirror MapService subscription
- Emit NDJSON to `geo_event_export_host:geo_event_export_port` when enabled
- Schema: see `event-schema.json`

## DftFrameExporter (Phase 6b)

Subscribe to `DFTResultsListener` from `ComplexDftProcessor`, downsample to ~512 bins @ 5–10 fps.

## Preferences

- `geo_event_export_enabled` (bool)
- `geo_event_export_host` (default 127.0.0.1)
- `geo_event_export_port` (default 29500)
- `spectrum_export_enabled` / host / port

Do not change decoder or audio behavior. Keep patch isolated for easy rebase.
