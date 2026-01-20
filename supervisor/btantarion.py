import asyncio
import subprocess
import random
import time
from datetime import datetime
from bleak import BleakClient, BleakScanner


class btantarion:
    def __init__(self):
        self.state = {
            "charging_current": 0,
            "battery_voltage": 0.0,
            "panel_voltage": 0.0,
            "charging_power": 0,
            "energy_daily": 0,
            "last_update": None
        }
        self.notif_14_buffer = ""
        self.restart_bluetooth()

    def restart_bluetooth(self):
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
                print(f"[BTS] [*] {step_name}...")

                if cmd is None:  # Sleep step
                    time.sleep(2)
                else:
                    result = subprocess.run(cmd, check=True, capture_output=True, text=True)
                    if result.stdout:
                        print(f"    {result.stdout.strip()}")

                print(f"[BTS] [✓] {step_name} done")

            except subprocess.CalledProcessError as e:
                print(f"[BTS] [✗] Error during {step_name}: {e.stderr}")
            except Exception as e:
                print(f"[BTS] [✗] Unexpected error: {e}")
                continue
        print("[BTS] [✓] Bluetooth restart completed successfully")
        return True

    async def run(self):
        address = "00:0d:18:05:53:24"
        notify_uuid = "f000ffc2-0451-4000-b000-000000000000"
        device = await self.find_device_with_timeout("Solar regulator", 3)
        while True:
            try:
                print(
                    "-------> Tentative de connexion au MPPT... device:",
                    device
                )
                async with BleakClient(address, timeout=15.0) as client:
                    # Affichage des services
                    for service in client.services:
                        print("[BTS] Service:", service.uuid)
                        for char in service.characteristics:
                            print(f"  Char: {char.uuid}, Handle: {char.handle}, Properties: {char.properties}")
                async with BleakClient(address, timeout=15.0) as client:
                    # Souscrire à toutes les notifications sur le handle 0x000f
                    WRITE_COMMAND = bytearray([0x4F, 0x4B])
                    WRITE_UUID = "00002af1-0000-1000-8000-00805f9b34fb"
                    try:
                        print("[BTS] Nettoyage des notifications existantes...")
                        await client.stop_notify(0x000e)
                    except Exception as e:
                        print(f"Erreur lors de l'arrêt des notifications existantes: {e}")

                    try:
                        print("[BTS] Souscription aux notifications...")
                        await client.start_notify(
                            0x000e,
                            self.notification_handler
                        )
                    except Exception as e:
                        print(f"Erreur lors de la souscription aux notifications: {e}")
                    while True:
                        try:
                            print("[BTS] Envoi requete et attente notification...")
                            await client.write_gatt_char(
                                WRITE_UUID,
                                WRITE_COMMAND,
                                response=True
                            )
                        except Exception as e:
                            print(f"Erreur lors de l'envoi de la requête: {e}")
                            break
                        print("[BTS] En écoute des notifications sur handle 0x000e...")
                        await asyncio.sleep(60)
            except Exception as e:
                print(f"Erreur Bleak : {e}")
                continue

    def parse_notification(self, data: bytearray):
        # convertir bytes ASCII en string
        s = data.decode('ascii')
        print(f"Trame reçue: de {len(s)} caractères: {s}")
        if data[-1] == 0x0d:  # CR à la fin
            s = data[:-1].decode('ascii')
            self.notif_14_buffer += s
        elif len(data) == 1 and data[-1] == 0x0a:
            self.state["charging_current"] = int(
                self.notif_14_buffer[0:3]
            )  # 001 → 1 A
            self.state["charging_power"] = int(
                self.notif_14_buffer[7:10]
            )  # 050 → 50 W
            self.state["battery_voltage"] = round(
                int(self.notif_14_buffer[3:7]) / 100, 2
            )  # 1280 → 12.8 V
            self.state["panel_voltage"] = round(
                int(self.notif_14_buffer[20:24]) / 100, 2
            )  # 1280 → 12.8 V
            self.state["energy_daily"] = int(
                self.notif_14_buffer[17:20])  # 1280 → 1280 Wh
            self.state["last_update"] = datetime.now().isoformat()
            print(f"'{datetime.now()}: Courant: {self.state['charging_current']}A, Tension batterie: {self.state['battery_voltage']}V, Tension panneau: {self.state['panel_voltage']}V ")
            out = ""
            out += f"\033[92m{self.notif_14_buffer[0:3]}\033[0m"
            out += f"\033[92m{self.notif_14_buffer[3:7]}\033[0m"
            out += self.notif_14_buffer[7:20]
            out += f"\033[92m{self.notif_14_buffer[20:24]}\033[0m" + self.notif_14_buffer[24:]
            print(f"Trame complète: {out}")
            self.notif_14_buffer = ""
        else:
            s = data.decode('ascii')
            self.notif_14_buffer = s + self.notif_14_buffer
            print(f"... trame #1: {s}")
            # 004127005000000000052160000000000000000

    def notification_handler(self, handle, data):
        hex_str = data.hex()
        print(f"Notification reçue (handle: {handle}): {hex_str}")
        self.parse_notification(data)

    async def find_device_with_timeout(self, device_name, timeout=10):
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

            print("[BTS] Device non trouvé")
            return None
        except asyncio.TimeoutError:
            print("[BTS] Timeout: recherche dépassée")
            return None

    def get_state(self):
        return self.state


if __name__ == "__main__":
    supervisor = btantarion()

    async def main():
        # Lancer la tâche principale en arrière-plan
        asyncio.create_task(supervisor.run())
        # Boucle de consultation d'état
        while True:
            etat = supervisor.get_state()
            print("[BTS] ----> Test etat depuis main " + str(etat))
            await asyncio.sleep(30)  # Affiche l'état toutes les 5 secondes

    asyncio.run(main())
