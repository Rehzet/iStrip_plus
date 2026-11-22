"""Helpers for discovering BLE characteristics."""

from __future__ import annotations

from typing import Any


def find_notify_char(client: Any, write_uuid: str | None) -> str | None:
    """Find a notify characteristic, preferring the write characteristic's service."""
    same_service: list[str] = []
    other: list[str] = []

    for service in client.services:
        has_write = any(
            str(char.uuid) == write_uuid for char in service.characteristics
        )
        for char in service.characteristics:
            if "notify" in char.properties or "indicate" in char.properties:
                (same_service if has_write else other).append(str(char.uuid))

    if same_service:
        return same_service[0]
    return other[0] if other else None
