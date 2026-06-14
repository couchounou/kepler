import asyncio
import subprocess
import logging
import time
from datetime import datetime
from bleak import BleakClient
from tstbthome import scan


class Btantarion:
    def __init__(self, scan_addresses=None):
        self.state = {
            "charging_current": 0,
            "charging_capacity": 0,
            "battery_voltage": 0.0,
            "panel_voltage": 0.0,
            "charging_power": 0,
            "energy_daily": 0,
            "last_update": None,
            "bt_temperature": None,
            "bt_humidity": None,
            "bt_last_update": None,
            "bt_light": ""
        }
        self.scan_addresses = [address.upper() for address in scan_addresses] if scan_addresses else None
        self.notif_14_buffer = ""
        self.restart_bluetooth()
        self.address = "00:0D:18:05:53:24"
        self.write_command = bytearray([0x4F, 0x4B])
        self.write_uuid = "00002af1-0000-1000-8000-00805f9b34fb"
        self.scan_duration = 5

    def restart_bluetooth(self):
        """Restart Bluetooth and HCI UART module"""
        logging.info("[BTS] Restarting Bluetooth...")
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
                logging.info("[BTS] [*] %s...", step_name)

                if cmd is None:  # Sleep step
                    time.sleep(2)
                else:
                    result = subprocess.run(cmd, check=True, capture_output=False, text=True, timeout=20)
                    if result.stdout:
                        logging.info("    %s", result.stdout.strip())

                logging.info("[BTS] [✓] %s done", step_name)

            except subprocess.CalledProcessError as e:
                logging.info("[BTS] [✗] Error during %s: %s", step_name, e.stderr)
                continue
            except Exception as e:
                logging.info("[BTS] [✗] Unexpected error: %s", e)
                continue
        logging.info("[BTS] [✓] Bluetooth restart completed successfully")
        return True

    async def run(self, loop=90):
        errors = 0
        while True:
            try:
                if self.scan_addresses:
                    logging.info("[BTS] BTHome scan for %d seconds before MPPT poll", self.scan_duration)
                    await scan(
                        target_address=self.scan_addresses,
                        duration=self.scan_duration,
                        state_obj=self
                    )

                logging.info("[BTS] -------> Tentative de connexion au MPPT... device: %s", self.address)

                async with BleakClient(self.address, timeout=10.0) as client:
                    # Affichage des services
                    for service in client.services:
                        logging.info("[BTS] Service: %s", service.uuid)
                        for char in service.characteristics:
                            logging.info(
                                "  Char: %s, Handle: %s, Properties: %s",
                                char.uuid,
                                char.handle,
                                char.properties
                            )
                async with BleakClient(self.address, timeout=10.0) as client:
                    # Souscrire à toutes les notifications sur le handle 0x000f

                    try:
                        logging.info("[BTS] Nettoyage des notifications existantes...")
                        await client.stop_notify(0x000e)
                    except Exception as e:
                        logging.error("[BTS] Erreur lors de l'arrêt des notifications existantes: %s", e)
                        continue

                    try:
                        logging.info("[BTS] Souscription aux notifications...")
                        await client.start_notify(
                            0x000e,
                            self.notification_handler
                        )
                    except Exception as e:
                        logging.error("[BTS] lors de la souscription aux notifications: %s", e)
                        continue
                    while True:
                        try:
                            logging.info("[BTS] Envoi requete et attente notification...")
                            await client.write_gatt_char(
                                self.write_uuid,
                                self.write_command,
                                response=True
                            )
                        except Exception as e:
                            logging.error("[BTS] Erreur lors de l'envoi de la requête: %s", e)
                            break
                        logging.info("[BTS] En écoute des notifications sur handle 0x000e...")
                        await asyncio.sleep(loop)
                        break
            except Exception as e:
                logging.error("Erreur Bleak : %s", e)
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
        logging.debug("[BTS] Trame reçue: de %d caractères: %s", len(s), s)
        if data[-1] == 0x0d:  # CR à la fin
            s = data[:-1].decode('ascii')
            self.notif_14_buffer += s
        elif len(data) == 1 and data[-1] == 0x0a:
            self.state["charging_current"] = int(
                self.notif_14_buffer[0:3]
            ) / 10  # 001 → 0.1 A
            self.state["battery_voltage"] = round(
                int(self.notif_14_buffer[3:6]) / 10, 2
            )  # 1280 → 12.8 V
            self.state["charging_power"] = int(
                self.notif_14_buffer[6:9]
            )    # 050 → 50 W
            self.state["panel_voltage"] = round(
                int(self.notif_14_buffer[20:23]) / 10, 1
            )  # 1280→ 12.8 V
            self.state["charging_capacity"] = int(
                self.notif_14_buffer[11:14])  # 128→ 128 Ah
            self.state["energy_daily"] = int(
                self.notif_14_buffer[17:20])  # 1280 → 1280 Wh
            self.state["last_update"] = datetime.now().isoformat()
            out = (
                f"{self.notif_14_buffer[0:3]}|"
                f"{self.notif_14_buffer[3:6]}|"
                f"{self.notif_14_buffer[6:9]}|"
                f"{self.notif_14_buffer[9:11]}|"
                f"{self.notif_14_buffer[11:14]}|"
                f"{self.notif_14_buffer[14:17]}|"
                f"{self.notif_14_buffer[17:20]}|"
                f"{self.notif_14_buffer[20:23]}|"
                f"{self.notif_14_buffer[23:]}"
            )
            logging.info("[BTS] Trame complète: %s", out)
            self.notif_14_buffer = ""
            logging.info(
                "[BTS] ---> U batterie: %sV, U panneau: %sV, Courant: %sA, "
                "Puissance: %sW , Capacité: %sAh, Energie quotidienne: %sWh",
                self.state["battery_voltage"],
                self.state["panel_voltage"],
                self.state["charging_current"],
                self.state["charging_power"],
                self.state["charging_capacity"],
                self.state["energy_daily"]
            )
        else:
            s = data.decode('ascii')
            self.notif_14_buffer = s + self.notif_14_buffer
            logging.debug("[BTS] ... trame #1: %s", s)
            # 004127005000000000052160000000000000000

    def notification_handler(self, handle, data):
        hex_str = data.hex()
        logging.info("[BTS] Notification reçue (handle: %s): %s ", handle, hex_str)
        self.parse_notification(data)

    def get_state(self):
        return self.state


if __name__ == "__main__":
    supervisor = Btantarion()

    async def main():
        # Lancer la tâche principale en arrière-plan
        asyncio.create_task(supervisor.run())
        # Boucle de consultation d'état
        while True:
            etat = supervisor.get_state()
            logging.info("[BTS] ----> Test etat depuis main %s", etat)
            await asyncio.sleep(30)  # Affiche l'état toutes les 5 secondes

    asyncio.run(main())
