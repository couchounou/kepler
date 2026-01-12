import asyncio
from datetime import datetime
from bleak import BleakClient, BleakScanner
import subprocess

notif_event = asyncio.Event()


def parse_notification_14(handle, data):
    notif_event.set()
    if handle == 0x000e:
        hex_str = data.hex()
        s = data.decode('ascii')
        print(f"Notification reçue (handle: {handle}): {hex_str}")
        if data[-1] == 0x0a:  # LF à la fin
            print("... Fin de trame")
        elif data[-1] == 0x0d:  # CR à la fin
            print(f"Trame reçue #2: de {len(s)} caractères: {s}")
            # extraire les valeurs en fonction de la longueur connue
            tension = int(s[0:4])/100
            print(f"R2 - Tension: {tension}")
        else:
            print(f"Trame reçue #1: de {len(s)} caractères: {s}")
            courant = int(s[0:3])       # 0000 → 0 A
            tension = int(s[3:7])/100    # 1280 → 12.8 V
            inconnu = s[7:10]            # 00
            capacity = int(s[10:14])     # 0051 → 51 Ah
            energie = int(s[14:20])     # 000614 → 640 Wh
            print(f"'{datetime.now()}: Courant: {courant} A, Tension: {tension} V, inconnu {inconnu} Ah: {capacity}, Wh: {energie} ")
    else:
        print(f"Notification reçue (handle: {handle}): {data.hex()} (non traité)")

async def find_device_with_timeout(device_name, timeout=10):
    try:
        scanner = BleakScanner(adapter='hci0')
        devices = await scanner.discover(timeout=10)
        if not devices:
            print("Aucun périphérique trouvé.")
        for d in devices:
            if device_name.lower() in (d.name or "").lower():
                return d
        return None
    except Exception as e:
        print(f"Erreur lors du scan BLE: {e}")
        power_on_bluetooth()
        return None


def power_on_bluetooth():
    try:
        result = subprocess.run(
            ["bluetoothctl", "power", "off"],
            capture_output=True,
            text=True,
            check=True
        )
        result = subprocess.run(
            ["bluetoothctl", "power", "on"],
            capture_output=True,
            text=True,
            check=True
        )
        print("Bluetooth activé :", result.stdout)
    except subprocess.CalledProcessError as e:
        print("Erreur lors de l'activation du Bluetooth :", e.stderr)


async def souscription_notifications(client):
    print("  start_notify 0x000e")
    for handle in [0x000e, 0x0025, 0x0029, 0x002d]:
        try:
            print(f"  start_notify {hex(handle)}")
            await client.start_notify(0x000e, parse_notification_14)
        except Exception as e:
            if "Notify acquired" in str(e):
                print("Notification déjà acquise...")
            else:
                raise


async def main():
    address = "00:0d:18:05:53:24"  # Remplace par l'adresse BLE de ton MPPT
    notify_uuid = "f000ffc2-0451-4000-b000-000000000000"  # candidate principale
    i = 1000
    while True:
        print("1-> Recherche device sur hci0 ")
        device = await find_device_with_timeout("Solar ", timeout=15)
        if not device:
            await asyncio.sleep(10)
            continue        
        else:
            print("2-> Tentative de connexion:", device)
            try:
                client = BleakClient(device.address)
                await asyncio.wait_for(client.__aenter__(), timeout=30)
                try:
                    # accès à client.services ou autres opérations
                    for service in client.services:
                        print("   Service:", service.uuid)
                        for char in service.characteristics:
                            print(f"    Char: {char.uuid}, Handle: {char.handle}, Properties: {char.properties}")

                    # Souscrire à toutes les notifications sur le handle 0x000f
                    WRITE_COMMAND = bytearray([0x4F, 0x4B])
                    WRITE_UUID = "00002af1-0000-1000-8000-00805f9b34fb"
                    print("3-> Connexion établie. Souscription aux notifications...")
                    try:
                        await asyncio.wait_for(souscription_notifications(client), timeout=15)
                        print("4-> Envoi requete et ecoute des notifications...")
                        while True:
                            notif_event.clear()
                            await asyncio.wait_for(
                                client.write_gatt_char(WRITE_UUID, WRITE_COMMAND, response=True),
                                timeout=10
                            )
                            try:
                                await asyncio.wait_for(notif_event.wait(), timeout=10)
                                print("Notification reçue dans les 10 secondes !")
                            except asyncio.TimeoutError:
                                print("Aucune notification reçue dans les 10 secondes après write.")
                                continue
                            print("4-> En écoute des notifications sur handle 0x0029, 0x0025 et 0x000e... (Ctrl+C pour arrêter)")
                            await asyncio.sleep(55)
                    except asyncio.TimeoutError:
                        print("Timeout global lors de la souscription aux notifications")
                        continue
                except KeyboardInterrupt:
                    print("Arrêt des notifications...")
                    await client.stop_notify(0x000e)
                    await client.stop_notify(0x0025)
                    await client.stop_notify(0x0029)
                except Exception as e:
                    print(f"Erreur durant la communication avec le MPPT: {e}")
                finally:
                    await client.__aexit__(None, None, None)
            except asyncio.TimeoutError:
                print("Timeout lors de la connexion au MPPT")
            except Exception as e:
                print(f"Erreur Bleak : {e}")
                if "Notify acquired" in str(e):
                    print("Attente de 10 secondes avant nouvelle tentative...")
                    await asyncio.sleep(10)

if __name__ == "__main__":
    print("Démarrage du superviseur BT Antarion...")
    asyncio.run(main())