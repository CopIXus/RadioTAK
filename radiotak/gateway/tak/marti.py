"""Marti API helpers — groups / channels."""

from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

log = logging.getLogger("radiotak.marti")


async def list_groups(
    host: str,
    api_port: int = 8443,
    cert: Optional[tuple[str, str]] = None,
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
    cert: Optional[tuple[str, str]] = None,
    verify: bool | str = False,
) -> Any:
    """Try PUT /groups/active then fall back to /groups/activebits."""
    url = f"https://{host}:{api_port}/Marti/api/groups/active"
    params = {"clientUid": client_uid}
    body = groups
    async with httpx.AsyncClient(cert=cert, verify=verify, timeout=30.0) as client:
        resp = await client.put(url, params=params, json=body)
        if resp.status_code >= 400:
            alt = f"https://{host}:{api_port}/Marti/api/groups/activebits"
            resp = await client.put(alt, params=params, json=body)
        resp.raise_for_status()
        try:
            return resp.json()
        except Exception:  # noqa: BLE001
            return {"status": resp.status_code, "text": resp.text[:500]}
