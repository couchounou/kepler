"""
BTHome Bleak — Scanner et client GATT pour device BTHome
=========================================================
Fonctionnalités :
  - Scan passif des advertisements BTHome (beacon 60 s)
  - Filtrage par nom / adresse MAC
  - Connexion GATT pour lire/écrire les caractéristiques
  - Décodage complet des 3 types de trames (beacon, device-id, events)

Dépendances :
    pip install bleak

Usage :
    # Scanner passif (Ctrl-C pour arrêter)
    python bthome_bleak.py scan

    # Scanner et filtrer sur un device précis
    python bthome_bleak.py scan --address AA:BB:CC:DD:EE:FF

    # Lire toutes les caractéristiques GATT
    python bthome_bleak.py read --address AA:BB:CC:DD:EE:FF

    # Écrire une caractéristique (ex. mettre l'heure UNIX)
    python bthome_bleak.py write --address AA:BB:CC:DD:EE:FF \
        --uuid d56a3410-115e-41d1-945b-3a7f189966a1 --value 1712345678
"""

import asyncio
import argparse
import struct
import time
import logging
from datetime import datetime, timezone

from bleak import BleakScanner, BleakClient
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData


CHARACTERISTICS = {
    "unix_time":          ("d56a3410-115e-41d1-945b-3a7f189966a1", "<I",  "rw", "UTC timestamp"),
    "utc_offset":         ("08b83239-6f5e-4412-892d-81e59224716e", "<h",  "rw", "UTC offset en minutes"),
    "zigbee_enabled":     ("68348d04-f62c-435d-b075-cc54b9f049cc", "B",   "rw", "0=désactivé, 1=activé"),
    "temp_offset":        ("0de178e5-a95d-4988-b042-7145d540a000", "<h",  "rw", "offset temp. (0.1 °C)"),
    "humi_offset":        ("0de178e5-a95d-4988-b042-7145d540a002", "<h",  "rw", "offset humidité (1 %)"),
    "dark_threshold":     ("c1a32099-32e8-42d8-99bb-b90ce4abe841", "<H",  "rw", "seuil obscurité (~1 lux)"),
    "bright_threshold":   ("c1a32099-32e8-42d8-99bb-b90ce4abe842", "<H",  "rw", "seuil lumineux (~1 lux)"),
    "invert_display":     ("611723f5-53dd-4289-888a-7523db56bb59", "B",   "rw", "0=noir/blanc, 1=blanc/noir"),
    "temp_units":         ("8645a7a9-6bb6-41fa-a120-4034629c2519", "B",   "rw", "0=Celsius, 1=Fahrenheit"),
    "clock_sync":         ("317c7868-5889-4572-b6ef-2c436ee5a92a", "B",   "rw", "0=désactivé, 1=activé"),
    "clock_mode_12h":     ("a9e33a3f-0396-41e5-a7c4-30511ffba2ad", "B",   "rw", "0=24h, 1=12h"),
    "power_save":         ("ca9d7a88-2ad3-4940-9b8b-75558d08a3b0", "B",   "rw", "0=désactivé, 1=activé"),
    "factory_reset":      ("b0a7e40f-2b87-49db-801c-eb3686a24bdb", "B",   "w",  "écrire 1 pour reset"),
    "battery1_voltage":   ("8f8e2438-535d-478d-af0f-c3692c3c1bb1", "<H",  "r",  "tension batterie 1 (0.01 V)"),
    "battery2_voltage":   ("8f8e2438-535d-478d-af0f-c3692c3c1bb2", "<H",  "r",  "tension batterie 2 (0.01 V)"),
}

# ── Décodeur BTHome ───────────────────────────────────────────────────────────

# UUID de service BTHome standard
BTHOME_SERVICE_UUID = "0000181c-0000-1000-8000-00805f9b34fb"
# Certains devices utilisent un UUID non-standard — on accepte les deux
BTHOME_ALT_UUID = "0000fcd2-0000-1000-8000-00805f9b34fb"


