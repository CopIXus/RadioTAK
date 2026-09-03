# Zello Audio Bridge (placeholder)

Protocol source of truth: [zelloptt/zello-channel-api](https://github.com/zelloptt/zello-channel-api).

## Planned design

1. Build JMBE on-device for P25/DMR voice decode in SDRTrunk.
2. Receive per-call uploads (Rdio Scanner-compatible) from SDRTrunk.
3. Transcode to 16 kHz mono Opus.
4. Stream via Zello Channel API:
   - Consumer: `wss://zello.io/ws` + JWT (`AUTH.md`)
   - Zello Work: `wss://zellowork.io/ws/<network>`
   - Enterprise: `wss://<domain>/ws/mesh`
5. Talkgroup → Zello channel mapping UI.
6. Optional `send_location` / `send_text_message` sinks from the core pipeline.

See the project plan Phase 8 for full wire-format details (`start_stream`, `codec_header`, binary packet layout).
