"""KISS / AX.25 helpers."""

from __future__ import annotations

from modules.aprs_rf_gateway.kiss_client import KissDecoder, ax25_ui_to_tnc2


def _addr(call: str, ssid: int = 0, end: bool = False) -> bytes:
    call = call.ljust(6)[:6].upper()
    out = bytearray((ord(c) << 1) for c in call)
    ssid_byte = 0x60 | ((ssid & 0x0F) << 1)
    if end:
        ssid_byte |= 0x01
    out.append(ssid_byte)
    return bytes(out)


def test_kiss_unescape_and_ax25_ui():
    # Build AX.25 UI: dest WIDE1-1, src W4TEST-9, control 0x03, pid 0xF0, info
    info = b"!3600.00N/08200.00W-"
    ax25 = _addr("WIDE1", 1) + _addr("W4TEST", 9, end=True) + bytes([0x03, 0xF0]) + info
    # KISS data frame: FEND 0x00 <ax25> FEND with no escapes needed
    kiss = bytes([0xC0, 0x00]) + ax25 + bytes([0xC0])
    dec = KissDecoder()
    frames = dec.feed(kiss)
    assert len(frames) == 1
    tnc2 = ax25_ui_to_tnc2(frames[0])
    assert tnc2 is not None
    assert tnc2.startswith("W4TEST-9>WIDE1-1:")
    assert "!3600.00N/08200.00W-" in tnc2
