#!/usr/bin/env python3
"""
Lecture des données Shelly H&T Gen3 via Bluetooth (BTHome v2)
Nécessite: pip install bleak
"""

import asyncio
from bleak import BleakScanner
import struct

# Adresse MAC de votre Shelly H&T (à adapter)
SHELLY_MAC = "7C:C6:B6:57:53:BA"  # Remplacer par votre adresse MAC

def decode_bthome_v2(data):
    """Décode les données BTHome v2 du Shelly H&T Gen3"""
    print(data)
    if len(data) < 2:
        return None
    
    result = {}
    i = 0
    
    # BTHome header
    if data[0] == 0x40:  # BTHome v2 avec encryption
        print("Données cryptées - nécessite la clé")
        return None
    
    i = 1  # Skip header
    
    while i < len(data):
        if i >= len(data):
            break
            
        obj_id = data[i]
        i += 1
        
        # Object ID selon BTHome v2
        if obj_id == 0x01:  # Battery %
            if i < len(data):
                result['battery'] = data[i]
                i += 1
                
        elif obj_id == 0x02:  # Temperature (0.01°C)
            if i + 1 < len(data):
                temp_raw = struct.unpack('<h', data[i:i+2])[0]
                result['temperature'] = temp_raw / 100.0
                i += 2
                
        elif obj_id == 0x03:  # Humidity (0.01%)
            if i + 1 < len(data):
                hum_raw = struct.unpack('<H', data[i:i+2])[0]
                result['humidity'] = hum_raw / 100.0
                i += 2
                
        elif obj_id == 0x05:  # Illuminance
            if i + 2 < len(data):
                i += 3
            else:
                i += 1
                
        else:
            # Object ID inconnu, essayer de skip
            i += 1
    
    return result

def decode_service_data(service_data):
    """Extrait les données depuis service_data"""
    for uuid, data in service_data.items():
        # BTHome UUID: 0xFCD2
        if "fcd2" in uuid.lower():
            return decode_bthome_v2(data)
    return None

async def scan_shelly():
    """Scan et affiche les données du Shelly H&T"""
    print(f"Recherche du Shelly H&T...")
    print(f"Adresse MAC cible: {SHELLY_MAC}")
    print("-" * 50)
    
    def callback(device, advertising_data):
        # Filtrer par adresse MAC
        if device.address.upper() == SHELLY_MAC.upper():
            print(f"\n📡 Trame reçue de {device.name or 'Shelly'} ({device.address})")
            print(f"   RSSI: {advertising_data.rssi} dBm")
            
            # Afficher les service data
            if advertising_data.service_data:
                print(f"   Service Data: {advertising_data.service_data}")
                
                # Décoder BTHome
                data = decode_service_data(advertising_data.service_data)
                if data:
                    print(f"\n   ✅ DONNÉES DÉCODÉES:")
                    print(data)
                    if 'temperature' in data:
                        print(f"   🌡️  Température: {data['temperature']:.1f}°C")
                    if 'humidity' in data:
                        print(f"   💧 Humidité: {data['humidity']:.0f}%")
                    if 'battery' in data:
                        print(f"   🔋 Batterie: {data['battery']}%")
                else:
                    print("   ⚠️  Impossible de décoder (données cryptées ou format inconnu)")
            
            # Afficher manufacturer data
            if advertising_data.manufacturer_data:
                print(f"   Manufacturer Data: {advertising_data.manufacturer_data}")
            
            print("-" * 50)
    
    scanner = BleakScanner(callback)
    
    print("⏳ Scan en cours (30 secondes)...")
    print("   Appuyez sur Ctrl+C pour arrêter\n")
    
    await scanner.start()
    await asyncio.sleep(600)
    await scanner.stop()

async def scan_all_devices():
    """Scan tous les devices BLE pour trouver le Shelly"""
    print("🔍 Scan de tous les appareils BLE à proximité...\n")
    
    devices = await BleakScanner.discover(timeout=10.0, return_adv=True)
    
    for device, adv_data in devices.values():
        if "shelly" in (device.name or "").lower():
            print(f"📱 Trouvé: {device.name}")
            print(f"   MAC: {device.address}")
            print(f"   RSSI: {adv_data.rssi} dBm")
            if adv_data.service_data:
                print(f"   Service Data: {adv_data.service_data}")
            print()

if __name__ == "__main__":
    print("=" * 50)
    print("  LECTEUR SHELLY H&T GEN3 - BLUETOOTH")
    print("=" * 50)
    print()
    
    # Option 1: Chercher tous les Shelly
    print("Voulez-vous:")
    print("1) Scanner tous les appareils pour trouver votre Shelly")
    print("2) Lire les données d'un Shelly spécifique (MAC connue)")
    
    choice = input("\nChoix (1/2): ").strip()
    
    try:
        if choice == "1":
            asyncio.run(scan_all_devices())
        else:
            # Modifier SHELLY_MAC en haut du script
            asyncio.run(scan_shelly())
    except KeyboardInterrupt:
        print("\n\n⏹️  Arrêt du scan")