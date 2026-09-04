"""Marti API helpers — groups / channels."""

from __future__ import annotations

import logging
from typing import Any

import httpx

log = logging.getLogger("radiotak.marti")


def _payload(resp: httpx.Response) -> Any:
    try:
        return resp.json()
    except Exception:  # noqa: BLE001
        return {"status": resp.status_code, "text": (resp.text or "")[:500]}


def bitpos_for_groups(all_groups: list[dict[str, Any]], names: list[str]) -> list[int]:
    """Map selected group names to unique Marti bitpos values."""
    wanted = {str(n).strip() for n in names if n and str(n).strip()}
    bits: list[int] = []
    seen: set[int] = set()
    for g in all_groups:
        if not isinstance(g, dict):
            continue
        if g.get("name") not in wanted:
            continue
        bp = g.get("bitpos")
        if bp is None:
            continue
        try:
            val = int(bp)
        except (TypeError, ValueError):
            continue
        if val not in seen:
            seen.add(val)
            bits.append(val)
    return bits


def bitfield_for_positions(positions: list[int]) -> int:
    field = 0
    for pos in positions:
        if 0 <= int(pos) < 62:
            field |= 1 << int(pos)
    return field


async def list_groups(
    host: str,
    api_port: int = 8443,
    cert: tuple[str, str] | None = None,
    verify: bool | str = False,
) -> list[dict[str, Any]]:
    url = f"https://{host}:{api_port}/Marti/api/groups/all"
    async with httpx.AsyncClient(cert=cert, verify=verify, timeout=30.0) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.json()
    # TAK returns { version, type, data: [...] }
    if isinstance(data, dict):
        return list(data.get("data") or [])
    return list(data or [])


async def set_active_groups(
    host: str,
    groups: list[str],
    api_port: int = 8443,
    client_uid: str = "RadioTAK",
    cert: tuple[str, str] | None = None,
    verify: bool | str = False,
) -> Any:
    """PUT /groups/active (names), then /groups/activebits (bit positions / bitfield).

    TAK Server returns 400 when the streaming client is not connected yet, or when
    activebits is given group names instead of integer bit positions.
    """
    params = {"clientUid": client_uid}
    listed: list[dict[str, Any]] = []
    try:
        listed = await list_groups(host, api_port=api_port, cert=cert, verify=verify)
    except Exception as exc:  # noqa: BLE001
        log.warning("Marti list_groups failed: %s", exc)

    async with httpx.AsyncClient(cert=cert, verify=verify, timeout=30.0) as client:
        url = f"https://{host}:{api_port}/Marti/api/groups/active"
        resp = await client.put(url, params=params, json=list(groups))
        if resp.status_code < 400:
            return _payload(resp)

        last = resp
        bitpos = bitpos_for_groups(listed, groups)
        alt = f"https://{host}:{api_port}/Marti/api/groups/activebits"
        if bitpos:
            resp = await client.put(alt, params=params, json=bitpos)
            if resp.status_code < 400:
                return _payload(resp)
            last = resp
            field = bitfield_for_positions(bitpos)
            resp = await client.put(alt, params=params, json=field)
            if resp.status_code < 400:
                return _payload(resp)
            last = resp

        detail = (last.text or "").strip()[:300]
        raise httpx.HTTPStatusError(
            "TAK Server rejected group assignment for client "
            f"{client_uid} (HTTP {last.status_code} on {last.request.url}). "
            "This is expected if RadioTAK is not yet connected on the CoT port; "
            "channels are stored locally and applied after the streaming session is up. "
            f"{detail}",
            request=last.request,
            response=last,
        )
