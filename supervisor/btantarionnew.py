import asyncio
from datetime import datetime
from bleak import BleakClient, BleakScanner
import subprocess
import time

notif_event = asyncio.Event()

"""[Solar regulator]> info
Device 00:0D:18:05:53:24 (public)
        Name: Solar regulator
        Alias: Solar regulator
        Paired: no
        Bonded: no
        Trusted: no
        Blocked: no
        Connected: yes
        LegacyPairing: no
        UUID: Generic Access Profile    (00001800-0000-1000-8000-00805f9b34fb)
        UUID: Generic Attribute Profile (00001801-0000-1000-8000-00805f9b34fb)
        UUID: Device Information        (0000180a-0000-1000-8000-00805f9b34fb)
        UUID: Battery Service           (0000180f-0000-1000-8000-00805f9b34fb)
        UUID: Unknown                   (000018f0-0000-1000-8000-00805f9b34fb)
        UUID: Vendor specific           (f000ffc0-0451-4000-b000-000000000000)
        Modalias: usb:v045Ep0040d0300
        AdvertisingFlags:
  06                                               .
        Battery Percentage: 0x00 (0)
"""


def print_red(text):
    print(f"\033[91m{text}\033[0m")

def print_orange(text):
    print(f"\033[93m{text}\033[0m")


async def find_device_with_timeout(device_name, timeout=5):
    try:
        scanner = BleakScanner(adapter='hci0')
        devices = await scanner.discover(timeout=timeout)
        if not devices:
            print("[BT SOLAR] Aucun périphérique trouvé.")
        for d in devices:
            if device_name.lower() in (d.name or "").lower():
                return d
        return None
    except Exception as e:
        print_red(f"Erreur lors du scan BLE: {e}")
        restart_bluetooth()
        return None


