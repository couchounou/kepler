import asyncio
from bleak import BleakClient

# =========================
# Fonctions de décodage
# =========================


def parse_notification(data: bytearray):
    # convertir bytes ASCII en string
    s = data.decode('ascii')
    print(f"Trame reçue: de {len(s)} caractères: {s}")
    # extraire les valeurs en fonction de la longueur connue
    courant = int(s[0:3])       # 0000 → 0 A
    tension = int(s[3:7])/100    # 1280 → 12.8 V
    capacity = int(s[7:14])     # 0051 → 51 Ah
    energie = int(s[14:20])     # 000614 → 640 Wh

    print(f"rrr - Courant: {courant} A, Tension: {tension} V, Ah: {capacity}, Wh: {energie}")

def decode_zone1(trame_hex):
    """
    Zone 1: Batterie / Charge
    trame_hex : chaîne hex ASCII
    Renvoie : courant (A), tension (V), capacité (Ah), énergie (Wh)
    """
    ascii_str = bytes.fromhex(trame_hex).decode('ascii')
    courant = int(ascii_str[0:6])
    tension = int(ascii_str[6:10]) * 0.1
    capacite = int(ascii_str[10:16])
    energie = int(ascii_str[16:22])
    return courant, tension, capacite, energie

def decode_zone2_3(trame_hex):
    """
    Zone 2+3: Panneau / Sortie
    Renvoie : puissance_panneau (W), tension_panneau (V),
              courant_sortie (A), tension_sortie (V), puissance_sortie (W)
    """
    ascii_str = bytes.fromhex(trame_hex).decode('ascii')
    puissance_panneau = int(ascii_str[0:4])
    tension_panneau = int(ascii_str[4:8]) * 0.1
    courant_sortie = int(ascii_str[8:12])
    tension_sortie = int(ascii_str[12:16]) * 0.1
    puissance_sortie = int(ascii_str[16:20])
    return puissance_panneau, tension_panneau, courant_sortie, tension_sortie, puissance_sortie

# =========================
# Handler de notification
# =========================

def notification_handler(handle, data):
    hex_str = data.hex()
    print(f"Notification reçue (handle: {handle}): {hex_str}")
    # Identifier la zone selon la longueur
    if len(hex_str) == 22*2:  # Zone 1 (22 caractères ASCII)
        parse_notification(data)
    elif len(hex_str) == 20*2:  # Zone 2+3 (20 caractères ASCII)
        parse_notification(data)
    else:
        print("Trame inconnue :", hex_str)

# =========================
# Programme principal
# =========================

async def find_device_with_timeout(device_name, timeout=10):
    print(f"Recherche pendant {timeout} secondes...")
    try:
        devices = await asyncio.wait_for(
            bleak.BleakScanner.discover(timeout=timeout),
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
    while True:
        device = asyncio.run(find_device_with_timeout("Solar regulator"))
        print("-------> Tentative de connexion au MPPT... device:", device)
        try:
            async with BleakClient(address) as client:
                # Affichage des services
                for service in client.services:
                    print("Service:", service.uuid)
                    for char in service.characteristics:
                        print(f"  Char: {char.uuid}, Handle: {char.handle}, Properties: {char.properties}")
            async with BleakClient(address) as client:
                # Souscrire à toutes les notifications sur le handle 0x000f
                WRITE_COMMAND = bytearray([0x4F, 0x4B])
                WRITE_UUID = "00002af1-0000-1000-8000-00805f9b34fb"
                print("Connexion établie. Souscription aux notifications...")
                await client.start_notify(0x0029, notification_handler)
                await client.start_notify(0x002d, notification_handler)
                await client.start_notify(0x0025, notification_handler)
                await client.start_notify(0x000e, notification_handler)
                while True:
                    await client.write_gatt_char(WRITE_UUID, WRITE_COMMAND, response=True)
                    await asyncio.sleep(15)
                print("En écoute des notifications sur handle 0x0029, 0x0025 et 0x000e... (Ctrl+C pour arrêter)")
                try:
                    while True:
                        await asyncio.sleep(1)  # boucle d'attente
                except KeyboardInterrupt:
                    print("Arrêt des notifications...")
                    await client.stop_notify(0x0029)
        except Exception as e:
            print(f"Erreur Bleak : {e}")

# =========================
# Exécution
# =========================

if __name__ == "__main__":
    print("Démarrage du superviseur BT Antarion...")
    asyncio.run(main())