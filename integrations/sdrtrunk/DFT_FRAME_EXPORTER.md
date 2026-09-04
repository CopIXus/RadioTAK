# DftFrameExporter (CopIXus/sdrtrunk)

Implemented in the GPLv3 fork. Source: [patch/DftFrameExporter.java](patch/DftFrameExporter.java). Isolated from decoder/audio paths.

## Hook

`SpectralDisplayPanel` registers the exporter on `ComplexDecibelConverter` (same DFT stream as the native waterfall).

## Behavior

1. Convert dB bins to linear power
2. Average-downsample to 512 bins
3. Rate-limit to ~8 frames per second
4. Label `f_min`/`f_max` from, in order:
   1. Live tuner LO + bandwidth (`Supplier<Tuner>` / `bindTuner`)
   2. OverlayPanel (spectral display)
   3. First **processing** playlist channel, using the overlay bandwidth, when that channel sits outside the panel window (`showFirstTuner()` idle ~100 MHz)
5. If the axis was recentered, also emit `panel_f_min` / `panel_f_max` (the overlay span)
6. If `spectrum_export_enabled`, write one NDJSON line per frame to
   `spectrum_export_host`:`spectrum_export_port` (default `127.0.0.1:29501`)

## SpectralDisplayPanel hook

Keep the exporter isolated. In `SpectralDisplayPanel.init()`:

```java
mDftFrameExporter = new DftFrameExporter(mOverlayPanel, mChannelModel, this::getTuner);
mDFTConverter.addListener(mDftFrameExporter);
```

In `showTuner`, after the tuner is assigned:

```java
mDftFrameExporter.bindTuner(mTuner);
```

In `clearTuner`, before dropping the tuner:

```java
mDftFrameExporter.bindTuner(null);
```

## Frame schema

See [README.md](README.md) and `tests/fixtures/spectrum_frame.json` in RadioTAK.

## Preferences

- `spectrum_export_enabled` (bool)
- `spectrum_export_host` (string)
- `spectrum_export_port` (int, default 29501)

Do not change geo export on port 29500.
