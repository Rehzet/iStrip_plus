"""Command-line interface for iStrip+ BLE lights."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

from .ble import IstripClient, scan_devices
from .const import (
    CHANNEL_ORDERS,
    DEFAULT_CHANNEL_ORDER,
    DEFAULT_SPEED,
    EFFECT_DEFAULT_SPEEDS,
)
from .payload_generator import PayloadGenerator

_LOGGER = logging.getLogger("istrip")


def _state_path() -> Path:
    config_home = os.environ.get("XDG_CONFIG_HOME")
    root = Path(config_home).expanduser() if config_home else Path.home() / ".config"
    return root / "istrip" / "state.json"


def _default_state() -> dict[str, Any]:
    return {
        "is_on": False,
        "rgb": [255, 255, 255],
        "brightness": 100,
        "effect": None,
        "speed": DEFAULT_SPEED,
        "channel_order": DEFAULT_CHANNEL_ORDER,
        "effect_speeds": dict(EFFECT_DEFAULT_SPEEDS),
    }


def _load_states() -> dict[str, dict[str, Any]]:
    try:
        with _state_path().open(encoding="utf-8") as file:
            value = json.load(file)
        return value if isinstance(value, dict) else {}
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as err:
        _LOGGER.warning("No se pudo leer el estado guardado: %s", err)
        return {}


def _save_states(states: dict[str, dict[str, Any]]) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(states, indent=2), encoding="utf-8")
    temporary.replace(path)


def _range(value: str, low: int, high: int, label: str) -> int:
    try:
        number = int(value)
    except ValueError as err:
        raise argparse.ArgumentTypeError(f"{label} debe ser un entero") from err
    if not low <= number <= high:
        raise argparse.ArgumentTypeError(f"{label} debe estar entre {low} y {high}")
    return number


def _hex_color(value: str) -> tuple[int, int, int]:
    """Parse a six-digit RGB hex color, with an optional leading #."""
    digits = value[1:] if value.startswith("#") else value
    if len(digits) != 6 or any(char not in "0123456789abcdefABCDEF" for char in digits):
        raise argparse.ArgumentTypeError(
            "El color debe tener formato hexadecimal RRGGBB (por ejemplo, FF2800)"
        )
    return tuple(int(digits[index : index + 2], 16) for index in (0, 2, 4))


def _percent(value: str) -> int:
    return _range(value, 0, 100, "El porcentaje")


