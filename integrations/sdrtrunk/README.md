# SDRTrunk geo / spectrum export (CopIXus fork, GPLv3)

Implemented in `CopIXus/sdrtrunk`. Java sources in [patch/](patch/) are the canonical copies kept with RadioTAK.

## GeoEventJsonExporter (`:29500`)

Registered next to `MapService` as a `Listener<IDecodeEvent>`. On `PlottableDecodeEvent` with `isValidLocation()`, emits one NDJSON line matching [event-schema.json](event-schema.json). Live Events / Units / TAK only update when these GPS lines arrive — RF audio or waterfall energy is not enough.

## DftFrameExporter (`:29501`)

Subscribes to `ComplexDecibelConverter` (same DFT results as the SDRTrunk waterfall). Converts dB to linear power, downsamples to 512 bins at ~8 fps, and streams NDJSON to RadioTAK.

Example frame (`sdr2tak.spectrum.v1`):

```json
{
  "schema": "sdr2tak.spectrum.v1",
  "bins": [0.01, 0.02, 0.5, 0.8, 0.4],
  "f_min": 850500000,
  "f_max": 852000000,
  "cc_hz": [851012500, 851512500],
  "ts": 1725372137.315
}
```

- `bins`: linear magnitudes, target length **512**
- `f_min` / `f_max`: tuner sweep edges in Hz. Prefer the live tuner LO feeding the DFT, not a stale `showFirstTuner()` overlay. When a processing playlist channel sits outside the spectral-panel window, the span is recentered on those CCs (same bandwidth) and the original overlay is copied to `panel_f_min` / `panel_f_max`.
- `cc_hz`: playlist control-channel markers (cyan lines on the canvas)

`SpectralDisplayPanel` should construct the exporter as:

```java
mDftFrameExporter = new DftFrameExporter(mOverlayPanel, mChannelModel, this::getTuner);
```

and call `mDftFrameExporter.bindTuner(mTuner)` from `showTuner` / `clearTuner` so frequency-change events update labels even if OverlayPanel misses them. The two-argument constructor remains for older hook lines.

## Preferences (`SDRTrunk.properties`)

- `geo_event_export_enabled` (default true)
- `geo_event_export_host` (default 127.0.0.1)
- `geo_event_export_port` (default 29500)
- `spectrum_export_enabled` (bool, default true)
- `spectrum_export_host` (default 127.0.0.1)
- `spectrum_export_port` (default **29501**)

RadioTAK writes those keys when it rebuilds the playlist. Spectrum listen bind is also in `settings.json` under `spectrum`.

Do not change decoder or audio behavior. Keep the patch isolated for easy rebase.
