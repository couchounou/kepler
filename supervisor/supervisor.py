import time
from datetime import datetime, UTC
import random
import configparser
import os

import time
from datetime import datetime, UTC
import random
import configparser
import os

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



class SiteStatus:
    def __init__(self, site_id: str):
        self.site_id = site_id
        self.reset()

    def reset(self):
        self.status = {
            "chassis_voltage": 0.0,
            "house_voltage": 0.0,
            "panel_voltage": 0.0,
            "panel_power": 0.0,
            "water_level": 0.0,
            "temperature_1": 0.0,
            "temperature_2": 0.0,
            "lte_signal": 0
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
        point = point.time(datetime.now(UTC))
        return point

    def __repr__(self):
        return f"SiteStatus(site_id={self.site_id}, status={self.status})"


SiteStatus_instance = SiteStatus(site_id="site_001")


def influx_write_pts(points: list, bucket: str) -> None:
    try:
        WRITE_API.write(org=ORG, bucket=bucket, record=points)
        return True
    except InfluxDBError as e:
        if e.response.status == 401 or e.response.status == 403:
            print(f"[influx] insufficient rights to {bucket}")
        else:
            print(f"[influx] influx error {e}")
    except Exception as e:
        if hasattr(e, "reason"):
            print(f"[influx] for bucket :{bucket} : {e.reason}")
        else:
            print(f"[influx] for bucket: {bucket}: {e}")
    return False


def read_all_ads1115_channels_fake():
    SiteStatus_instance.update(
        chassis_voltage=random.uniform(0, 15),
        house_voltage=random.uniform(0, 15),
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
    print(f"channel voltages: {[ch.voltage for ch in channels]}")
    SiteStatus_instance.update(
        =channels[0].voltage * 3.965,
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
        print("try Reading ADS1115 channels...")
        if ADAFRUIT_AVAILABLE:
            read_all_ads1115_channels()
        else:
            print("Using fake ADS1115 readings.")
            read_all_ads1115_channels_fake()
        print(SiteStatus_instance)
        POINTS.append(SiteStatus_instance.to_point())
        SiteStatus_instance.reset()

        connected = False
        if not test_ping(1):
            connected, _ = ready_or_connect(force=False)
        else:
            connected = True

        if connected:
            if influx_write_pts(POINTS, BUCKET):
                POINTS.clear()
                print("Points successfully written to InfluxDB.")
            else:
                print("Failed to write points to InfluxDB.")
        else:
            print("No internet connection. Points not sent.")
        time.sleep(interval_minutes * 60)


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
        print(f"Config file {cfgname} not found, exiting")
        sys.exit(1)
    CLIENT = InfluxDBClient(
        url=SERVER,
        token=TOKEN,
        org=ORG
    )
    WRITE_API = CLIENT.write_api(write_options=SYNCHRONOUS)
    print("Starting supervisor versin 224 with InfluxDB org:%s, server:%s, bucket:%s" % (ORG, SERVER, BUCKET))
    read_loop()
