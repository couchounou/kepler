from datetime import datetime, UTC
import random
import configparser
import os
import asyncio
import sys
import math
import logging
try:
    import board
    import busio
    import adafruit_ads1x15.ads1115 as ADS
    import adafruit_ads1x15.ads1x15 as ADSbase
    from adafruit_ads1x15.analog_in import AnalogIn
    ADAFRUIT_AVAILABLE = True
except:
    print("Failed to import Adafruit ")
    ADAFRUIT_AVAILABLE = False
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS
from influxdb_client.client.exceptions import InfluxDBError
from lte_init import test_ping, ready_or_connect
from btantarion import btantarion

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("kepler.log")
    ]
)
logging.info("Service démarré")

SHELLY_MAC = "30:30:F9:E7:07:76"
SHELLY_MAC_2 = "7C:C6:B6:57:53:BA"
POINTS = []
BUCKET = None
ORG = None
TOKEN = None
SERVER = None
INTERVAL = 30  # seconds
CLIENT = None
WRITE_API = None
VCC = 3.3               # Alimentation
R_FIXED = 10000.0       # Résistance fixe (ohms)
R0 = 10000.0            # NTC à 25°C
BETA = 3950.0           # Coefficient Beta
T0 = 298.15             # 25°C en Kelvi

def lead_soc(voltage, temperature_c):
    """
    Estime le SOC (%) d'une batterie plomb 12V
    :param voltage: tension mesurée (V) batterie au repos
    :param temperature_c: température en °C
    :return: SOC en %
    """

    # Table SOC vs tension à 25°C (batterie plomb ouverte)
    soc_table = [
        (100, 12.70),
        (90, 12.60),
        (80, 12.50),
        (70, 12.40),
        (60, 12.30),
        (50, 12.20),
        (40, 12.10),
        (30, 12.00),
        (20, 11.90),
        (10, 11.80),
        (0, 11.70),
    ]

    # Correction température vers 25 °C
    # Coefficient plomb ≈ 18 mV / °C pour une batterie 12 V
    corrected_voltage = voltage + (25 - temperature_c) * 0.018

    # Bornes
    if corrected_voltage >= soc_table[0][1]:
        return 100.0
    if corrected_voltage <= soc_table[-1][1]:
        return 0.0

    # Interpolation linéaire
    for i in range(len(soc_table) - 1):
        soc1, v1 = soc_table[i]
        soc2, v2 = soc_table[i + 1]

        if v1 >= corrected_voltage >= v2:
            soc = soc1 + (soc2 - soc1) * (v1 - corrected_voltage) / (v1 - v2)
            logging.info("[MAIN] Lead SOC calculated: %f for voltage: %f and temp: %f", soc, voltage, temperature_c)
            return round(soc, 1)

    return None


def agm_soc(voltage, temperature_c):
    """
    Estime le SOC (%) d'une batterie AGM 12V
    :param voltage: tension mesurée (V) batterie au repos
    :param temperature_c: température en °C
    :return: SOC en %
    """

    # Table SOC vs tension à 25°C (AGM)
    soc_table = [
        (100, 12.85),
        (90, 12.75),
        (80, 12.65),
        (70, 12.55),
        (60, 12.45),
        (50, 12.35),
        (40, 12.25),
        (30, 12.15),
        (20, 12.05),
        (10, 11.95),
        (0, 11.80),
    ]

    # Correction température (−15 mV / °C pour une batterie 12 V)
    corrected_voltage = voltage + (25 - temperature_c) * 0.015

    # Bornes
    if corrected_voltage >= soc_table[0][1]:
        return 100.0
    if corrected_voltage <= soc_table[-1][1]:
        return 0.0

    # Interpolation linéaire
    for i in range(len(soc_table) - 1):
        soc1, v1 = soc_table[i]
        soc2, v2 = soc_table[i + 1]

        if v1 >= corrected_voltage >= v2:
            soc = soc1 + (soc2 - soc1) * (v1 - corrected_voltage) / (v1 - v2)
            logging.info("[MAIN] Lead SOC calculated: %f for voltage: %f and temp: %f", soc, voltage, temperature_c)
            return round(soc, 1)

    return None


