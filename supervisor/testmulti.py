import asyncio
import logging
import time
from victron_ble.devices import SolarCharger
from bthome_ble import BTHomeBluetoothDeviceData
from home_assistant_bluetooth import BluetoothServiceInfoBleak
from bleak import BleakScanner

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("KeplerCentral")

class GlobalStateManager:
    def __init__(self, victron_key: str):
        self.victron_parser = SolarCharger(victron_key)
        self.bthome_parser = BTHomeBluetoothDeviceData()
        
        # Fenêtre de capture (ex: on n'accepte les données que les 15 premières secondes de chaque minute)
        self.intervalle_ecoute_seconds = 120
        self.duree_fenetre_seconds = 30
        
        # Stockage des états actuels
        self.victron_state = {}
        self.bthome_states = {} 

    def _est_dans_la_fenetre_d_ecoute(self) -> bool:
        """Détermine si on est dans la fenêtre temporelle où on accepte de stocker"""
        secondes_courantes = time.time() % self.intervalle_ecoute_seconds
        return secondes_courantes < self.duree_fenetre_seconds

    def update_victron(self, advertise_data):
        """Décode et ne stocke le Victron que si on est dans la fenêtre ET que ça a changé"""
        if not self._est_dans_la_fenetre_d_ecoute():
            return  # On ignore le paquet pour économiser les calculs

        try:
            raw_data = None
            if advertise_data.manufacturer_data:
                for manufacturer_id, data_bytes in advertise_data.manufacturer_data.items():
                    raw_data = data_bytes
                    break

            if raw_data:
                parsed = self.victron_parser.parse(raw_data)
                
                # Récupération des nouvelles valeurs
                nouvelles_valeurs = {
                    "battery_voltage": parsed.get_battery_voltage(),
                    "battery_charging_current": parsed.get_battery_charging_current(),
                    "solar_power": parsed.get_solar_power(),
                    "yield_today": parsed.get_yield_today(),
                    "charge_state": getattr(parsed.get_charge_state(), "name", str(parsed.get_charge_state()))
                }
                
                # 💡 FILTRE DE CHANGEMENT : On compare avec l'ancien état
                if nouvelles_valeurs != self.victron_state:
                    self.victron_state = nouvelles_valeurs
                    print(
                        f"⚡ [CHANGEMENT VICTRON] "
                        f"Batterie: {self.victron_state['battery_voltage']}V / {self.victron_state['battery_charging_current']}A | "
                        f"Panneaux: {self.victron_state['solar_power']}W | "
                        f"Statut: {self.victron_state['charge_state']}"
                    )
        except Exception as e:
            logger.error(f"Erreur stockage Victron : {e}")

    def update_bthome(self, mac_address: str, device_obj, advertise_data):
        """Décode et ne stocke le Shelly que si la valeur a changé (on n'applique pas la fenêtre de temps ici pour ne pas le rater)"""
        try:
            service_info = BluetoothServiceInfoBleak.from_scan(
                "local", device_obj, advertise_data, 0.0, False
            )
            annotation = self.bthome_parser.update(service_info) 
            
            if annotation and annotation.entity_values:
                valeurs_paquet = {dev_key.key: sensor_val.native_value for dev_key, sensor_val in annotation.entity_values.items()}
                
                if mac_address not in self.bthome_states:
                    self.bthome_states[mac_address] = {"name": annotation.title or "Capteur", "temperature": None, "humidity": None, "illuminance": None, "battery": None}
                
                # On vérifie s'il y a du nouveau par rapport à ce qu'on a déjà en mémoire
                un_changement = False
                for cle, valeur in valeurs_paquet.items():
                    if cle in self.bthome_states[mac_address] and self.bthome_states[mac_address][cle] != valeur:
                        self.bthome_states[mac_address][cle] = valeur
                        un_changement = True
                
                # 💡 FILTRE DE CHANGEMENT : On ne print que s'il y a une vraie évolution
                if un_changement:
                    s = self.bthome_states[mac_address]
                    print(f"🌡️ [CHANGEMENT BTHOME] [{s['name']}] T°: {s['temperature']}°C | Hum: {s['humidity']}% | Lum: {s['illuminance']} lx")
                    
        except Exception as e:
            logger.error(f"Erreur stockage BTHome ({mac_address}) : {e}")


# --- CONFIGURATION MATÉRIEL ---
VICTRON_MAC = "FC:40:BC:FC:A8:D4"
VICTRON_KEY = "8ebf134b9339e9524eb24979c5e87505"
LISTE_MAC_BTHOME = ["C0:2C:ED:A8:EE:6E"]

async def main():
    manager = GlobalStateManager(victron_key=VICTRON_KEY)
    logger.info("Démarrage du superviseur Kepler (Optimisé : Fenêtré + Filtre de changement)...")

    def bleak_callback(device, advertisement_data):
        mac_upper = device.address.upper()
        if mac_upper == VICTRON_MAC.upper():
            manager.update_victron(advertisement_data)
        elif mac_upper in [mac.upper() for mac in LISTE_MAC_BTHOME]:
            manager.update_bthome(mac_upper, device, advertisement_data)

    scanner = BleakScanner(detection_callback=bleak_callback, scanning_mode="active")
    await scanner.start()
    
    while True:
        await asyncio.sleep(1)

if __name__ == "__main__":
    asyncio.run(main())