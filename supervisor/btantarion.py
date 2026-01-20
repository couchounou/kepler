import asyncio
from datetime import datetime
from bleak import BleakClient, BleakScanner


class btantarion:
    def __init__(self):
        self.state = {
            "charging_current": 0,
            "battery_voltage": 0.0,
            "panel_voltage": 0.0
        }
        self.notif_14_buffer = ""

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
                        await client.start_notify(
                            0x000e,
                            self.notification_handler
                        )
                    except Exception as e:
                        print(f"Erreur lors de la souscription aux notifications: {e}")
                    while True:
                        try:
                            print("Envoi requete et attente notification...")
                            await client.write_gatt_char(
                                WRITE_UUID,
                                WRITE_COMMAND,
                                response=True
                            )
                        except Exception as e:
                            print(f"Erreur lors de l'envoi de la requête: {e}")
                            break
                        print("En écoute des notifications sur handle 0x000e...")
                        await asyncio.sleep(60)
            except Exception as e:
                print(f"Erreur Bleak : {e}")

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
            self.state["battery_voltage"] = round(
                int(self.notif_14_buffer[3:7])/100, 2
            )  # 1280 → 12.8 V
            self.state["panel_voltage"] = round(
                int(self.notif_14_buffer[20:24])/100, 2
            )  # 1280 → 12.8 V
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

            print("Device non trouvé")
            return None
        except asyncio.TimeoutError:
            print("Timeout: recherche dépassée")
            return None

    def get_state(self):
        return self.state


if __name__ == "__main__":
    supervisor = btantarion()
    asyncio.create_task(supervisor.run())

    # Plus tard, dans le même programme :
    etat = supervisor.get_state()
    print(etat)
