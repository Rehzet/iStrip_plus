# iStrip+ desde la terminal

CLI en Python para controlar luces iStrip+ por Bluetooth Low Energy (BLE). No necesita Home Assistant.

Esta adaptación para terminal parte de la integración y el trabajo de ingeniería inversa del [repositorio original de vakintosh](https://github.com/vakintosh/istrip_plus_HA).

## Requisitos

- Python 3.11 o posterior.
- Un adaptador Bluetooth LE habilitado y acceso a Bluetooth desde el usuario que ejecuta los comandos.
- En Linux, BlueZ instalado y en ejecución.

## Instalación

Desde la carpeta del repositorio:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

Esto instala el comando `istrip` y sus dependencias (`bleak` y `pycryptodome`). También se puede ejecutar sin instalar como comando:

```bash
python -m istrip --help
```

## Uso

Busca dispositivos cercanos y anota la dirección BLE que aparece en la primera columna:

```bash
istrip scan
```

Todos los comandos de control usan esa dirección con `-a` o `--address`:

```bash
istrip on -a AA:BB:CC:DD:EE:FF
istrip off -a AA:BB:CC:DD:EE:FF
istrip color -a AA:BB:CC:DD:EE:FF FF2800 --brightness 75
istrip color -a AA:BB:CC:DD:EE:FF FF2800 --channel-order RGB
istrip effect -a AA:BB:CC:DD:EE:FF 'Red Breathing' --speed 35
istrip speed -a AA:BB:CC:DD:EE:FF 60
istrip watch -a AA:BB:CC:DD:EE:FF
```

`color` recibe un color hexadecimal `RRGGBB` (también acepta `#RRGGBB`; entre comillas si se usa `#`). `--channel-order` permite elegir entre `RGB`, `RBG`, `GRB`, `GBR`, `BRG` y `BGR`; por defecto usa `GRB`. La selección se guarda por dispositivo y se reutiliza al restaurar el color y al leer notificaciones. `--brightness` y la velocidad usan el rango `0-100`. Los efectos disponibles son:

```text
7-Color Fade       3-Color Fade       Red Breathing
Red Strobe         7-Color Breathing  3-Color Breathing
Blue Breathing     Blue Strobe        7-Color Flash
3-Color Flash      Green Breathing    Green Strobe
```

`on` recupera el último color o efecto usado. La CLI guarda el modo, el brillo y las velocidades por efecto en `~/.config/istrip/state.json` (o `$XDG_CONFIG_HOME/istrip/state.json`). `watch` mantiene una conexión abierta, muestra notificaciones de estado del dispositivo —incluidos cambios hechos con el mando infrarrojo— y actualiza ese archivo. Pulsa `Ctrl+C` para salir.

Cada comando abre una conexión BLE, envía el saludo de grupo que requiere el dispositivo y se desconecta. El primer escaneo puede tardar unos segundos. Si no encuentra la luz, comprueba que esté encendida, que el adaptador Bluetooth esté activo y que el proceso tenga permiso para usarlo.

## Protocolo

Los comandos usan paquetes AES cifrados compatibles con la aplicación oficial. La referencia de servicios GATT y paquetes está en [docs/ble-protocol.md](docs/ble-protocol.md).

## Desarrollo

```bash
python -m istrip --help
ruff check istrip/
ruff format --check istrip/
```