def decode_frame(data: bytes) -> dict:
    """Décode une payload BTHome brute."""
    if not data:
        return {}

    result = {}
    pos = 0

    while pos < len(data):
        obj_id = data[pos]
        pos += 1

        try:
            if obj_id == 0x01:
                result["battery_pct"] = data[pos]
                pos += 1
            elif obj_id == 0x15:
                result["battery_low"] = bool(data[pos])
                pos += 1
            elif obj_id == 0x1E:
                raw = data[pos]
                pos += 1
                result["light"] = {0: "dark", 1: "twilight", 2: "bright"}.get(raw, f"?({raw})")
                result["light_raw"] = raw
            elif obj_id == 0x2E:
                result["humidity_pct"] = data[pos]
                pos += 1
            elif obj_id == 0x45:
                raw = struct.unpack_from("<h", data, pos)[0]
                pos += 2
                result["temperature_c"] = raw / 10.0
            elif obj_id == 0xF0:
                result["device_type_id"] = struct.unpack_from("<H", data, pos)[0]
                pos += 2
            elif obj_id == 0xF1:
                result["firmware_u32"] = struct.unpack_from("<I", data, pos)[0]
                pos += 4
            elif obj_id == 0xF2:
                b = data[pos:pos+3]
                pos += 3
                result["firmware_u24"] = b[0] | (b[1] << 8) | (b[2] << 16)
            elif obj_id == 0x3A:
                raw = data[pos]
                pos += 1
                result["button_event"] = {1: "short_press"}.get(raw, f"?({raw})")
            else:
                result[f"unknown_0x{obj_id:02X}"] = data[pos] if pos < len(data) else None
                pos += 1
        except (IndexError, struct.error):
            logging.warning(f"Trame tronquée à l'offset {pos} (obj_id=0x{obj_id:02X})")
            break

    # Déduire le type
    if "device_type_id" in result or "firmware_u32" in result:
        result["frame_type"] = "device_id_packet"
    elif "button_event" in result:
        result["frame_type"] = "event"
    elif any(k in result for k in ("temperature_c", "humidity_pct", "light")):
        result["frame_type"] = "advertising_beacon"
    else:
        result["frame_type"] = "unknown"

    return result


def extract_bthome_payload(adv: AdvertisementData) -> bytes | None:
    """Extrait la payload BTHome depuis les données d'advertisement."""
    # 1. Chercher dans les service_data (UUID connu)
    for uuid in (BTHOME_SERVICE_UUID, BTHOME_ALT_UUID):
        if uuid in adv.service_data:
            payload = adv.service_data[uuid]
            # Le premier octet est le Device Information byte (flags BTHome)
            # On l'ignore et on passe directement aux objets
            return payload[1:] if payload else None

    # 2. Chercher dans manufacturer_data (fallback)
    for mfr_id, mfr_data in adv.manufacturer_data.items():
        if len(mfr_data) > 2:
            return mfr_data

    return None


# ── Formatage ─────────────────────────────────────────────────────────────────

def fmt_decoded(decoded: dict, addr: str, rssi: int | None = None) -> str:
    ts = datetime.now().strftime("%H:%M:%S")
    ftyp = decoded.get("frame_type", "?")
    rssi_s = f"  RSSI={rssi} dBm" if rssi is not None else ""

    lines = [f"[{ts}] {addr}  {ftyp}{rssi_s}"]

    field_labels = {
        "battery_pct":    ("Batterie",    "%"),
        "battery_low":    ("Batt. faible", ""),
        "temperature_c":  ("Temp.",       "°C"),
        "humidity_pct":   ("Humidité",    "%"),
        "light":          ("Lumière",     ""),
        "device_type_id": ("Device type", ""),
        "firmware_u32":   ("FW (u32)",    ""),
        "firmware_u24":   ("FW (u24)",    ""),
        "button_event":   ("Bouton",      ""),
    }
    for key, (label, unit) in field_labels.items():
        if key in decoded:
            suffix = f" {unit}" if unit else ""
            lines.append(f"    {label:<14}: {decoded[key]}{suffix}")

    return "\n".join(lines)


