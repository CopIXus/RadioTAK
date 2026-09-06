"""Talkgroup audio hub — PCM ingest and encrypted silence stripping."""

from __future__ import annotations

import base64
import json
import struct

from modules.sdr_location_gateway.sdrtrunk.audio import audio_hub


def _pcm_b64(samples: list[int]) -> str:
    return base64.b64encode(b"".join(struct.pack("<h", s) for s in samples)).decode("ascii")


def test_audio_parse_pcm_chunk():
    pcm = _pcm_b64([0, 16384, -16384, 32767])
    frame = audio_hub.parse_frame(
        json.dumps(
            {
                "schema": "sdr2tak.audio.v1",
                "encrypted": False,
                "talkgroup": "1471",
                "radio_id": "1234567",
                "sample_rate": 8000,
                "pcm_b64": pcm,
            }
        )
    )
    assert frame is not None
    assert frame["encrypted"] is False
    assert frame["silence"] is False
    assert frame["talkgroup"] == "1471"
    assert frame["radio_id"] == "1234567"
    assert frame["pcm_b64"] == pcm
    assert frame["sample_rate"] == 8000


def test_audio_parse_strips_pcm_on_encrypted():
    pcm = _pcm_b64([1, 2, 3, 4])
    frame = audio_hub.parse_frame(
        json.dumps(
            {
                "schema": "sdr2tak.audio.v1",
                "encrypted": True,
                "silence": True,
                "talkgroup": "11025",
                "pcm_b64": pcm,
            }
        )
    )
    assert frame is not None
    assert frame["encrypted"] is True
    assert frame["silence"] is True
    assert frame["talkgroup"] == "11025"
    assert frame["pcm_b64"] == ""


def test_audio_parse_end_without_pcm():
    frame = audio_hub.parse_frame(
        '{"schema":"sdr2tak.audio.v1","encrypted":false,"end":true,"talkgroup":"1471"}'
    )
    assert frame is not None
    assert frame["end"] is True
    assert frame["pcm_b64"] == ""


def test_audio_parse_skips_blank_and_unrelated():
    assert audio_hub.parse_frame("") is None
    assert audio_hub.parse_frame("   ") is None
    assert audio_hub.parse_frame('{"schema":"sdr2tak.spectrum.v1","bins":[1]}') is None


def test_audio_snapshot_shape():
    snap = audio_hub.snapshot()
    assert "clients" in snap
    assert "frames_received" in snap
    assert "pcm_frames" in snap
    assert "encrypted_frames" in snap
    assert "encrypted" in snap
    assert snap["talkgroup"] == "" or isinstance(snap["talkgroup"], str)
