import asyncio
import subprocess
import time
from datetime import datetime
from bleak import BleakClient, BleakScanner
import logging
import sys

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("kepler.log")
    ]
)
logging.info("Service démarré")
import logging, sys

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("kepler.log")
    ]
)
logging.info("Service démarré")

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
        self.address = "00:0d:18:05:53:24"
        self.WRITE_COMMAND = bytearray([0x4F, 0x4B])
        self.WRITE_UUID = "00002af1-0000-1000-8000-00805f9b34fb"

    def restart_bluetooth(self):
        """Restart Bluetooth and HCI UART module"""
        logging.info("[BTS] Restarting Bluetooth...")
        commands = [
            ("Turning Bluetooth power off", ["bluetoothctl", "power", "off"]),
            ("Stopping bluetooth service", [
                "sudo",
                "systemctl",
                "stop",
                "bluetooth"
                ]
            ),
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
                logging.info(f"[BTS] [*] {step_name}...")

                if cmd is None:  # Sleep step
                    time.sleep(2)
                else:
                    result = subprocess.run(cmd, check=True, capture_output=True, text=True)
                    if result.stdout:
                        logging.info(f"    {result.stdout.strip()}")

                logging.info(f"[BTS] [✓] {step_name} done")

            except subprocess.CalledProcessError as e:
                logging.info(f"[BTS] [✗] Error during {step_name}: {e.stderr}")
                continue
            except Exception as e:
                logging.info(f"[BTS] [✗] Unexpected error: {e}")
                continue
        logging.info("[BTS] [✓] Bluetooth restart completed successfully")
        return True

    async def run(self, loop=90):
        device = await self.find_device_with_timeout("regulator", timeout=20)
        if device is None:
            logging.info("[BTS] Device 'regulator' non trouvé")
        else:
            logging.info(f"[BTS] Device trouvé: {device.address}")
            self.address = device.address
        errors = 0
        while True:
            try:
                logging.info(f"[BTS] -------> Tentative de connexion au MPPT... device: {self.address}")

                async with BleakClient(self.address, timeout=10.0) as client:
                    # Affichage des services
                    for service in client.services:
                        logging.info(f"[BTS] Service: {service.uuid}")
                        for char in service.characteristics:
                            logging.info(f"  Char: {char.uuid}, Handle: {char.handle}, Properties: {char.properties}")
                async with BleakClient(self.address, timeout=10.0) as client:
                    # Souscrire à toutes les notifications sur le handle 0x000f

                    try:
                        logging.info("[BTS] Nettoyage des notifications existantes...")
                        await client.stop_notify(0x000e)
                    except Exception as e:
                        logging.info(f"Erreur lors de l'arrêt des notifications existantes: {e}")
                        continue

                    try:
                        logging.info("[BTS] Souscription aux notifications...")
                        await client.start_notify(
                            0x000e,
                            self.notification_handler
                        )
                    except Exception as e:
                        logging.info(f"Erreur lors de la souscription aux notifications: {e}")
                        continue
                    while True:
                        try:
                            logging.info("[BTS] Envoi requete et attente notification...")
                            await client.write_gatt_char(
                                self.WRITE_UUID,
                                self.WRITE_COMMAND,
                                response=True
                            )
                        except Exception as e:
                            logging.info(f"Erreur lors de l'envoi de la requête: {e}")
                            break
                        logging.info("[BTS] En écoute des notifications sur handle 0x000e...")
                        await asyncio.sleep(loop)
            except Exception as e:
                logging.info(f"Erreur Bleak : {e}")
                errors += 1
                if errors >= 10:
                    logging.info("[BTS] Trop d'erreurs, redémarrage du Bluetooth")
                    self.restart_bluetooth()
                    errors = 0
                else:
                    await asyncio.sleep(5)
                continue

    def parse_notification(self, data: bytearray):
        # convertir bytes ASCII en string
        s = data.decode('ascii')
        logging.info(f"Trame reçue: de {len(s)} caractères: {s}")
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
                int(self.notif_14_buffer[20:23]) / 100, 1
            )  # 1280 → 12.8 V
            self.state["energy_daily"] = int(
                self.notif_14_buffer[17:20])  # 1280 → 1280 Wh
            self.state["last_update"] = datetime.now().isoformat()
            logging.info(f"'{datetime.now()}: Courant: {self.state['charging_current']}A, Tension batterie: {self.state['battery_voltage']}V, Tension panneau: {self.state['panel_voltage']}V ")
            out = ""
            out += f"\033[92m{self.notif_14_buffer[0:3]}\033[0m"
            out += f"\033[92m{self.notif_14_buffer[3:7]}\033[0m"
            out += self.notif_14_buffer[7:20]
            out += f"\033[92m{self.notif_14_buffer[20:23]}\033[0m" + self.notif_14_buffer[23:]
            logging.info(f"Trame complète: {out}")
            self.notif_14_buffer = ""
        else:
            s = data.decode('ascii')
            self.notif_14_buffer = s + self.notif_14_buffer
            logging.info(f"... trame #1: {s}")
            # 004127005000000000052160000000000000000

    def notification_handler(self, handle, data):
        hex_str = data.hex()
        logging.info(f"Notification reçue (handle: {handle}): {hex_str}")
        self.parse_notification(data)

    async def find_device_with_timeout(self, device_name, timeout=20):
        logging.info("[BTS] Recherche devices sur hci0...")
        try:
            devices = await BleakScanner.discover(timeout=timeout)
            for device in devices:
                logging.info(f"[BTS] Device: {device}")
                if device.name and device_name.lower() in device.name.lower():
                    logging.info(f"[BTS] Device trouvé: {device.name}")
                    return device

            logging.info("[BTS] Device non trouvé")
            return None
        except asyncio.TimeoutError:
            logging.info("[BTS] Timeout: recherche dépassée")
            return None
        except Exception as e:
            logging.info(f"[BTS] Erreur lors de la recherche des devices: {e}")
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
            logging.info("[BTS] ----> Test etat depuis main " + str(etat))
            await asyncio.sleep(30)  # Affiche l'état toutes les 5 secondes

    asyncio.run(main())