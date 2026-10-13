#!/bin/bash

# ── Variables de configuration ────────────────────────────────────────────────
PRIMARY_GW="192.168.1.1"
BACKUP_GW="192.168.10.1"
PRIMARY_DEV="wlan0"
BACKUP_DEV="eth0"
MODEM_TTY="/dev/ttyACM0"
TEST_IP="8.8.8.8"
USER_NAME="eric"

PING_COUNT=3
INTERVAL=10
CONFIRM_COUNT=3
LOG_FILE="/var/log/failover.log"

current_gw="primary"
success_streak=0

# ── Force la relance de rpi-connect dans le contexte utilisateur ───────────────
restart_rpiconnect() {
    USER_ID=$(id -u "$USER_NAME")
    export DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/${USER_ID}/bus"
    
    sudo -u "$USER_NAME" DBUS_SESSION_BUS_ADDRESS="$DBUS_SESSION_BUS_ADDRESS" \
        systemctl --user restart rpi-connect.service 2>/dev/null || pkill -f rpi-connectd || true
}

# ── Reset physique / AT du modem Air780E si freeze ─────────────────────────────
reset_modem_hardware() {
    echo "$(date) - [RECOVERY] Modem non fonctionnel. Envoi de AT+RESET..." | tee -a "$LOG_FILE"
    python3 -c '
import serial, time
try:
    ser = serial.Serial("'$MODEM_TTY'", 115200, timeout=1)
    ser.write(b"AT+RESET\r\n")
    time.sleep(1)
    ser.close()
    print("Reset AT envoyé au modem.")
except Exception as e:
    print("Erreur envoi AT+RESET:", e)
' | tee -a "$LOG_FILE"
    sleep 10
}

# ── Configuration eth0 et modem ───────────────────────────────────────────────
init_backup_interface() {
    echo "$(date) - Initialisation eth0 et modem Air780E (SFR)..." | tee -a "$LOG_FILE"

    # 1. Montage interface, IP fixe locale et MTU CGNAT SFR
    ip link set dev $BACKUP_DEV up
    ip link set dev $BACKUP_DEV mtu 1420 2>/dev/null
    ip addr add 192.168.10.2/24 dev $BACKUP_DEV 2>/dev/null
    
    ip route del default dev $BACKUP_DEV 2>/dev/null
    ip route add default via $BACKUP_GW dev $BACKUP_DEV metric 200 2>/dev/null

    # 2. Activation du contexte 4G SFR sur le modem
    python3 -c '
import serial, time
try:
    ser = serial.Serial("'$MODEM_TTY'", 115200, timeout=1)
    ser.write(b"AT+CGDCONT=1,\"IP\",\"sl2sfr\"\r\n")
    time.sleep(0.5)
    ser.write(b"AT+CGACT=1,1\r\n")
    time.sleep(1)
    ser.close()
    print("Modem Air780E initialisé (PDP active).")
except Exception as e:
    print("Erreur initialisation modem AT:", e)
' | tee -a "$LOG_FILE"
}

# ── Fonctions de contrôle ──────────────────────────────────────────────────────

check_primary() {
    ip route del $TEST_IP 2>/dev/null
    ping -c 2 -W 2 -I $PRIMARY_DEV $PRIMARY_GW &>/dev/null || return 1

    ip route replace $TEST_IP via $PRIMARY_GW dev $PRIMARY_DEV 2>/dev/null
    ping -c $PING_COUNT -W 2 -I $PRIMARY_DEV -B $TEST_IP &>/dev/null
    result=$?
    ip route del $TEST_IP 2>/dev/null
    return $result
}

bascule_backup() {
    echo "$(date) - Bascule sur eth0 (backup 4G SFR)" | tee -a "$LOG_FILE"

    ip route del $TEST_IP 2>/dev/null
    init_backup_interface

    # Application des métriques de bascule
    ip route replace default via $BACKUP_GW dev $BACKUP_DEV metric 50 2>/dev/null
    ip route replace default via $PRIMARY_GW dev $PRIMARY_DEV metric 200 2>/dev/null

    # DNS publics
    echo "nameserver 8.8.8.8"  > /etc/resolv.conf
    echo "nameserver 1.1.1.1" >> /etc/resolv.conf

    # Vérification que le ping passe sur eth0
    sleep 3
    if ! ping -c 2 -W 2 -I $BACKUP_DEV 8.8.8.8 &>/dev/null; then
        echo "$(date) - [ATTENTION] eth0 ne repond pas. Tentative de Reset Modem..." | tee -a "$LOG_FILE"
        reset_modem_hardware
        init_backup_interface
        ip route replace default via $BACKUP_GW dev $BACKUP_DEV metric 50 2>/dev/null
    fi

    echo "$(date) - Reconnexion de Raspberry Pi Connect sur la 4G..." | tee -a "$LOG_FILE"
    restart_rpiconnect

    current_gw="backup"
    success_streak=0
}

retour_primary() {
    echo "$(date) - Retour confirmé sur wlan0 (primary)" | tee -a "$LOG_FILE"

    # Restauration des métriques d origine
    ip route replace default via $PRIMARY_GW dev $PRIMARY_DEV metric 50 2>/dev/null
    ip route replace default via $BACKUP_GW dev $BACKUP_DEV metric 200 2>/dev/null

    # DNS Box Wi-Fi
    echo "nameserver $PRIMARY_GW" > /etc/resolv.conf

    echo "$(date) - Reconnexion de Raspberry Pi Connect sur wlan0..." | tee -a "$LOG_FILE"
    restart_rpiconnect

    current_gw="primary"
    success_streak=0
}

# ── Démarrage du service ───────────────────────────────────────────────────────
init_backup_interface

# ── Boucle principale ──────────────────────────────────────────────────────────
while true; do
    if check_primary; then
        success_streak=$((success_streak + 1))

        if [ "$current_gw" = "backup" ] && [ "$success_streak" -ge "$CONFIRM_COUNT" ]; then
            retour_primary
        fi
    else
        echo "$(date) - wlan0 KO" | tee -a "$LOG_FILE"
        success_streak=0

        if [ "$current_gw" = "primary" ]; then
            bascule_backup
        else
            # Si on est déjà sur backup mais que le ping eth0 échoue, on relance le modem
            if ! ping -c 2 -W 2 -I $BACKUP_DEV 8.8.8.8 &>/dev/null; then
                echo "$(date) - eth0 a perdu la connexion 4G. Re-initialisation..." | tee -a "$LOG_FILE"
                bascule_backup
            fi
        fi
    fi
    sleep $INTERVAL
done