"""Marti group bit-position helpers."""

from __future__ import annotations

from radiotak.gateway.tak.marti import bitfield_for_positions, bitpos_for_groups


def test_bitpos_unique_across_in_out():
    groups = [
        {"name": "TN Law Enforcement Mutual Aid", "bitpos": 4, "direction": "IN"},
        {"name": "TN Law Enforcement Mutual Aid", "bitpos": 4, "direction": "OUT"},
        {"name": "__ANON__", "bitpos": 0, "direction": "OUT"},
    ]
    assert bitpos_for_groups(groups, ["TN Law Enforcement Mutual Aid"]) == [4]
    assert bitpos_for_groups(groups, ["TN Law Enforcement Mutual Aid", "__ANON__"]) == [4, 0]


def test_bitfield():
    assert bitfield_for_positions([0, 2]) == 0b101
    assert bitfield_for_positions([4]) == 16
