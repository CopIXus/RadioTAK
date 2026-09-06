# AudioFrameExporter (CopIXus/sdrtrunk)

Implemented in the GPLv3 fork. Source: [patch/AudioFrameExporter.java](patch/AudioFrameExporter.java). Consumer of `AudioSegment` only.

## Hook

`SDRTrunk` registers the exporter with `ChannelProcessingManager.addAudioSegmentListener`, next to `AudioPlaybackManager`. See [patch/AUDIO_SEGMENT_HOOK.md](patch/AUDIO_SEGMENT_HOOK.md).

## Behavior

1. Follow each `AudioSegment` as buffers arrive (8 kHz float)
2. Batch ~100 ms, convert to PCM s16le, Base64
3. Encrypted segments: NDJSON silence markers, **never PCM**
4. If `audio_export_enabled`, write one NDJSON line per batch to
   `audio_export_host`:`audio_export_port` (default `127.0.0.1:29502`)

## Frame schema

```json
{
  "schema": "sdr2tak.audio.v1",
  "encrypted": false,
  "silence": false,
  "end": false,
  "sample_rate": 8000,
  "channels": 1,
  "encoding": "pcm_s16le",
  "talkgroup": "1471",
  "radio_id": "1234567",
  "pcm_b64": "...",
  "ts": 1725372137.315
}
```

## Preferences

- `audio_export_enabled` (bool, default true)
- `audio_export_host` (string, default 127.0.0.1)
- `audio_export_port` (int, default **29502**)
