"""Direct BLE access for iStrip+ devices using Bleak."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from .ble_helpers import find_notify_char
from .const import DEFAULT_CHANNEL_ORDER, KNOWN_CHAR_UUIDS
from .payload_generator import CommandType, PayloadGenerator

_LOGGER = logging.getLogger(__name__)
PROBE_TIMEOUT = 2.0


async def scan_devices(timeout: float = 8.0) -> list[Any]:
    """Scan nearby Bluetooth LE devices."""
    from bleak import BleakScanner

    return await BleakScanner.discover(timeout=timeout)


class IstripClient:
    """One BLE connection to an iStrip light."""

    def __init__(
        self,
        address: str,
        name: str | None = None,
        channel_order: str = DEFAULT_CHANNEL_ORDER,
    ) -> None:
        self.address = address
        self.name = name or "iStrip"
        self.channel_order = channel_order
        from bleak import BleakClient

        self.client = BleakClient(address, timeout=20.0)
        self.payloads = PayloadGenerator()
        self.write_uuid: str | None = None
        self.notify_uuid: str | None = None
        self.on_state: Callable[[dict[str, object]], None] | None = None
        self._subscribed = False

    async def __aenter__(self) -> IstripClient:
        await self.client.connect()
        try:
            await self._select_write_characteristic()
            return self
        except Exception:
            await self.client.disconnect()
            raise

    async def __aexit__(self, *_: object) -> None:
        if self._subscribed and self.notify_uuid:
            try:
                await self.client.stop_notify(self.notify_uuid)
            except Exception:  # BLE backends can report disconnect during cleanup
                _LOGGER.debug("Could not stop notifications from %s", self.address)
        if self.client.is_connected:
            await self.client.disconnect()

    async def _select_write_characteristic(self) -> None:
        writable: list[str] = []
        for service in self.client.services:
            for char in service.characteristics:
                can_write = "write" in char.properties or (
                    "write-without-response" in char.properties
                )
                if can_write:
                    writable.append(str(char.uuid))

        if not writable:
            raise RuntimeError(
                f"{self.address}: no se encontraron características BLE escribibles"
            )

        candidates = [uuid for uuid in KNOWN_CHAR_UUIDS if uuid in writable]
        candidates.extend(uuid for uuid in writable if uuid not in candidates)

        join_packet = self.payloads.get_join_group_payload()
        for candidate in candidates:
            notify_uuid = find_notify_char(self.client, candidate)
            if not notify_uuid:
                continue

            echoed = asyncio.Event()

            def on_probe(sender: Any, data: bytearray) -> None:
                if bytes(data) == join_packet:
                    echoed.set()
                    return
                self._handle_notification(sender, data)

            try:
                await self.client.start_notify(notify_uuid, on_probe)
                self._subscribed = True
                self.notify_uuid = notify_uuid
                await self.client.write_gatt_char(
                    candidate, join_packet, response=False
                )
                await asyncio.wait_for(echoed.wait(), timeout=PROBE_TIMEOUT)
            except Exception as err:
                _LOGGER.debug("No se confirmó la característica %s: %s", candidate, err)
                if self._subscribed:
                    try:
                        await self.client.stop_notify(notify_uuid)
                    except Exception:
                        pass
                    self._subscribed = False
                    self.notify_uuid = None
                continue

            self.write_uuid = candidate
            _LOGGER.info(
                "Conectado a %s; característica de control: %s",
                self.address,
                candidate,
            )
            return

        # Some firmware does not echo the group-join packet. Retain the known
        # characteristic preference, then send the required handshake once.
        self.write_uuid = next(
            (uuid for uuid in KNOWN_CHAR_UUIDS if uuid in writable), writable[0]
        )
        self.notify_uuid = find_notify_char(self.client, self.write_uuid)
        if self.notify_uuid:
            try:
                await self.client.start_notify(
                    self.notify_uuid, self._handle_notification
                )
                self._subscribed = True
            except Exception as err:
                _LOGGER.warning("No se pudieron activar notificaciones BLE: %s", err)
                self.notify_uuid = None

        await self.client.write_gatt_char(self.write_uuid, join_packet, response=False)
        _LOGGER.info(
            "Conectado a %s; característica de control: %s",
            self.address,
            self.write_uuid,
        )

    async def send(self, packet: bytes) -> None:
        """Write one encrypted command to the control characteristic."""
        if not self.client.is_connected or not self.write_uuid:
            raise ConnectionError(f"No hay conexión con {self.address}")
        await self.client.write_gatt_char(self.write_uuid, packet, response=False)

    async def watch(self) -> None:
        """Wait for state notifications until interrupted by the user."""
        if not self.notify_uuid:
            raise RuntimeError("El dispositivo no ofrece notificaciones de estado")
        await asyncio.Event().wait()

    def _handle_notification(self, _sender: Any, data: bytearray) -> None:
        try:
            state = self.payloads.parse_state(
                self.payloads.decrypt_payload(bytes(data)), self.channel_order
            )
            if state["command_type"] != CommandType.RGB:
                return
            if self.on_state:
                self.on_state(state)
        except (ValueError, IndexError):
            _LOGGER.debug("Notificación iStrip+ no reconocida desde %s", self.address)
