# Encrypted traffic archive

RadioTAK records **observed encryption metadata** from the CopIXus SDRTrunk exporter. This is not a cracking engine. Unknown keys are never searched, guessed, or tested. Authorized traffic keys stay in `secrets/` and are never written into archive rows, exports, or logs.

## What is stored

For each voice/data call the decoder reports:

- radio ID, talkgroup, optional destination radio / talker alias
- protocol, P25 phase, timeslot, channel, frequency
- system ID, WACN, NAC, RFSS, site (when IdentifierCollection exposes them)
- ALGID / KID from the structured encryption identifier, falling back to call-details text
- Message Indicator **only if** the decoder already printed it
- decrypt state (`CLEAR`, `ENCRYPTED_METADATA_ONLY`, `ENCRYPTED_KEY_NOT_AVAILABLE`, `ENCRYPTED_AUTHORIZED_KEY_AVAILABLE`, `UNSUPPORTED_ENCRYPTION_ALGORITHM`)
- original `sdr2tak.decode.v1` JSON (secrets stripped)

Encrypted calls are **not** forwarded to TAK. TAK still receives allowlisted GPS as Cursor-on-Target.

## Configuration

Settings → Encryption archive, or `settings.json`:

```json
"encryption_archive": {
  "enabled": true,
  "metadata_retention_days": 365,
  "raw_samples": false,
  "iq_enabled": false
}
```

Raw sample / IQ capture remain disabled. Duplicate calls within 15 seconds increment `hear_count` instead of inserting another row.

Storage: SQLite table `encrypted_traffic_events` (metadata). Traffic keys remain in `/var/lib/radiotak/secrets/`. Deleting the archive does not delete keys.

## UI and API

- Console encryption card → `/encryption`
- CSV / JSON / JSONL export from that page (`GET /encryption/export?format=jsonl`)
- `GET /api/v1/encryption/stats`
- `GET /api/v1/encryption/events`

## Decoder exporter

`GeoEventJsonExporter` copies IdentifierCollection fields (`SYSTEM`, `WACN`, `NETWORK_ACCESS_CODE`, `SITE`, `RF_SUBSYSTEM`, `ENCRYPTION_KEY`, timeslot) into `sdr2tak.decode.v1`. A RadioTAK SDRTrunk rebuild is required before live RF includes those extra fields; RadioTAK already accepts them when present.

## What this does not do

- decrypt audio or embedded GPS without a future authorized known-key decoder path
- brute-force, dictionary, or GPU search for keys
- forward encrypted artifacts as map points