def restart_bluetooth():
    """Restart Bluetooth and HCI UART module"""
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
        print("[BT SOLAR] Bluetooth activé :", result.stdout)
    except subprocess.CalledProcessError as e:
        print_red(f"[BT SOLAR] Erreur lors de l'activation du Bluetooth : {e.stderr}")

    commands = [
        ("Turning Bluetooth power off", ["bluetoothctl", "power", "off"]),
        ("Turning Bluetooth power on", ["bluetoothctl", "power", "on"]),
        ("Waiting 2 seconds", None),  # Special case for sleep
        ("Stopping bluetooth service", ["sudo", "systemctl", "stop", "bluetooth"]),
        ("Unloading hci_uart module", ["sudo", "rmmod", "hci_uart"]),
        ("Waiting 2 seconds", None),  # Special case for sleep
        ("Loading hci_uart module", ["sudo", "modprobe", "hci_uart"]),
        ("Starting bluetooth service", ["sudo", "systemctl", "start", "bluetooth"]),
        ("Waiting 2 seconds", None),  # Special case for sleep
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
            print_red(f"[✗] Error during {step_name}: {e.stderr}")
            return False
        except Exception as e:
            print_red(f"[✗] Unexpected error: {e}")
            return False

    print("[✓] Bluetooth restart completed successfully")
    return True


dataframe = []


async def get_solar_reg_data(cycles=1):
    address = "00:0d:18:05:53:24"

    live_data = {}
    data_event = asyncio.Event()

    def parse_notification_14(handle, data):
        print(f"[BT SOLAR] 6-> handle: {handle}")
        if "00002af0-0000-1000-8000-00805f9b34fb" in str(handle):
            print(f"[BT SOLAR] 6-> Notification reçue (handle: {handle}): {data.decode('ascii')}, {data.hex()}")
            if data[-1] == 0x0a:
                print(f"[BT SOLAR] 6-> Fin de trame , on a {len(dataframe)} chars")
                if len(dataframe) >= 20:
                    s_full = data.decode('ascii')
                    courant = int(s_full[0:3])
                    tension = int(s_full[3:7])/100
                    inconnu = s_full[7:10]
                    capacity = int(s_full[10:14])
                    energie = int(s_full[14:20])
                    live_data.update({
                        "courant": courant,
                        "tension": tension,
                        "inconnu": inconnu,
                        "capacity": capacity,
                        "energie": energie
                    })
                    data_event.set()  # Signale qu'on a reçu des données
                    print(f"[BT SOLAR] 6->    {datetime.now()}: Courant: {courant} A, Tension: {tension} V, inconnu {inconnu} Ah: {capacity}, Wh: {energie} ")
            elif data[-1] == 0x0d:
                s = data[:-1].decode('ascii')
                print(f"[BT SOLAR] 6->      Trame reçue #2: de {len(s)} caractères: {s}")
                dataframe.extend(data[:-1])  # Ignorer le dernier octet CR
            elif data[0] == 0x03:  # STX au début
                s = data[1:].decode('ascii')
                print(f"[BT SOLAR] 6->      Trame reçue #1: de {len(s)} caractères: {s}")
                dataframe[:0] = data[1:]  # Ignorer le premier octet
        else:
            print(f" 6->    Notification reçue (handle: {handle}): {data.hex()} (non traité)")

    async def souscription_notifications(client):
        for handle in ["00002af0-0000-1000-8000-00805f9b34fb"]:
            try:
                print(f"[BT SOLAR]     Try (turn {turn}) start notify -> {handle}")
                await asyncio.wait_for(
                    client.start_notify(
                        handle,
                        parse_notification_14
                    ),
                    timeout=10
                )
                return True
            except asyncio.TimeoutError:
                print_red("[BT SOLAR]     Timeout: Impossible de souscrire")
            except Exception as e:
                if "notify acquired" in str(e).lower():
                    print_orange("[BT SOLAR]     Notification déjà acquise...")
                    # await client.stop_notify(handle)
                    return True
                else:
                    print_red(f"[BT SOLAR]      Erreur lors de la souscription aux notifications: {e}")
        return False

    device = None
    while not device:
        print("[BT SOLAR] 1-> Recherche device sur hci0 ")
        device = await find_device_with_timeout("Solar ", timeout=5)
        if not device:
            print("[BT SOLAR]     Device non trouvé.")
            await asyncio.sleep(5)

    while True:
        print("[BT SOLAR] 2-> Tentative de connexion:", device)
        try:
            async with BleakClient(address, timeout=10.0) as client:
                for service in client.services:
                    print("[BT SOLAR]    Service:", service.uuid)
                    for char in service.characteristics:
                        print(f"[BT SOLAR]         Char: {char.uuid}, Handle: {char.handle}, Properties: {char.properties}")

                WRITE_COMMAND = bytearray([0x4F, 0x4B])
                WRITE_UUID = "00002af1-0000-1000-8000-00805f9b34fb"

                subscribed = False
                turn = 0
                while not subscribed and turn < 3:
                    print("[BT SOLAR] 3-> Souscription aux notifications...")
                    subscribed = await asyncio.wait_for(
                        souscription_notifications(client),
                        timeout=15
                    )
                    if not subscribed:
                        await asyncio.sleep(2)
                        turn += 1

                if subscribed:
                    notif_event.clear()
                    data_event.clear()

                    print("[BT SOLAR] 4-> Envoi requete et attente notification...")
                    turn = 3
                    while turn > 0:
                        try:
                            await asyncio.wait_for(
                                client.write_gatt_char(WRITE_UUID, WRITE_COMMAND, response=False),
                                timeout=3
                            )
                        except asyncio.TimeoutError:
                            print_red("[BT SOLAR]     Impossible d'envoyer la commande dans le délai imparti")
                            turn -= 1
                            continue
                        except Exception as e:
                            print_red(f"[BT SOLAR]     Erreur lors de l'envoi de la commande: {e}")
                            turn -= 1
                            continue
                        print("[BT SOLAR] 5-> Attente des données...")
                        await asyncio.wait_for(data_event.wait(), timeout=3)
                    return live_data
        except asyncio.TimeoutError:
            print_red("[BT SOLAR] Impossible de se connecter dans le délai imparti")
        except Exception as e:
            print_red(f"[BT SOLAR] Erreur Bleak : {e}")
    return None


# ...existing code...


if __name__ == "__main__":
    print("[BT SOLAR] Démarrage du superviseur BT Antarion...")
    restart_bluetooth() 
    try:
        # Timeout global de 60 secondes (modifiable)
        result = asyncio.run(asyncio.wait_for(get_solar_reg_data(), timeout=120))
        print("[BT SOLAR] Résultat:", result)
    except asyncio.TimeoutError:
        print_red("[BT SOLAR] Timeout global atteint, arrêt du superviseur.")
