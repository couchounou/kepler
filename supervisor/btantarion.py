import asyncio
from datetime import datetime
from bleak import BleakClient, BleakScanner

def parse_notification_14(handle, data):
    # convertir bytes ASCII en string
    hex_str = data.hex()
    s = data.decode('ascii')
    print(f"Notification reçue (handle: {handle}): {hex_str}")
    print(f"Trame reçue: de {len(s)} caractères: {s}")
    if data[-1] == 0x0a:  # LF à la fin
        print(f"... Fin de trame")
    elif data[-1] == 0x0d:  # CR à la fin
        print(f"Trame reçue #1: de {len(s)} caractères: {s}")
        # extraire les valeurs en fonction de la longueur connue
        tension = int(s[0:4])/100
        print(f"R2 - Tension: {tension}")
    else:
        print(f"Trame reçue #2: de {len(s)} caractères: {s}")
        courant = int(s[0:3])       # 0000 → 0 A
        tension = int(s[3:7])/100    # 1280 → 12.8 V
        inconnu = s[7:10]            # 00
        capacity = int(s[10:14])     # 0051 → 51 Ah
        energie = int(s[14:20])     # 000614 → 640 Wh
        print(f"'{datetime.datetime.now()}: Courant: {courant} A, Tension: {tension} V, inconnu {inconnu} Ah: {capacity}, Wh: {energie} ")


async def find_device_with_timeout(device_name, timeout=10):
    print("Recherche device sur hci0 ")
    scanner = BleakScanner(adapter='hci0')
    devices = await scanner.discover(timeout=10)
    if not devices:
        print("Aucun périphérique trouvé.")
    for d in devices:s
        if device_name.lower() in (d.name or "").lower():
            return d
    return None


async def main():
    address = "00:0d:18:05:53:24"  # Remplace par l'adresse BLE de ton MPPT
    notify_uuid = "f000ffc2-0451-4000-b000-000000000000"  # candidate principale
    while True:
        device = await find_device_with_timeout("Solar ", timeout=15)
        if not device:
            await asyncio.sleep(10)
            continue        
        else:
            print("Tentative de connexion au MPPT... device:", device)
            try:
                client = BleakClient(device.address)
                await asyncio.wait_for(client.__aenter__(), timeout=10)
                try:
                    # accès à client.services ou autres opérations
                    for service in client.services:
                        print("Service:", service.uuid)
                        for char in service.characteristics:
                            print(f"  Char: {char.uuid}, Handle: {char.handle}, Properties: {char.properties}")

                    # Souscrire à toutes les notifications sur le handle 0x000f
                    WRITE_COMMAND = bytearray([0x4F, 0x4B])
                    WRITE_UUID = "00002af1-0000-1000-8000-00805f9b34fb"
                    print("Connexion établie. Souscription aux notifications...")
                    await client.start_notify(0x000e, notification_handler_1)
                    while i:
                        while True:
                            await client.write_gatt_char(WRITE_UUID, WRITE_COMMAND, response=True)
                            await asyncio.sleep(15)
                            print("En écoute des notifications sur handle 0x0029, 0x0025 et 0x000e... (Ctrl+C pour arrêter)")
                except KeyboardInterrupt:
                    print("Arrêt des notifications...")
                    await client.stop_notify(0x000e)
                finally:
                    await client.__aexit__(None, None, None)
            except asyncio.TimeoutError:
                print("Timeout lors de la connexion au MPPT")
            except Exception as e:
                print(f"Erreur Bleak : {e}")

if __name__ == "__main__":
    print("Démarrage du superviseur BT Antarion...")
    asyncio.run(main())