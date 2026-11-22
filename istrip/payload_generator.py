"""AES payload generation and state parsing for iStrip+ BLE lights."""

from __future__ import annotations

from enum import IntEnum


class CommandType(IntEnum):
    JOIN_GROUP_REQUEST = 1
    RGB = 2
    RHYTHM = 3
    TIMER = 4
    RGB_LINE_SEQUENCE = 5
    SPEED = 6
    LIGHT = 7


class PayloadGenerator:
    """Generate and parse encrypted iStrip+ BLE packets."""

    __slots__ = ("_cipher",)

    KEY = bytes(
        [
            0x34, 0x52, 0x2A, 0x5B, 0x7A, 0x6E, 0x49, 0x2C,
            0x08, 0x09, 0x0A, 0x9D, 0x8D, 0x2A, 0x23, 0xF8,
        ]
    )
    HEADER = bytes([0x54, 0x52, 0x00, 0x57])
    GROUP_ID = 1
    EFFECT_MODES: dict[str, int] = {
        "3-Color Breathing": 6,
        "3-Color Fade": 2,
        "3-Color Flash": 10,
        "7-Color Breathing": 5,
        "7-Color Fade": 1,
        "7-Color Flash": 9,
        "Blue Breathing": 7,
        "Blue Strobe": 8,
        "Green Breathing": 11,
        "Green Strobe": 12,
        "Red Breathing": 3,
        "Red Strobe": 4,
    }
    EFFECT_NAMES = {mode: name for name, mode in EFFECT_MODES.items()}

    def __init__(self) -> None:
        from Crypto.Cipher import AES

        self._cipher = AES.new(self.KEY, AES.MODE_ECB)

    def get_join_group_payload(self) -> bytes:
        payload = bytearray(16)
        payload[0:4] = self.HEADER
        payload[4] = CommandType.JOIN_GROUP_REQUEST
        payload[5] = self.GROUP_ID
        return self._encrypt(payload)

    def get_rgb_payload(
        self,
        red: int,
        green: int,
        blue: int,
        brightness: int = 100,
        speed: int = 100,
        channel_order: str = "GRB",
    ) -> bytes:
        payload = bytearray(16)
        payload[0:4] = self.HEADER
        payload[4] = CommandType.RGB
        payload[5] = self.GROUP_ID
        payload[7:10] = self._ordered_channels((red, green, blue), channel_order)
        payload[10] = brightness
        payload[11] = speed
        return self._encrypt(payload)

    def get_off_payload(self, speed: int = 100) -> bytes:
        return self.get_rgb_payload(0, 0, 0, 0, speed)

    def get_effect_payload(
        self,
        effect_name: str,
        brightness: int = 100,
        speed: int = 100,
        rgb: tuple[int, int, int] = (255, 255, 255),
        channel_order: str = "GRB",
    ) -> bytes:
        if effect_name not in self.EFFECT_MODES:
            raise ValueError(
                f"Efecto desconocido: {effect_name}. Opciones: "
                f"{', '.join(self.EFFECT_MODES)}"
            )

        payload = bytearray(16)
        payload[0:4] = self.HEADER
        payload[4] = CommandType.RGB
        payload[5] = self.GROUP_ID
        payload[6] = self.EFFECT_MODES[effect_name]
        payload[7:10] = self._ordered_channels(rgb, channel_order)
        payload[10] = brightness
        payload[11] = speed
        return self._encrypt(payload)

    def _encrypt(self, payload: bytearray) -> bytes:
        if len(payload) != 16:
            raise ValueError(f"El paquete debe tener 16 bytes, tiene {len(payload)}")
        return self._cipher.encrypt(bytes(payload))

    def decrypt_payload(self, data: bytes) -> bytearray:
        if len(data) != 16:
            raise ValueError(
                f"El paquete cifrado debe tener 16 bytes, tiene {len(data)}"
            )
        return bytearray(self._cipher.decrypt(bytes(data)))

    @staticmethod
    def _ordered_channels(rgb: tuple[int, int, int], channel_order: str) -> bytes:
        if len(channel_order) != 3 or set(channel_order) != {"R", "G", "B"}:
            raise ValueError(f"Orden de canales no válido: {channel_order}")
        channels = dict(zip("RGB", rgb, strict=True))
        return bytes(channels[channel] for channel in channel_order)

    def parse_state(
        self, payload: bytearray, channel_order: str = "GRB"
    ) -> dict[str, object]:
        if len(payload) != 16 or bytes(payload[:4]) != self.HEADER:
            raise ValueError("Paquete iStrip+ no válido")

        mode = payload[6]
        if len(channel_order) != 3 or set(channel_order) != {"R", "G", "B"}:
            raise ValueError(f"Orden de canales no válido: {channel_order}")
        channels = dict(zip(channel_order, payload[7:10], strict=True))
        red, green, blue = (channels[channel] for channel in "RGB")
        brightness = payload[10]
        return {
            "command_type": payload[4],
            "is_on": not (red == green == blue == 0 and mode == 0),
            "rgb": (red, green, blue),
            "brightness": brightness,
            "effect": self.EFFECT_NAMES.get(mode),
            "speed": payload[11],
        }