# ── Scanner passif ────────────────────────────────────────────────────────────

async def scan(target_address: str | None = None, duration: float | None = None, state_obj: dict | None = None):
    """
    Écoute passivement les advertisements BTHome.

    :param target_address: si fourni, filtre sur cette adresse MAC
    :param duration:       durée en secondes (None = infini jusqu'à Ctrl-C)
    """
    logging.info(
        "[SCAN] Démarrage du scan BLE BTHome %s…",
        f" (filtre: {target_address})" if target_address else ""
    )
    seen: dict[str, float] = {}   # adresse → timestamp dernière réception

    def callback(device: BLEDevice, adv: AdvertisementData):
        addr = device.address.upper()

        if target_address and addr != target_address.upper():
            return

        payload = extract_bthome_payload(adv)
        if payload is None:
            return

        decoded = decode_frame(payload)
        if not decoded:
            return

        # Anti-doublon : afficher au max 1 fois par seconde par device
        now = time.monotonic()
        if now - seen.get(addr, 0) < 1.0:
            return
        seen[addr] = now

        # print(fmt_decoded(decoded, addr, adv.rssi))
        logging.info("[SCAN] %s", decoded)
        state_obj.state["bt_temperature"] = decoded.get("temperature_c", None)
        state_obj.state["bt_humidity"] = decoded.get("humidity_pct", None)
        state_obj.state["bt_last_update"] = datetime.now().isoformat()
        state_obj.state["bt_light"] = decoded.get("light", "")
        logging.debug(
            "[SCAN] Température BT: %s °C, Humidité BT: %s %%, Lumière: %s",
            state_obj.state.get("bt_temperature"),
            state_obj.state.get("bt_humidity"),
            state_obj.state.get("bt_light")
        )


    async with BleakScanner(detection_callback=callback):
        if duration:
            await asyncio.sleep(duration)
        else:
            logging.info("Scan en cours — Ctrl-C pour arrêter")
            try:
                await asyncio.Future()   # attente infinie
            except asyncio.CancelledError:
                pass

    logging.info("[SCAN] End of scan.")


# ── Lecture des caractéristiques GATT ─────────────────────────────────────────

async def read_characteristics(address: str):
    """Se connecte au device et lit toutes les caractéristiques connues."""
    logging.info("Connexion GATT à %s…", address)

    async with BleakClient(address) as client:
        logging.info("Connecté (%s)", address)

        print(f"\n{'='*56}")
        print(f"  Caractéristiques GATT — {address}")
        print(f"{'='*56}")

        for name, (uuid, fmt, access, description) in CHARACTERISTICS.items():
            if "r" not in access:
                continue
            try:
                raw = await client.read_gatt_char(uuid)
                value = struct.unpack(fmt, raw)[0]

                # Post-traitement selon la caractéristique
                display = str(value)
                if name == "unix_time":
                    display = f"{value}  ({datetime.fromtimestamp(value, tz=timezone.utc).isoformat()})"
                elif name in ("battery1_voltage", "battery2_voltage"):
                    display = f"{value * 0.01:.2f} V"
                elif name == "temp_offset":
                    display = f"{value / 10:.1f} °C"
                elif name == "temp_units":
                    display = "Fahrenheit" if value else "Celsius"
                elif name in ("zigbee_enabled", "clock_sync", "power_save", "invert_display", "clock_mode_12h"):
                    display = "activé" if value else "désactivé"

                print(f"  {name:<22}: {display:<30}  # {description}")

            except Exception as e:
                print(f"  {name:<22}: ERREUR ({e})")

        print()


# ── Écriture d'une caractéristique GATT ───────────────────────────────────────

