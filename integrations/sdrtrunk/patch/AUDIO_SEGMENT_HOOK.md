# AudioSegment hook (CopIXus/sdrtrunk)

Apply on the `radiotak-exporters` branch next to `AudioFrameExporter`. This is a **consumer** of already-decoded `AudioSegment`s — same registration as playback / recording / streaming. Do not change vocoder, mixer, or JMBE paths.

## `SDRTrunk` constructor — after the other audio-segment listeners

```java
mPlaylistManager.getChannelProcessingManager().addAudioSegmentListener(duplicateCallDetector);
mPlaylistManager.getChannelProcessingManager().addAudioSegmentListener(audioPlaybackManager);
mPlaylistManager.getChannelProcessingManager().addAudioSegmentListener(mAudioRecordingManager);
mPlaylistManager.getChannelProcessingManager().addAudioSegmentListener(mAudioStreamingManager);
mPlaylistManager.getChannelProcessingManager().addAudioSegmentListener(new AudioFrameExporter());
```

Import:

```java
import io.github.dsheirer.export.AudioFrameExporter;
```

Encrypted segments emit silence markers only (`encrypted: true`, no `pcm_b64`). Clear P25/DMR voice still requires JMBE in the decoder lib folder, same as local SDRTrunk playback.