def ntc_temperature(voltage):
    if voltage <= 0 or voltage >= VCC:
        return None

    r_ntc = R_FIXED * (voltage / (VCC - voltage))
    temp_k = 1.0 / ((1.0 / T0) + (1.0 / BETA) * math.log(r_ntc / R0))
    res = temp_k - 273.15
    print(f"[MAIN] NTC temperature calculated: {res} °C for voltage: {voltage} V")
    return res


class SiteStatus:
    def __init__(self, site_id: str):
        self.site_id = site_id
        self.reset()

    def reset(self):
        self.status = {
            "aux_voltage": 0.0,
            "aux_level": 0.0,
            "main_voltage": 0.0,
            "main_level": 0.0,
            "panel_voltage": 0.0,
            "panel_power": 0.0,
            "charging_current": 0.0,
            "water_level": 0.0,
            "temperature_1": 0.0,
            "temperature_2": 0.0,
            "lte_signal": False,
            "energy_daily": 0.0
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
            if float(value) == 0.0 and field in ["principal_voltage", "auxiliary_voltage"]:
                continue
            point = point.field(field, float(value))
        point = point.time(datetime.now(UTC))
        return point

    def __repr__(self):
        return f"SiteStatus(site_id={self.site_id}, status={self.status})"


SiteStatus_instance = SiteStatus(site_id="site_001")
solar_regulator = btantarion()


def influx_write_pts(points: list, bucket: str) -> None:
    try:
        WRITE_API.write(org=ORG, bucket=bucket, record=points)
        return True
    except InfluxDBError as e:
        if e.response.status == 401 or e.response.status == 403:
            logging.info(f"[INFLUX] insufficient rights to {bucket}")
        else:
            logging.info(f"[INFLUX] influx error {e}")
    except Exception as e:
        if hasattr(e, "reason"):
            logging.info(f"[INFLUX] for bucket :{bucket} : {e.reason}")
        else:
            logging.info(f"[INFLUX] for bucket: {bucket}: {e}")
    return False


def read_all_ads1115_channels_fake():
    SiteStatus_instance.update(
        # auxiliary_voltage=if Sitrandom.uniform(11.5, 13.5),
        principal_voltage=random.uniform(11.5, 13.5),
        # panel_voltage=random.uniform(0.0, 25.0),
        water_level=random.uniform(0, 100),
        temperature_1=random.uniform(-10, 50),
        temperature_2=random.uniform(-10, 50)
    )


def read_all_ads1115_channels():
    """
    Reads all 4 channels from the ADS1115 ADC
    and returns their values as a list.
    """

    i2c = busio.I2C(board.SCL, board.SDA)
    ads = ADS.ADS1115(i2c)
    ads.gain = 1  # +/-4.096V
    channels = [
        AnalogIn(ads, 0),
        AnalogIn(ads, 1),
        AnalogIn(ads, 2),
        AnalogIn(ads, 3)
    ]
    logging.info(f"[MAIN] channel voltages: {[ch.voltage for ch in channels]}")
    aux_voltage = channels[0].voltage * 3.965  # facteur de division
    main_voltage = channels[1].voltage * 3.98  # facteur de division
    main_level = lead_soc(main_voltage, 25)
    aux_level = agm_soc(aux_voltage, 25)
    SiteStatus_instance.update(
        main_voltage=main_voltage if 10 < main_voltage < 15.0 else 0.0,
        main_level=main_level or 0.0,
        water_level=round(channels[3].voltage * 4.59, 0),
        temperature_1=ntc_temperature(channels[2].voltage),
    )
    if not SiteStatus_instance.status["aux_voltage"] and 10 < aux_voltage < 15.0:
        logging.info("[MAIN] Updating aux_voltage to %f from ADS1115", aux_voltage)
        SiteStatus_instance.update(
            aux_voltage=aux_voltage
        )
    if not SiteStatus_instance.status["aux_level"] and aux_level:
        logging.info("[MAIN] Updating aux_level to %f from ADS1115", aux_level)
        SiteStatus_instance.update(
            aux_level=aux_level
        )
    logging.info(f"[MAIN] Updated SiteStatus_instance: {SiteStatus_instance}")


async def read_loop(interval_minutes=0.5):
    """
    Continuously reads all 4 ADS1115 channels
    every 'interval_minutes' minutes and prints the results.
    """
    supervisor_bt = btantarion()
    asyncio.create_task(supervisor_bt.run())

    while True:
        btstate = supervisor_bt.get_state()
        logging.info("[MAIN] Bluetooth read %s", btstate)
        aux_volt = btstate.get("battery_voltage", 0.0)
        if aux_volt:
            logging.info("[MAIN] Calculating auxiliary SOC with voltage: %f", aux_volt)
            aux_level = agm_soc(aux_volt, btstate.get("temperature_1", 10))
            if aux_level:
                SiteStatus_instance.update(
                    aux_level=aux_level
                )
            SiteStatus_instance.update(
                aux_voltage=aux_volt,
                panel_voltage=btstate.get("panel_voltage", 0.0),
                panel_power=btstate.get("charging_power", 0.0),
                charging_current=btstate.get("charging_current", 0.0),
                energy_daily=btstate.get("energy_daily", 0.0),
            )

        logging.info("[MAIN] try Reading ADS1115 channels...")
        if ADAFRUIT_AVAILABLE:
            logging.info("[MAIN] Using real ADS1115 readings.")
            read_all_ads1115_channels()
        else:
            logging.info("[MAIN] Using fake ADS1115 readings.")
            read_all_ads1115_channels_fake()
        logging.info(SiteStatus_instance)
        connected = False
        lte_signal = False
        if not test_ping(1):
            connected, lte_signal = ready_or_connect(force=False)
        else:
            connected = True
        logging.info("[MAIN] Internet connected: %s via %s", connected, "LTE" if lte_signal else "WLAN0")
        SiteStatus_instance.update(lte_signal=lte_signal)
        POINTS.append(SiteStatus_instance.to_point())
        SiteStatus_instance.reset()

        if connected:
            if influx_write_pts(POINTS, BUCKET):
                POINTS.clear()
                logging.info(
                    "[MAIN] Points successfully written to InfluxDB through %s",
                    "LTE" if lte_signal else "WLAN0"
                )
            else:
                logging.info("[MAIN] Failed to write points to InfluxDB.")
        else:
            logging.info("[MAIN] No internet connection. Points not sent.")
        await asyncio.sleep(interval_minutes * 60)  # <-- async sleep


if __name__ == "__main__":
    # Place config and log in the parent of the parent directory of the script
    script_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.dirname(script_dir)
    grandparent_dir = os.path.dirname(parent_dir)
    cfgname = os.path.join(grandparent_dir, "supervisor.cfg")
    Config = configparser.ConfigParser()
    logname = os.path.join(grandparent_dir, "supervisor.log")
    # logging removed
    if os.path.exists(cfgname):
        Config.read(cfgname)
        TOKEN = Config.get("influx", "token")
        SERVER = Config.get("influx", "server")
        BUCKET = Config.get("influx", "bucket")
        ORG = Config.get("influx", "org")
    else:
        print(f"[Config] Config file {cfgname} not found, exiting")
        sys.exit(1)
    CLIENT = InfluxDBClient(
        url=SERVER,
        token=TOKEN,
        org=ORG
    )
    WRITE_API = CLIENT.write_api(write_options=SYNCHRONOUS)
    logging.info(f"[MAIN] Starting supervisor version 224 with InfluxDB org:{ORG}, server:{SERVER}, bucket:{BUCKET}")
    asyncio.run(read_loop())
