import asyncio
from datetime import datetime
from bleak import BleakClient, BleakScanner
import subprocess
import time
# =========================
# Fonctions de décodage
# =========================


def parse_notification(data: bytearray):
    # convertir bytes ASCII en string
    s = data.decode('ascii')
    print(f"Trame reçue: de {len(s)} caractères: {s}")
    if data[-1] == 0x0d:  # CR à la fin
        print(f"Trame reçue: de {len(s)} caractères: {s}")
        # extraire les valeurs en fonction de la longueur connue
        tension = int(s[0:4])/100
        print(f"R2 - Tension: {tension}")
    else:
        # extraire les valeurs en fonction de la longueur connue
        courant = int(s[0:3])       # 0000 → 0 A
        tension = int(s[3:7])/100    # 1280 → 12.8 V
        inconnu = s[7:10]            # 00
        capacity = int(s[10:14])     # 0051 → 51 Ah
        energie = int(s[14:20])     # 000614 → 640 Wh
        print(f"'{datetime.now()}: Courant: {courant} A, Tension: {tension} V, inconnu {inconnu} Ah: {capacity}, Wh: {energie} ")


class NotificationParser:
    def __init__(self):
        self.dataframe = ""

    def parse_notification_14(self, handle, data):
        print(f"[BTS] 6-> Notification (handle: {handle}): {data.decode('ascii')}, {data.hex()}")
        if "00002af0-0000-1000-8000-00805f9b34fb" in str(handle):
            if data[-1] == 0x0a:
                print(f"[BTS] 6-> Fin de trame , on a {len(self.dataframe)} chars")
                if len(self.dataframe) >= 20:
                    print(f"dataframe complet: {str(self.dataframe)}")
                    self.dataframe = ""
            elif data[-1] == 0x0d:
                s = data[:-1].decode('ascii')
                print(f"[BTS] 6->      Trame reçue #2: de {len(s)} caractères: {s}")
                self.dataframe += s
            else:
                s = data[1:].decode('ascii')
                print(f"[BTS] 6->      Trame reçue #1: de {len(s)} caractères: {s}")
                self.dataframe = s + self.dataframe
        else:
            print(f" 6->    Notification reçue (handle: {handle}): {data.hex()} (non traité)")


async def find_device_with_timeout(device_name, timeout=15):
    print(f"Recherche pendant {timeout} secondes...")
    device_name = device_name.lower()
    try:
        devices = await BleakScanner.discover(timeout=timeout)
        
        for device in devices:
            if device.name:
                print(f"  Device trouvé: {device.name}, adresse: {device.address}")
                if device_name in device.name.lower():
                    print(f"Device trouvé: {device.name}")
                    return device
        
        print("Device non trouvé")
        return None
    except asyncio.TimeoutError:
        print("Timeout: recherche dépassée")
        return None
    except Exception as e:
        print(f"Erreur lors du scan BLE: {e}")
        return None


async def main():
    address = "00:0d:18:05:53:24"  # Remplace par l'adresse BLE de ton MPPT
    address = "00:0d:18:05:53:24"  # Remplace par l'adresse BLE de ton MPPT
    notify_uuid = "f000ffc2-0451-4000-b000-000000000000"  # candidate principale
    device = await find_device_with_timeout("Solar", timeout=5)
    while True:
        try:
            print("-------> Tentative de connexion au MPPT... device:", device)
            async with BleakClient(address, timeout=15.0) as client:
                # Affichage des services
                for service in client.services:
                    print("Service:", service.uuid)
                    for char in service.characteristics:
                        print(f"  Char: {char.uuid}, Handle: {char.handle}, Properties: {char.properties}")
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
                    parser = NotificationParser()
                    await client.start_notify(0x000e, parser.parse_notification_14)
                except Exception as e:
                    print(f"Erreur lors de la souscription aux notifications: {e}")

                try:
                    print("Envoi requete et attente notification...")
                    await client.write_gatt_char(WRITE_UUID, WRITE_COMMAND, response=True)
                except Exception as e:
                    print(f"Erreur lors de l'envoi de la requête: {e}")
                print("En écoute des notifications sur handle 0x0029, 0x0025 et 0x000e... (Ctrl+C pour arrêter)")
                await asyncio.sleep(15)
        except Exception as e:
            print(f"Erreur Bleak : {e}")
        restart_bluetooth()


def restart_bluetooth():
    """Restart Bluetooth and HCI UART module"""
    commands = [
        ("Turning Bluetooth power off", ["bluetoothctl", "power", "off"]),
        ("Stopping bluetooth service", ["sudo", "systemctl", "stop", "bluetooth"]),
        ("Unloading hci_uart module", ["sudo", "rmmod", "hci_uart"]),
        ("Waiting 2 seconds", None),
        ("Loading hci_uart module", ["sudo", "modprobe", "hci_uart"]),
        ("Waiting 1 seconds", None),
        ("Starting bluetooth service", ["sudo", "systemctl", "start", "bluetooth"]),
        ("Waiting 1 seconds", None),
        ("Turning Bluetooth power on", ["bluetoothctl", "power", "on"]),
        ("Waiting 2 seconds", None),
    ]

    for step_name, cmd in commands:
        try:
            print(f"[*] {step_name}...")

            if cmd is None:  # Sleep step
                time.sleep(2)
            else:
                result = subprocess.run(cmd, check=True, capture_output=True, text=True)
                if result.stdout:
                    print(f"    {result.stdout.strip()}")

            print(f"[✓] {step_name} done")

        except subprocess.CalledProcessError as e:
            print(f"[✗] Error during {step_name}: {e.stderr}")
        except Exception as e:
            print(f"[✗] Unexpected error: {e}")

    print("[✓] Bluetooth restart completed successfully")
    return True    


if __name__ == "__main__":
    print("Démarrage du superviseur BT Antarion...")
    asyncio.run(main())