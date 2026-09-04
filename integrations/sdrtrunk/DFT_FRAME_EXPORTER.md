# DftFrameExporter (CopIXus/sdrtrunk)

Implemented in the GPLv3 fork. Source: [patch/DftFrameExporter.java](patch/DftFrameExporter.java). Isolated from decoder/audio paths.

## Hook

`SpectralDisplayPanel` registers the exporter on `ComplexDecibelConverter` (same DFT stream as the native waterfall).

## Behavior

1. Convert dB bins to linear power
2. Average-downsample to 512 bins
3. Rate-limit to ~8 frames per second
4. If `spectrum_export_enabled`, write one NDJSON line per frame to
   `spectrum_export_host`:`spectrum_export_port` (default `127.0.0.1:29501`)

## Frame schema

See [README.md](README.md) and `tests/fixtures/spectrum_frame.json` in RadioTAK.

## Preferences

- `spectrum_export_enabled` (bool)
- `spectrum_export_host` (string)
- `spectrum_export_port` (int, default 29501)

Do not change geo export on port 29500.
