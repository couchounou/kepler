import asyncio
import sys
import time
from datetime import datetime
import logging
import random
import configparser
import os

try:
    import board
    import busio
    import adafruit_ads1x15.ads1115 as ADS
    import adafruit_ads1x15.ads1x15 as ADSbase
    from adafruit_ads1x15.analog_in import AnalogIn
except:
    logging.warning("Failed to import Adafruit ADS1115 libraries. Ensure they are installed.")
    pass
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS
from influxdb_client.client.exceptions import InfluxDBError
from lte_init import test_ping, ready_or_connect, wlan0_has_internet
from bleak import BleakScanner
from bleak import BleakClient
SHELLY_MAC = "30:30:F9:E7:07:76"
SHELLY_MAC_2 = "7C:C6:B6:57:53:BA"
POINTS = []
BUCKET = None
ORG = None
TOKEN = None
SERVER = None
INTERVAL = 30  # seconds

client = None 

write_api = client.write_api(write_options=SYNCHRONOUS)


class SiteStatus:
    def __init__(self, site_id: str):
        self.site_id = site_id
        self.reset()

    def reset(self):
        self.status = {
            "voltage_1": 0.0,
            "voltage_2": 0.0,
            "water_level": 0.0,
            "temperature_1": 0.0,
            "temperature_2": 0.0
        }

    def update(self, **kwargs):
        """
        Update the status dictionary with new values for existing keys.

        Parameters:
            **kwargs: Arbitrary keyword arguments 
            where each key corresponds to a field in the status dictionary,
            and each value is converted to a float
            and assigned to the corresponding key.

        Raises:
            KeyError: If any provided key does not exist
            in the status dictionary.
        """

        for key, value in kwargs.items():
            if key in self.status:
                self.status[key] = float(value)
            else:
                raise KeyError(f"{key} n'est pas un champ valide")

    def to_point(self):
        """
        Converts the current object's status into an InfluxDB Point.
        Returns:
            Point: An InfluxDB Point object
            with the measurement name "site_metrics",
                   tagged with the site's ID, containing
                   all status fields as float values,
                   and timestamped with the current UTC time.
        """
        
        point = Point("site_metrics").tag("site_id", self.site_id)
        for field, value in self.status.items():
            point = point.field(field, float(value))
        point = point.time(datetime.utcnow())
        return point

    def __repr__(self):
        return f"SiteStatus(site_id={self.site_id}, status={self.status})"


SiteStatus_instance = SiteStatus(site_id="site_001")


def influx_write_pts(points: list, bucket: str = BUCKET) -> None:
    try:
        write_api.write(org=ORG, bucket=bucket, record=points)
        return True
    except InfluxDBError as e:
        if e.response.status == 401 or e.response.status == 403:
            logging.warning("[influx] insufficient rights to %s", bucket)
        else:
            logging.warning("[influx] influx error %r", e)
    except Exception as e:
        if hasattr(e, "reason"):
            logging.warning("[influx] for bucket :%s : %s", bucket, e.reason)
        else:
            logging.warning("[influx] for bucket: %s: %s", bucket, e)
    return False


def read_all_ads1115_channels_fake():
    SiteStatus_instance.update(
        voltage_1=random.uniform(0, 15),
        voltage_2=random.uniform(0, 15),
        water_level=random.uniform(0, 100),
        temperature_1=random.uniform(-10, 50)
    )


def read_all_ads1115_channels():
    """
    Reads all 4 channels from the ADS1115 ADC
    and returns their values as a list.
    """
    i2c = busio.I2C(board.SCL, board.SDA)
    ads = ADS.ADS1115(i2c)
    channels = [
        AnalogIn(ads, 0),
        AnalogIn(ads, 1),
        AnalogIn(ads, 2),
        AnalogIn(ads, 3)
    ]
    print("channel voltages:", [ch.voltage for ch in channels])
    SiteStatus_instance.update(
        voltage_1=channels[0].voltage * 3.965,
        voltage_2=channels[1].voltage * 3.98,
        water_level=channels[2].voltage * 4.59,
        temperature_1=channels[3].voltage * 4.59
    )


