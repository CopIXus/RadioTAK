# DftFrameExporter patch sketch (CopIXus/sdrtrunk)

Implement in the GPLv3 fork only. Keep isolated from decoder/audio paths.

## Hook

Subscribe to `DFTResultsListener` / results from `ComplexDftProcessor`.

## Behavior

1. Downsample magnitude bins to ~512 values
2. Rate-limit to 5–10 frames per second
3. If `spectrum_export_enabled`, write one NDJSON line per frame to
   `spectrum_export_host`:`spectrum_export_port` (default `127.0.0.1:29501`)

## Frame schema

See [README.md](README.md) and `tests/fixtures/spectrum_frame.json` in RadioTAK.

## Preferences

- `spectrum_export_enabled` (bool)
- `spectrum_export_host` (string)
- `spectrum_export_port` (int, default 29501)

Do not change geo export on port 29500.
