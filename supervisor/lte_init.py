import serial
import time
import subprocess
import socket

MODEM_PORT = "/dev/ttyACM0"
BAUDRATE = 115200
APN = "sl2fr"
PING_TARGET = "8.8.8.8"
MAX_WAIT_NETWORK = 120


def send_at(ser, command, delay=0.5):
    """Envoyer une commande AT et retourner la réponse"""
    ser.write((command + "\r").encode())
    time.sleep(delay)
    resp = ser.read_all().decode(errors="ignore")
    print(f">{resp}")
    return resp


def wait_network_registration(ser, timeout=MAX_WAIT_NETWORK):
    """Attendre que le modem soit enregistré sur le réseau LTE"""
    print("...try registering...")
    for _ in range(timeout):
        resp = send_at(ser, "AT+CREG?")
        if "+CREG: 0,1" in resp or "+CREG: 0,5" in resp:
            print("✅ Modem registered on network")
            return True
        time.sleep(1)
    print("❌ Failed: modem not registered")
    return False


def is_reg(ser):
    resp = send_at(ser, "AT+CFUN?")
    if "+CFUN: 1" not in resp:
        print("❌ Modem not initialized")
        return False
    resp = send_at(ser, "AT+CREG?")
    if "+CREG: 0,1" in resp or "+CREG: 0,5" in resp:
        print("✅ Modem registered")
        return True
    if "+CREG: 0,2" in resp:
        print("✅ Modem still waiting for registration")
        time.sleep(3)
        return True
    return False


def test_ping(num: int = 2, target: str = "8.8.8.8", timeout: int = 2) -> bool:
    print(f"  Test ping to {target}...")
    result = subprocess.run(
        ["ping", "-I", "eth0", "-w", str(timeout * 1000), "-c", str(num), target],
        capture_output=True,
        text=True,
        check=False
    )

    if result.returncode == 0:
        print("  LTE Internet OK")
        return True
    else:
        print(f"  LTE Internet KO: {result.stderr}".strip())
        return False


def wlan0_has_internet(timeout=1) -> bool:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.setsockopt(socket.SOL_SOCKET, 25, b"wlan0\0")
        sock.connect(("8.8.8.8", 53))
        sock.close()
        return True
    except OSError:
        return False


def ready_or_connect(force=False) -> tuple[bool, bool]:
    if wlan0_has_internet():
        print("  WLAN0 already connected to internet.")
        return True, False

    if not force and test_ping("8.8.8.8"):
        print("✅ LTE already connected")
        return True, True

    print("  LTE not connected, initializing...")
    try:
        ser = serial.Serial(MODEM_PORT, BAUDRATE, timeout=1)
        time.sleep(1)
    except Exception as e:
        print(f"   Error opening serial port: {e}")
        return False, False

    send_at(ser, "AT")
    if not is_reg(ser) or force:
        print("  Init modem...")
        send_at(ser, "AT+CFUN=1", 1)
        send_at(ser, f'AT+CGDCONT=1,"IP","{APN}"', 1)

    if not wait_network_registration(ser):
        ser.close()
        return False, False

    send_at(ser, "AT+CGACT=1,1", 1)
    ser.close()

    success = test_ping(PING_TARGET)
    print("✅ LTE init. successful" if success else "❌ LTE init. failed")
    return success, success


if __name__ == "__main__":
    print(ready_or_connect(force=False))