async def write_characteristic(address: str, uuid: str, int_value: int):
    """Écrit une valeur entière dans une caractéristique GATT."""
    # Retrouver le format depuis nos définitions
    fmt = "<I"   # défaut uint32
    for name, (u, f, access, _) in CHARACTERISTICS.items():
        if u.lower() == uuid.lower():
            if "w" not in access:
                logging.error("La caractéristique '%s' est en lecture seule.", name)
                return
            fmt = f
            break

    data = struct.pack(fmt, int_value)
    logging.info("Connexion GATT à %s…", address)

    async with BleakClient(address) as client:
        await client.write_gatt_char(uuid, data)
        logging.info("Écriture OK — UUID=%s  valeur=%d  bytes=%s", uuid, int_value, data.hex())


# ── Synchronisation de l'heure ────────────────────────────────────────────────

async def sync_time(address: str, utc_offset_minutes: int = 0):
    """
    Synchronise l'heure UTC et le fuseau horaire du device.

    :param utc_offset_minutes: ex. 120 pour UTC+2
    """
    now_unix = int(time.time())
    logging.info(
        "Sync heure : %s UTC  (offset=%d min)",
        datetime.utcfromtimestamp(now_unix).isoformat(), utc_offset_minutes
    )

    async with BleakClient(address) as client:
        # UNIX timestamp
        uuid_time = CHARACTERISTICS["unix_time"][0]
        await client.write_gatt_char(uuid_time, struct.pack("<I", now_unix))
        logging.info("UNIX time écrit : %d", now_unix)

        # UTC offset
        uuid_offset = CHARACTERISTICS["utc_offset"][0]
        await client.write_gatt_char(uuid_offset, struct.pack("<h", utc_offset_minutes))
        logging.info("UTC offset écrit : %d min", utc_offset_minutes)


# ── Découverte automatique ────────────────────────────────────────────────────

async def discover(duration: float = 10.0) -> list[tuple[str, str]]:
    """
    Cherche des devices BTHome pendant `duration` secondes.
    Retourne une liste de (adresse, nom).
    """
    found: dict[str, str] = {}

    def callback(device: BLEDevice, adv: AdvertisementData):
        if extract_bthome_payload(adv) is not None:
            found[device.address] = device.name or "?"

    logging.info("Découverte des devices BTHome (%ds)…", int(duration))
    async with BleakScanner(detection_callback=callback):
        await asyncio.sleep(duration)

    if found:
        print("\nDevices BTHome détectés :")
        for addr, name in found.items():
            print(f"  {addr}  {name}")
    else:
        print("Aucun device BTHome trouvé.")

    return list(found.items())


# ── CLI ───────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="BTHome Bleak — scanner et client GATT",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    # scan
    s = sub.add_parser("scan", help="Scanner passif des advertisements BTHome")
    s.add_argument("--address", help="Filtrer sur une adresse MAC")
    s.add_argument("--duration", type=float, help="Durée du scan en secondes (défaut: infini)")

    # discover
    sub.add_parser("discover", help="Découvrir les devices BTHome présents (10 s)")

    # read
    r = sub.add_parser("read", help="Lire les caractéristiques GATT du device")
    r.add_argument("--address", required=True, help="Adresse MAC du device")

    # write
    w = sub.add_parser("write", help="Écrire une caractéristique GATT")
    w.add_argument("--address", required=True)
    w.add_argument("--uuid",    required=True, help="UUID de la caractéristique")
    w.add_argument("--value",   required=True, type=int, help="Valeur entière à écrire")

    # sync-time
    t = sub.add_parser("sync-time", help="Synchroniser l'heure du device")
    t.add_argument("--address", required=True)
    t.add_argument("--offset",  type=int, default=0,
                   help="Décalage UTC en minutes (ex: 120 pour UTC+2)")

    return p


async def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.cmd == "scan":
        await scan(target_address=args.address, duration=args.duration)

    elif args.cmd == "discover":
        await discover()

    elif args.cmd == "read":
        await read_characteristics(args.address)

    elif args.cmd == "write":
        await write_characteristic(args.address, args.uuid, args.value)

    elif args.cmd == "sync-time":
        await sync_time(args.address, utc_offset_minutes=args.offset)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-7s  %(message)s",
        datefmt="%H:%M:%S",
    )
    logging = logging.getLogger("bthome")
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Interrompu.")
