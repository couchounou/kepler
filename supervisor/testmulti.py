import asyncio
import logging
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

# =====================================================================
# CLASSE DE GESTION DES ÉTATS
# =====================================================================
class GlobalStateManager:

    def __init__(self, victron_key: str):
        # Initialisation des décodeurs
        self.victron_parser = SolarCharger(victron_key)
        self.bthome_parser = BTHomeBluetoothDeviceData()
        
        # 💡 Stockage complet de TOUS les attributs Victron
        self.victron_state = {
            "battery_voltage": None,
            "battery_charging_current": None,
            "solar_power": None,
            "yield_today": None,
            "charge_state": None
        }
        self.bthome_states = {} 

    def update_victron(self, advertise_data):
        """Décode et stocke les attributs réels du régulateur Victron MPPT"""
        try:
            raw_data = None
            if advertise_data.manufacturer_data:
                for manufacturer_id, data_bytes in advertise_data.manufacturer_data.items():
                    raw_data = data_bytes
                    break

            if raw_data:
                # Décodage via la bibliothèque officielle
                parsed = self.victron_parser.parse(raw_data)
                
                # 💡 VRAIS ATTRIBUTS DIRECTS (Pas de fonctions, pas de get_)
                self.victron_state.update({
                    "battery_voltage": parsed.battery_voltage,
                    "battery_charging_current": parsed.battery_charging_current,
                    "solar_power": parsed.solar_power,
                    "yield_today": parsed.yield_today,
                    "charge_state": parsed.charge_state
                })
                
                # Traduction texte du mode de fonctionnement
                nom_etat = getattr(parsed.charge_state, "name", str(parsed.charge_state))

                print(
                    f"⚡ [STORE VICTRON] "
                    f"Batterie: {self.victron_state['battery_voltage']}V / {self.victron_state['battery_charging_current']}A | "
                    f"Panneaux: {self.victron_state['solar_power']}W | "
                    f"Rendement du jour: {self.victron_state['yield_today']}Wh | "
                    f"Statut: {nom_etat}"
                )
            else:
                logger.warning("[VICTRON] Paquet reçu mais pas de données constructeur brutes trouvées.")
                
        except Exception as e:
            logger.error(f"Erreur stockage Victron : {e}")

    def update_bthome(self, mac_address: str, device_obj, advertise_data):
        """Décode et stocke les données d'un capteur BTHome (Shelly, etc.)"""
        try:
            service_info = BluetoothServiceInfoBleak.from_scan(
                "local", device_obj, advertise_data, 0.0, False
            )
            annotation = self.bthome_parser.update(service_info) 
            
            if annotation and annotation.entity_values:
                # Extraction brute des nouvelles valeurs reçues
                nouvelles_valeurs = {dev_key.key: sensor_val.native_value for dev_key, sensor_val in annotation.entity_values.items()}
                
                # Si le capteur n'existe pas encore dans notre dictionnaire, on l'initialise
                if mac_address not in self.bthome_states:
                    self.bthome_states[mac_address] = {
                        "name": annotation.title or "Capteur Inconnu",
                        "temperature": None,
                        "humidity": None,
                        "illuminance": None,
                        "battery": None
                    }
                
                # Mise à jour partielle (uniquement ce que le paquet contient)
                for cle, valeur in nouvelles_valeurs.items():
                    if cle in self.bthome_states[mac_address]:
                        if valeur is not None:
                            self.bthome_states[mac_address][cle] = valeur
                
                # Log de l'état actuel de ce capteur spécifique
                s = self.bthome_states[mac_address]
                print(f"🌡️ [STORE BTHOME] [{s['name']}] T°: {s['temperature']}°C | Hum: {s['humidity']}% | Lum: {s['illuminance']} lx | Bat: {s['battery']}%")
                
        except Exception as e:
            logger.error(f"Erreur stockage BTHome ({mac_address}) : {e}")


# =====================================================================
# PROGRAMME PRINCIPAL
# =====================================================================

# --- CONFIGURATION MATÉRIEL ---
VICTRON_MAC = "FC:40:BC:FC:A8:D4"
VICTRON_KEY = "8ebf134b9339e9524eb24979c5e87505"

# Liste de tes adresses MAC BTHome à écouter
LISTE_MAC_BTHOME = [
    "C0:2C:ED:A8:EE:6E",  # Ton Shelly BLU actuel
    # "00:11:22:33:44:55",  # (Exemple d'un deuxième capteur si tu en ajoutes un)
]
# ------------------------------

async def main():
    # Instanciation de notre classe de stockage
    manager = GlobalStateManager(victron_key=VICTRON_KEY)
    
    logger.info("Démarrage du superviseur Kepler (Victron + Multi-BTHome)...")

    def bleak_callback(device, advertisement_data):
        mac_upper = device.address.upper()
        
        # 💡 BIP DE VIE : Affiche TOUS les appareils détectés aux alentours
        # print(f"📡 [ANTENNE ACTIVE] Vu passer l'appareil : {mac_upper} (RSSI: {advertisement_data.rssi})")
        
        if mac_upper == VICTRON_MAC.upper():
            # On ne passe que advertise_data
            manager.update_victron(advertisement_data)
            
        elif mac_upper in [mac.upper() for mac in LISTE_MAC_BTHOME]:
            manager.update_bthome(mac_upper, device, advertisement_data)

    scanner = BleakScanner(detection_callback=bleak_callback, scanning_mode="active")
    await scanner.start()
    
    # Boucle infinie pour maintenir le script en vie
    while True:
        await asyncio.sleep(1)

if __name__ == "__main__":
    asyncio.run(main())