def read_loop(interval_minutes=0.1):
    """
    Continuously reads all 4 ADS1115 channels
    every 'interval_minutes' minutes and prints the results.
    """
    while True:
        read_all_ads1115_channels()
        print(SiteStatus_instance)
        POINTS.append(SiteStatus_instance.to_point())
        SiteStatus_instance.reset()

        connected = False
        if not test_ping(1):
            connected = ready_or_connect(force=False)
        else:
            connected = True

        if connected:
            if influx_write_pts(POINTS):
                POINTS.clear()
                print("Points successfully written to InfluxDB.")
            else:
                print("Failed to write points to InfluxDB.")
        else:
            print("No internet connection. Points not sent.")
        time.sleep(interval_minutes * 60)


def decode_shelly_htg3(data: bytes):
    """
    Format Shelly H&T Gen3 (BLE advertising)
    """
    # Température : int16, centi-degrés
    temp = int.from_bytes(data[6:8], "little", signed=True) / 100

    # Humidité : uint16, centi-pourcent
    hum = int.from_bytes(data[8:10], "little") / 100

    # Batterie : pourcentage
    battery = data[10]

    return temp, hum, battery


def decode_shelly_htg3(data: bytes):
    """
    Décodage du broadcast BLE du Shelly H&T Gen3.
    data : manufacturer_data (bytes)
    """
    # Température : octets 4-5 (little endian), centi°C
    temp = int.from_bytes(data[4:6], "little", signed=True) / 100
    # Humidité : octets 6-7 (little endian), centi-%
    hum = int.from_bytes(data[6:8], "little") / 100
    # Batterie : octet 8
    battery = data[8]  # généralement 0-100%
    return temp, hum, battery


def detection_callback(device, advertisement_data):
    # Filtrer uniquement ton Shelly
    if device.address != SHELLY_MAC:
        return

    # manufacturer_data peut contenir plusieurs clefs
    for _, data in advertisement_data.manufacturer_data.items():
        print(data)
        if len(data) >= 9:  # vérifier longueur
            temp, hum, batt = decode_shelly_htg3(data)
            print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} | "
                  f"🌡️ {temp:.2f} °C | 💧 {hum:.1f} % | 🔋 {batt} %")


async def smain():
    scanner = BleakScanner(detection_callback)
    await scanner.start()
    print("🔍 Écoute BLE Shelly H&T Gen3 en continu…")
    try:
        while True:
            await asyncio.sleep(3600)  
            # boucle infinie, callback déclenché à chaque trame
    finally:
        await scanner.stop()

# UUID des caractéristiques (exemple générique, à ajuster pour H&T Gen3)
UUID_TEMP = "00002a6e-0000-1000-8000-00805f9b34fb"  # Temperature
UUID_HUM = "00002a6f-0000-1000-8000-00805f9b34fb"   # Humidity
UUID_BATT = "00002a19-0000-1000-8000-00805f9b34fb"  # Battery Level


async def read_shelly():
    async with BleakClient(SHELLY_MAC) as client:
        temp_bytes = await client.read_gatt_char(UUID_TEMP)
        hum_bytes = await client.read_gatt_char(UUID_HUM)
        batt_bytes = await client.read_gatt_char(UUID_BATT)

        temp = int.from_bytes(temp_bytes, "little", signed=True) / 100
        hum = int.from_bytes(hum_bytes, "little") / 100
        batt = int(batt_bytes[0])

        print(f"🌡️ {temp:.1f} °C | 💧 {hum:.1f} % | 🔋 {batt} %")


if __name__ == "__main__":
    cfgname = sys.argv[0][:-2] + "cfg"
    Config = configparser.ConfigParser()
    if os.path.exists(cfgname):
        Config.read(cfgname)
        TOKEN = Config.get("influx", "token")
        SERVER = Config.get("influx", "server")
        BUCKET = Config.get("influx", "bucket")
        ORG = Config.get("influx", "org")
    client = InfluxDBClient(
        url=SERVER,
        token=TOKEN,
        org=ORG
    )
    read_loop()
