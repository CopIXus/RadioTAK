# SpectralDisplayPanel hook (CopIXus/sdrtrunk)

Apply on the `radiotak-exporters` branch next to `DftFrameExporter`. Do not change decoder or audio paths.

## `init()` — pass the displayed tuner into the exporter

```java
mDftFrameExporter = new DftFrameExporter(mOverlayPanel, mChannelModel, this::getTuner);
mDFTConverter.addListener(mDftFrameExporter);
```

The two-argument constructor still works; without `this::getTuner` the exporter falls back to OverlayPanel, then to a processing playlist channel.

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

RadioTAK recenters `f_min`/`f_max` in `spectrum.py` even before this hook ships, so cyan CC markers work against an already-installed `v0.6.2-radiotak.2` jar. `v0.6.2-radiotak.3` includes this hook.
