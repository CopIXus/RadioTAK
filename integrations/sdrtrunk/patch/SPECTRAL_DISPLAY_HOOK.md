# SpectralDisplayPanel hook (CopIXus/sdrtrunk)

Apply on the `radiotak-exporters` branch next to `DftFrameExporter`. Do not change decoder or audio paths.

## `init()` — pass the displayed tuner into the exporter

```java
mDftFrameExporter = new DftFrameExporter(mOverlayPanel, mChannelModel, this::getTuner);
mDFTConverter.addListener(mDftFrameExporter);
```

The two-argument constructor still works; without `this::getTuner` the exporter falls back to OverlayPanel. RadioTAK stamps the listening control channel into `tuner_configuration.json` so `showFirstTuner()` is not left at 101.1 MHz.

## `showTuner(Tuner tuner)` — after `mTuner = tuner` and the frequency/sample-rate sync

```java
if(mDftFrameExporter != null)
{
    mDftFrameExporter.bindTuner(mTuner);
}
```

## `clearTuner()` — before removing buffer listeners

```java
if(mDftFrameExporter != null)
{
    mDftFrameExporter.bindTuner(null);
}
```

`v0.6.2-radiotak.3` includes this hook. `v0.6.2-radiotak.4` labels `f_min`/`f_max` from the live tuner only (no playlist-axis remap).