def _speed(value: str) -> int:
    return _range(value, 1, 100, "La velocidad")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="istrip",
        description="Controla luces iStrip+ por Bluetooth LE, sin Home Assistant.",
        epilog=(
            "Ejemplos: istrip scan | istrip color -a AA:BB:CC:DD:EE:FF FF0050 "
            "--brightness 60 | istrip effect -a AA:BB:CC:DD:EE:FF 'Red Breathing'"
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan_parser = subparsers.add_parser("scan", help="buscar dispositivos BLE cercanos")
    scan_parser.add_argument(
        "--timeout", type=float, default=8.0, help="duración del escaneo en segundos"
    )

    def device_command(name: str, help_text: str) -> argparse.ArgumentParser:
        command_parser = subparsers.add_parser(name, help=help_text)
        command_parser.add_argument(
            "-a", "--address", required=True, help="dirección BLE del dispositivo"
        )
        return command_parser

    device_command("on", "encender o recuperar el último color/efecto")
    device_command("off", "apagar la luz")

    color_parser = device_command("color", "establecer un color RGB")
    color_parser.add_argument(
        "hex_color",
        type=_hex_color,
        metavar="RRGGBB",
        help="color hexadecimal de seis dígitos (se admite el prefijo #)",
    )
    color_parser.add_argument(
        "--brightness", type=_percent, default=None, help="brillo: 0-100%%"
    )
    color_parser.add_argument(
        "--channel-order",
        "--order",
        type=str.upper,
        choices=CHANNEL_ORDERS,
        default=DEFAULT_CHANNEL_ORDER,
        help=f"orden de canales BLE (predeterminado: {DEFAULT_CHANNEL_ORDER})",
    )

    effect_parser = device_command("effect", "activar uno de los efectos integrados")
    effect_parser.add_argument(
        "name", choices=PayloadGenerator.EFFECT_MODES, help="nombre exacto del efecto"
    )
    effect_parser.add_argument(
        "--speed", type=_speed, default=None, help="velocidad: 1-100"
    )
    effect_parser.add_argument(
        "--brightness", type=_percent, default=None, help="brillo: 0-100%%"
    )

    speed_parser = device_command(
        "speed", "cambiar velocidad del efecto activo guardado"
    )
    speed_parser.add_argument("value", type=_speed, help="velocidad: 1-100")

    device_command("watch", "mostrar cambios de estado y del mando infrarrojo")
    return parser


async def _scan(timeout: float) -> None:
    devices = await scan_devices(timeout)
    if not devices:
        print("No se encontraron dispositivos BLE.")
        return
    for device in sorted(devices, key=lambda item: (item.name or "").lower()):
        print(f"{device.address:24} {device.name or '(sin nombre)'}")


def _format_state(state: dict[str, object]) -> str:
    red, green, blue = state["rgb"]
    mode = state["effect"] or "color fijo"
    power = "encendida" if state["is_on"] else "apagada"
    return (
        f"{power} | RGB {red},{green},{blue} | brillo {state['brightness']}% | "
        f"{mode} | velocidad {state['speed']}"
    )


async def _control(args: argparse.Namespace) -> None:
    address = args.address.upper()
    states = _load_states()
    state = _default_state()
    state.update(states.get(address, {}))
    payloads = PayloadGenerator()
    packet: bytes | None = None

    if args.command == "off":
        state["is_on"] = False
        packet = payloads.get_off_payload()
    elif args.command == "on":
        state["is_on"] = True
        packet = _active_payload(payloads, state)
    elif args.command == "color":
        state["rgb"] = list(args.hex_color)
        state["effect"] = None
        state["is_on"] = True
        state["channel_order"] = args.channel_order
        if args.brightness is not None:
            state["brightness"] = args.brightness
        packet = payloads.get_rgb_payload(
            *state["rgb"],
            state["brightness"],
            channel_order=state["channel_order"],
        )
    elif args.command == "effect":
        state["effect"] = args.name
        state["is_on"] = True
        if args.brightness is not None:
            state["brightness"] = args.brightness
        effect_speeds = state.setdefault("effect_speeds", dict(EFFECT_DEFAULT_SPEEDS))
        if args.speed is not None:
            effect_speeds[args.name] = args.speed
        state["speed"] = effect_speeds.get(
            args.name, EFFECT_DEFAULT_SPEEDS.get(args.name, DEFAULT_SPEED)
        )
        packet = _active_payload(payloads, state)
    elif args.command == "speed":
        if not state.get("effect"):
            raise ValueError(
                "No hay un efecto guardado; activa uno primero con 'istrip effect'."
            )
        effect_speeds = state.setdefault("effect_speeds", dict(EFFECT_DEFAULT_SPEEDS))
        effect_speeds[state["effect"]] = args.value
        state["speed"] = args.value
        if state["is_on"]:
            packet = _active_payload(payloads, state)

    if args.command == "speed" and packet is None:
        states[address] = state
        _save_states(states)
        print(
            f"Velocidad guardada para {state['effect']}: {state['speed']} "
            f"({address}, luz apagada)"
        )
        return

    if packet is not None:
        async with IstripClient(
            address, channel_order=state["channel_order"]
        ) as device:
            await device.send(packet)
        states[address] = state
        _save_states(states)
        print(f"{args.command}: {_format_state(state)} ({address})")
        return

    if args.command == "watch":
        def report(incoming: dict[str, object]) -> None:
            state.update(
                is_on=incoming["is_on"],
                rgb=list(incoming["rgb"]),
                brightness=incoming["brightness"],
                effect=incoming["effect"],
                speed=incoming["speed"],
            )
            effect_name = incoming["effect"]
            if effect_name:
                state.setdefault("effect_speeds", {})[effect_name] = incoming["speed"]
            states[address] = state
            _save_states(states)
            print(_format_state(incoming), flush=True)

        async with IstripClient(
            address, channel_order=state["channel_order"]
        ) as device:
            device.on_state = report
            print(f"Escuchando {address}; Ctrl+C para salir.", flush=True)
            await device.watch()


def _active_payload(payloads: PayloadGenerator, state: dict[str, Any]) -> bytes:
    effect = state.get("effect")
    if effect:
        speed = state.get("effect_speeds", {}).get(
            effect, EFFECT_DEFAULT_SPEEDS.get(effect, DEFAULT_SPEED)
        )
        state["speed"] = speed
        return payloads.get_effect_payload(
            effect,
            max(10, state["brightness"]),
            speed,
            tuple(state["rgb"]),
            channel_order=state["channel_order"],
        )
    return payloads.get_rgb_payload(
        *state["rgb"],
        state["brightness"],
        channel_order=state["channel_order"],
    )


def main() -> None:
    parser = _parser()
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        if args.command == "scan":
            asyncio.run(_scan(args.timeout))
        else:
            asyncio.run(_control(args))
    except KeyboardInterrupt:
        print("\nInterrumpido.")
    except ImportError as err:
        print(
            "Falta una dependencia. Instálala con 'python -m pip install -e .': "
            f"{err}",
            file=sys.stderr,
        )
        raise SystemExit(1) from err
    except Exception as err:
        print(f"Error: {err}", file=sys.stderr)
        raise SystemExit(1) from err
