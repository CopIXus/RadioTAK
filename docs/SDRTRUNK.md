# SDRTrunk integration

RadioTAK does **not** reimplement P25/DMR demodulation. It uses [SDRTrunk](https://github.com/DSheirer/sdrtrunk) as the decoder engine.

## Runtime

- SDRTrunk Linux AArch64 bundle
- Run under **Xvfb** as `sdrtrunk.service` (JavaFX requires a display)
- Playlist is written from the RadioTAK **SDR** page (`/modules/sdr`): type control-channel MHz, save, start decoder
- File: `/var/lib/radiotak/SDRTrunk/playlist/default.xml` (SDRTrunk playlist v4 — this is the path SDRTrunk actually loads)
- RadioTAK **Listen** toggles write that file and restart `sdrtrunk`. Only listening systems are included. One RTL-SDR typically runs one trunked system at a time.
- Optional: x11vnc for the native SDRTrunk GUI if you need spectrum debugging

Do **not** enter a random voice frequency for trunked P25/DMR — enter the **control channel** (and alternates). GPS telemetry is decoded from the system, then allowlisted under **Units** before it is forwarded to TAK.

## Geo events

GPS on P25/DMR is a **separate TCP path** from the waterfall. RadioTAK listens on **127.0.0.1:29500** for `sdr2tak.location.v1` NDJSON. Stock SDRTrunk never sends that. The CopIXus fork's `GeoEventJsonExporter` exports `PlottableDecodeEvent` when a radio reports a valid lat/lon:

```json
{
  "schema": "sdr2tak.location.v1",
  "decoder": "sdrtrunk",
  "protocol": "P25",
  "radio_id": "1234567",
  "latitude": 36.29531,
  "longitude": -82.27922,
  "observed_at": "2026-09-03T15:42:17.315Z"
}
```

Until a patched build is installed, Live Events and Units stay empty even while the decoder is running. Preferences: `geo_event_export_enabled`, `geo_event_export_host`, `geo_event_export_port`, `traffic_keys_path`. RadioTAK writes those into `SDRTrunk.properties` when it writes the playlist.

## Encrypted calls

The same `:29500` feed also accepts `sdr2tak.decode.v1` (no lat/lon). The CopIXus exporter emits those for voice/data calls, including `CALL_ENCRYPTED`, so Live Events / Units can show **Encrypted — no GPS** instead of looking idle.

When IdentifierCollection has the values, the exporter also sends system ID, WACN, NAC, RFSS, site, timeslot, downlink/uplink frequency, talker alias, source/destination type, patch group, unit/user status, LRA, structured ALGID/KID, `encryption_header_present`, duration, and Message Indicator (only if already present in call details). RadioTAK archives that metadata. See [ENCRYPTION-ARCHIVE.md](ENCRYPTION-ARCHIVE.md).

```json
{
  "schema": "sdr2tak.decode.v1",
  "decoder": "sdrtrunk",
  "protocol": "P25",
  "radio_id": "1234567",
  "talkgroup": "11025",
  "encrypted": true,
  "algorithm_id": 132,
  "key_id": 1,
  "system_id": "2A5",
  "wacn": "BEE00",
  "nac": "2AC",
  "site_id": "50",
  "source_type": "RADIO",
  "destination_type": "TALKGROUP",
  "encryption_header_present": true,
  "key_loaded": false,
  "observed_at": "2026-09-04T15:00:00Z"
}
```

Authorized traffic keys are entered on the SDR page and written to `/var/lib/radiotak/SDRTrunk/traffic_keys.json` (mode 0600). SDRTrunk does not decrypt P25/DMR audio; RadioTAK uses the file to match ALGID+KID and label events **key on file**.

## Spectrum export

`DftFrameExporter` downsamples FFT bins (~512) and streams NDJSON to RadioTAK on **127.0.0.1:29501**. Enable with `spectrum_export_enabled`. Installer tag: `v0.6.2-radiotak.5` from `CopIXus/sdrtrunk` releases. Stock 0.6.1 leaves the canvas black.

The exporter is registered on `SpectralDisplayPanel`'s `ComplexDecibelConverter`, so it only produces frames once SDRTrunk has a tuner shown in its spectral display. Under Xvfb that happens automatically (`showFirstTuner()` after the main window opens) — roughly 50 s after `sdrtrunk.service` starts on a Pi 4. If `spectral.display.enabled=false` is ever set in `SDRTrunk.properties`, no frames are exported.

### Keeping the decoder build current

The decoder binary is **not** part of the RadioTAK git checkout; it is a zip unpacked by `modules/sdr_location_gateway/install.sh` into `/var/lib/radiotak/sdrtrunk/app`. Three paths keep it in step with the tag in `install.sh`:

1. **Startup self-heal** — `upgrade_decoder_on_startup()` (in `radiotak/services/modules.py`) checks `sdrtrunk_build_info()` ~20 s after RadioTAK starts and re-runs the module installer when the installed jar lacks `DftFrameExporter` or the `.radiotak-fork` marker differs from the expected tag.
2. **System → Update** — `update_now()` re-runs the installer right after `git checkout` when an upgrade is needed.
3. **SDR page → Upgrade decoder** — manual button; the page polls `/modules/sdr/status.json` and reloads when the upgrade finishes.

`install.sh` is idempotent: it skips the download when the marker already matches, and restarts `sdrtrunk` after an upgrade if it was running.

### Telling whether the SDR is working

`/modules/sdr/status.json` exposes what the page shows under the canvas:

- `feed.spectrum.clients` — exporter TCP connections on :29501 (1 when the fork build is running)
- `feed.spectrum.frames_received` / `last_frame_age` — frames are ~8 fps when a tuner is streaming
- `feed.geo.clients` / `lines_received` — GPS exporter connection and how many location lines have arrived (stays 0 until a radio actually transmits lat/lon)
- `feed.audio.clients` / `pcm_frames` / `encrypted_frames` — talkgroup audio exporter on :29502
- `build.has_exporters` — false means stock SDRTrunk
- `build.has_audio_exporter` — false means the fork is old enough to paint the waterfall but not to play Listen audio

### Canvas waterfall

The Console dashboard and **SDR** module render frames in a canvas waterfall (`waterfall.js` over WebSocket). Each frame carries `bins`, `f_min`, `f_max`, and optional `cc_hz` control-channel markers. Those edges are the tuner LO actually feeding the DFT. SDRTrunk’s idle default is 101.1 MHz; RadioTAK stamps the listening control channel into `SDRTrunk/configuration/tuner_configuration.json` on playlist write and again after the decoder stops, so the next start shows the site you are listening to.

### Listen (browser audio)

A **Listen** button on the same waterfall plays decoded talkgroup audio in the browser (`waterfall.js` + `listen.js` over `/api/v1/ws/audio`). That is vocoded P25/DMR voice from SDRTrunk, not the FFT picture.

`AudioFrameExporter` streams `sdr2tak.audio.v1` NDJSON to RadioTAK on **127.0.0.1:29502**. Encrypted calls arrive as silence markers (`encrypted: true`, no PCM). RadioTAK strips any PCM on encrypted frames before the WebSocket. Clear digital voice still needs **JMBE** in the decoder, the same as local SDRTrunk playback. `install.sh` compiles that jar on-device with JMBE Creator `v1.0.9` into `/var/lib/radiotak/SDRTrunk/jmbe/` and writes the Java preference (and turns off the missing-library modal so Xvfb is not blocked). Enable with `audio_export_enabled`.

The Pi does not need headphones — click Listen on the website.

### noVNC fallback

When you need the native SDRTrunk GUI (full spectrum view, channel editor, tuner dialogs), use the **noVNC** iframe on the Console dashboard. SDRTrunk still runs under Xvfb; x11vnc exposes the display for browser access.

### Hearing gauges

The Console **hearing gauges** summarize decoder activity without FFT:

- **Messages / min** — geo/decode events in the last 60 s window
- **CC lock** — proxy for control-channel activity (`locked` / `intermittent` / `listening` / `idle`)
- **Last event** — age of the most recent heard event

Gauges turn green when the decoder is running and traffic is recent; amber when intermittent; red when idle or decoder stopped.

## East TN TACN sample

TN Interop names (**TN CALL**, **TN IO 1–15**) are **talkgroups** on TACN, not frequencies you paste into the playlist. Lock a nearby site control channel; Live Events / Units then show the TGID (for example `1471` = TN CALL).

Preset data: [`modules/sdr_location_gateway/samples/east_tn_tacn.json`](../modules/sdr_location_gateway/samples/east_tn_tacn.json). The SDR page **Fill Sullivan Co (LSM)** / **Fill Elizabethton (P25)** / **Fill Buffalo Mtn (LSM)** buttons copy those CCs into the Add form; they do not auto-seed the database. Save and Listen only for systems you are authorized to monitor. One RTL-SDR typically runs one trunked system.

| Sample | Protocol | Site | NAC | Control channels (MHz) |
|--------|----------|------|-----|------------------------|
| Sullivan Co Simulcast | P25 LSM CQPSK | 50 | 2AC | 854.5625, 856.7375 |
| Elizabethton (Carter) | P25 C4FM | 78 | 2A0 | 854.4375 (primary), 854.0375 |
| Buffalo Mtn simulcast (Washington) | P25 LSM CQPSK | 51 | 2A4 | 856.2375, 857.2375 |
| Fall Branch (optional 700 MHz) | P25 | 45 | 2A0 | 769.83125, 771.33125 |

Do **not** enter Elizabethton voice channels (`858.0375`, `858.7125`) as CCs. Simulcast sites need LSM; standalone sites use C4FM.

### Interop / mutual-aid TGIDs (event matching only)

| DEC | Name | Notes |
|-----|------|--------|
| 1471 | TN CALL | 24/7 hailing |
| 1473–1485 (odd) | TN IO 1–7 | East districts |
| 4001–4015 (odd) | TN IO 8–15 | West on zone map |
| 4055 / 4057 / 4059 | LAW MA 07–09 | THP District 5 |
| 47101 | PSAP-3 | District 5 PSAP |

Sullivan County sheriff/EMS/PD dispatch is mostly encrypted; Interop/MA and Kingsport Fire / SULLNET are the practical decoder-alive check. GPS still requires a radio transmitting Motorola unit GPS on the locked site (Sullivan radios affiliate on site 50, not Elizabethton). Re-check [RadioReference SID 6355](https://www.radioreference.com/db/sid/6355) / [site 50](https://www.radioreference.com/db/site/26156) if control-channel lock fails. Official zone layout: [TN.gov TACN talkgroups](https://www.tn.gov/safety/tacn/talkgroups.html).

## Fallback

`bin/radiotak replay tests/fixtures/*.jsonl` exercises the full pipeline without RF.
