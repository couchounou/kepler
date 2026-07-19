import asyncio
from victron_ble.devices import SolarCharger
from victron_ble.scanner import Scanner

# --- REMPLACEZ AVEC VOS INFORMATIONS ---
DEVICE_MAC = "AA:BB:CC:DD:EE:FF"  # L'adresse MAC de votre SmartSolar
ENCRYPTION_KEY = "0123456789abcdef0123456789abcdef"  # Votre clé à 32 caractères
# ---------------------------------------


class SmartSolarListener:
    def __init__(self, mac_address, encryption_key):
        self.mac_address = mac_address
        self.encryption_key = encryption_key
        self.parser = SolarCharger(encryption_key)

    async def start_listening(self):
        scanner = Scanner()
        scanner.get_device(self.mac_address, self.handle_data)
        await scanner.start()

    def handle_data(self, data):
        try:
            parsed_data = self.parser.parse(data)
            print(f"État de charge : {parsed_data.get_charge_state()}")
            print(f"Tension Batterie : {parsed_data.get_battery_voltage()} V")
            print(f"Courant de charge : {parsed_data.get_charge_current()} A")
            print(f"Puissance Solaire (Panneaux) : {parsed_data.get_solar_power()} W")
            print(f"Rendement du jour : {parsed_data.get_yield_today()} Wh")
        except Exception as e:
            print(f"Erreur de décodage : {e}")



if __name__ == "__main__":
    listener = SmartSolarListener(DEVICE_MAC, ENCRYPTION_KEY)
    asyncio.run(listener.start_listening())