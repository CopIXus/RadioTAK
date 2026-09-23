"""GeoChat CoT builder and APRS mapping tests."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from radiotak.gateway.cot import build_geochat_xml


def test_geochat_xml_shape():
    xml = build_geochat_xml(
        sender_uid="RADIOTAK-APRS-W4TEST-9",
        sender_callsign="W4TEST-9",
        message_body="To W4DEST: Hello from APRS",
        chatroom="APRS",
        message_id="APRS-W4TEST-9-1",
        latitude=36.29531,
        longitude=-82.27922,
        marti_dest_group="APRS_WRITE",
    )
    assert 'type="b-t-f"' in xml
    assert 'uid="GeoChat.RADIOTAK-APRS-W4TEST-9.APRS.APRS-W4TEST-9-1"' in xml
    assert 'chatroom="APRS"' in xml
    assert 'id="APRS"' in xml
    assert 'senderCallsign="W4TEST-9"' in xml
    assert 'uid0="RADIOTAK-APRS-W4TEST-9"' in xml
    assert 'uid1="APRS"' in xml
    assert "Hello from APRS" in xml
    assert 'callsign="W4TEST-9"' in xml
    assert 'group="APRS_WRITE"' in xml
    assert 'source="BAO.F.ATAK.RADIOTAK-APRS-W4TEST-9"' in xml
    assert 'to="APRS"' in xml
    assert 'lat="36.295310"' in xml


def test_geochat_omits_marti_when_unset():
    xml = build_geochat_xml(
        sender_uid="RADIOTAK-APRS-W4TEST-9",
        sender_callsign="W4TEST-9",
        message_body="ping",
        chatroom="APRS",
        message_id="m1",
    )
    assert "<marti>" not in xml
    assert 'type="b-t-f"' in xml


def test_position_mapping_from_aprslib_dict():
    from modules.aprs_rf_gateway.aprs_map import position_to_ndjson

    packet = {
        "from": "W4TEST-9",
        "latitude": 36.29531,
        "longitude": -82.27922,
        "altitude": 1574.8,  # feet
        "speed": 25.0,  # knots
        "course": 180.0,
        "format": "uncompressed",
        "timestamp": datetime(2026, 9, 23, 16, 0, 0, tzinfo=UTC).timestamp(),
    }
    loc = position_to_ndjson(packet, source="rf")
    assert loc is not None
    assert loc["schema"] == "sdr2tak.location.v1"
    assert loc["decoder"] == "direwolf"
    assert loc["protocol"] == "APRS"
    assert loc["system_id"] == "APRS"
    assert loc["radio_id"] == "W4TEST-9"
    assert loc["latitude"] == pytest.approx(36.29531)
    assert loc["longitude"] == pytest.approx(-82.27922)
    assert loc["heading_deg"] == pytest.approx(180.0)
    assert loc["speed_mps"] == pytest.approx(25.0 * 0.514444)
    assert loc["altitude_m"] == pytest.approx(1574.8 * 0.3048)


def test_message_mapping():
    from modules.aprs_rf_gateway.aprs_map import message_from_packet

    packet = {
        "format": "message",
        "from": "W4TEST-9",
        "addresse": "W4DEST",
        "message_text": "Hello from APRS",
        "msgNo": "1",
    }
    msg = message_from_packet(packet, source="rf")
    assert msg is not None
    assert msg["from"] == "W4TEST-9"
    assert "Hello from APRS" in msg["body"]
    assert "W4DEST" in msg["body"]


def test_parse_sample_message_tnc2():
    aprslib = pytest.importorskip("aprslib")
    from modules.aprs_rf_gateway.aprs_map import message_from_packet, parse_tnc2

    sample = Path("modules/aprs_rf_gateway/samples/message.tnc2").read_text(encoding="utf-8").strip()
    packet = parse_tnc2(sample)
    assert packet is not None
    assert packet["from"] == "W4TEST-9"
    msg = message_from_packet(packet)
    assert msg is not None
    assert "Hello from APRS" in msg["body"]
    # round-trip via aprslib directly
    assert aprslib.parse(sample)["format"] == "message"


def test_sample_position_jsonl_validates():
    import json

    from radiotak.gateway import LocationEventIn

    line = Path("modules/aprs_rf_gateway/samples/position.jsonl").read_text(encoding="utf-8").strip()
    ev = LocationEventIn.model_validate(json.loads(line))
    assert ev.radio_id == "W4TEST-9"
    assert ev.decoder == "direwolf"
    assert ev.protocol == "APRS"
