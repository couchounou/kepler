import asyncio
from datetime import datetime
from bleak import BleakClient, BleakScanner

"011131015000020000332140000000000000000"

notif_14 = ""

def parse_notification(data: bytearray):
    global notif_14
    # convertir bytes ASCII en string
    s = data.decode('ascii')
    print(f"Trame reçue: de {len(s)} caractères: {s}")
    if data[-1] == 0x0d:  # CR à la fin
        s = data[:-1].decode('ascii')
        notif_14 += s
        print(f"... trame #2: {s}")
    elif len(data) == 1 and data[-1] == 0x0a:
        print(f"... Fin de trame : {notif_14}")
        courant = int(notif_14[0:3])       # 0000 → 0 A
        tension_batterie = round(int(notif_14[3:7])/100, 2)    # 1280 → 12.8 V
        tension_panneau = round(int(notif_14[20:24])/100, 2)  # 1280 → 12.8 V
        print(f"'{datetime.now()}: Courant: {courant}A, Tension batterie: {tension_batterie}V, Tension panneau: {tension_panneau}V ")
        notif_14 = ""
    else:
        s = data.decode('ascii')
        notif_14 = s + notif_14
        print(f"... trame #1: {s}")
        # 004127005000000000052160000000000000000


def notification_handler(handle, data):
    hex_str = data.hex()
    print(f"Notification reçue (handle: {handle}): {hex_str}")
    parse_notification(data)


async def find_device_with_timeout(device_name, timeout=10):
    print(f"Recherche pendant {timeout} secondes...")
    try:
        devices = await asyncio.wait_for(
            BleakScanner.discover(timeout=timeout),
            timeout=timeout
        )
        
        for device in devices:
            if device.name == device_name:
                print(f"Device trouvé: {device.name}")
                return device
        
        print("Device non trouvé")
        return None
    except asyncio.TimeoutError:
        print("Timeout: recherche dépassée")
        return None


async def main():
    address = "00:0d:18:05:53:24"  # Remplace par l'adresse BLE de ton MPPT
    address = "00:0d:18:05:53:24"  # Remplace par l'adresse BLE de ton MPPT
    notify_uuid = "f000ffc2-0451-4000-b000-000000000000"  # candidate principale
    device = await find_device_with_timeout("Solar regulator", 3)
    while True:
        try: 
            print("-------> Tentative de connexion au MPPT... device:", device)
            async with BleakClient(address, timeout=15.0) as client:
                # Affichage des services
                for service in client.services:
                    print("Service:", service.uuid)
                    for char in service.characteristics:
                        print(f"  Char: {char.uuid}, Handle: {char.handle}, Properties: {char.properties}")
            async with BleakClient(address, timeout=15.0) as client:
                # Souscrire à toutes les notifications sur le handle 0x000f
                WRITE_COMMAND = bytearray([0x4F, 0x4B])
                WRITE_UUID = "00002af1-0000-1000-8000-00805f9b34fb"
                try:
                    print("Nettoyage des notifications existantes...")
                    await client.stop_notify(0x000e)
                except Exception as e:
                    print(f"Erreur lors de l'arrêt des notifications existantes: {e}")
                
                try:
                    print("Souscription aux notifications...")
                    await client.start_notify(0x000e, notification_handler)
                except Exception as e:
                    print(f"Erreur lors de la souscription aux notifications: {e}")
                while True:
                    try:
                        print("Envoi requete et attente notification...")
                        await client.write_gatt_char(WRITE_UUID, WRITE_COMMAND, response=True)
                    except Exception as e:
                        print(f"Erreur lors de l'envoi de la requête: {e}")
                        break
                    print("En écoute des notifications sur handle 0x0029, 0x0025 et 0x000e... (Ctrl+C pour arrêter)")
                    await asyncio.sleep(60)
        except Exception as e:
            print(f"Erreur Bleak : {e}")

# =========================
# Exécution
# =========================

if __name__ == "__main__":
    print("Démarrage du superviseur BT Antarion...")
    asyncio.run(main())