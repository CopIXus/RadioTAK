# SDRTrunk geo / spectrum export (CopIXus fork, GPLv3)

Implemented in `CopIXus/sdrtrunk`. Java sources in [patch/](patch/) are the canonical copies kept with RadioTAK.

## GeoEventJsonExporter (`:29500`)

Registered next to `MapService` as a `Listener<IDecodeEvent>`. On `PlottableDecodeEvent` with `isValidLocation()`, emits one NDJSON line matching [event-schema.json](event-schema.json). Voice/data calls, encrypted traffic, analog ANI (`ID_ANI`), affiliation, and GPS/LRRP without a plottable fix emit [decode-event-schema.json](decode-event-schema.json) so Units still show the radio ID. RF audio or waterfall energy alone is not enough.

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
- `f_min` / `f_max`: live tuner sweep edges in Hz (the stick feeding the DFT, not a relabeled playlist)
- `cc_hz`: playlist control-channel markers (cyan lines on the canvas)

`SpectralDisplayPanel` should construct the exporter as:

```java
mDftFrameExporter = new DftFrameExporter(mOverlayPanel, mChannelModel, this::getTuner);
```

and call `mDftFrameExporter.bindTuner(mTuner)` from `showTuner` / `clearTuner` so frequency-change events update labels even if OverlayPanel misses them. The two-argument constructor remains for older hook lines.

## AudioFrameExporter (`:29502`)

Registered next to `AudioPlaybackManager` as a `Listener<AudioSegment>`. Batches ~100 ms of 8 kHz PCM as `sdr2tak.audio.v1`. Encrypted segments emit silence markers only. See [AUDIO_FRAME_EXPORTER.md](AUDIO_FRAME_EXPORTER.md).

## Preferences (`SDRTrunk.properties`)

- `geo_event_export_enabled` (default true)
- `geo_event_export_host` (default 127.0.0.1)
- `geo_event_export_port` (default 29500)
- `spectrum_export_enabled` (bool, default true)
- `spectrum_export_host` (default 127.0.0.1)
- `spectrum_export_port` (default **29501**)
- `audio_export_enabled` (bool, default true)
- `audio_export_host` (default 127.0.0.1)
- `audio_export_port` (default **29502**)

RadioTAK writes those keys when it rebuilds the playlist. Spectrum listen bind is also in `settings.json` under `spectrum`; audio under `audio`.

Do not change vocoder / mixer / playback. `AudioFrameExporter` is a consumer of `AudioSegment`, same as recording. Keep patches isolated for easy rebase.
