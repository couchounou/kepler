#!/bin/bash

PRIMARY_GW="192.168.1.1"
BACKUP_GW="192.168.10.1"
PRIMARY_DEV="wlan0"
BACKUP_DEV="eth0"
TEST_IP="8.8.8.8"
PING_COUNT=3
INTERVAL=60
CONFIRM_COUNT=3
STARTUP_WAIT=30
STARTUP_RETRY=5

current_gw="primary"
success_streak=0

# ── DNS de secours immédiat au démarrage ───────────────────────────────────────
# Évite la fenêtre sans DNS si wlan0 est absent au boot
echo "nameserver 8.8.8.8"  > /etc/resolv.conf
echo "nameserver 1.1.1.1" >> /etc/resolv.conf

# ── Fonctions ──────────────────────────────────────────────────────────────────

check_primary() {
    ping -c 2 -W 2 -I $PRIMARY_DEV $PRIMARY_GW &>/dev/null || return 1
    ip route replace $TEST_IP via $PRIMARY_GW dev $PRIMARY_DEV
    ping -c $PING_COUNT -W 2 -I $PRIMARY_DEV -B $TEST_IP &>/dev/null
    result=$?
    ip route del $TEST_IP 2>/dev/null
    return $result
}

set_metric() {
    local dev=$1
    local gw=$2
    local metric=$3

    if ip route show dev $dev | grep -q "^default.*proto dhcp"; then
        ip route change default via $gw dev $dev proto dhcp metric $metric
    elif ip route show dev $dev | grep -q "^default"; then
        ip route change default via $gw dev $dev metric $metric
    else
        echo "$(date) - WARNING: pas de route default sur $dev, création manuelle" | tee -a /var/log/failover.log
        ip route add default via $gw dev $dev metric $metric
    fi
}

wait_for_any_interface() {
    echo "$(date) - Démarrage : attente qu'au moins une interface soit prête..." | tee -a /var/log/failover.log
    local waited=0

    while [ $waited -lt $STARTUP_WAIT ]; do
        local primary_ok=false
        local backup_ok=false

        if ip link show $PRIMARY_DEV &>/dev/null && \
           ip addr show $PRIMARY_DEV | grep -q "inet " && \
           ping -c 1 -W 2 -I $PRIMARY_DEV $PRIMARY_GW &>/dev/null; then
            primary_ok=true
        fi

        if ip link show $BACKUP_DEV &>/dev/null && \
           ip addr show $BACKUP_DEV | grep -q "inet " && \
           ping -c 1 -W 2 -I $BACKUP_DEV $BACKUP_GW &>/dev/null; then
            backup_ok=true
        fi

        if $primary_ok; then
            echo "$(date) - Démarrage : wlan0 prête, démarrage en mode primary" | tee -a /var/log/failover.log
            current_gw="primary"
            # wlan0 dispo : on peut utiliser son DNS
            echo "nameserver 192.168.1.1" > /etc/resolv.conf
            return 0
        elif $backup_ok; then
            echo "$(date) - Démarrage : wlan0 absente, eth0 prête, bascule initiale sur backup" | tee -a /var/log/failover.log
            ip route show dev $PRIMARY_DEV | grep -q "^default" && \
                set_metric $PRIMARY_DEV $PRIMARY_GW 100
            set_metric $BACKUP_DEV $BACKUP_GW 50
            # DNS publics déjà écrits en haut du script, rien à faire
            current_gw="backup"
            return 0
        fi

        echo "$(date) - Démarrage : aucune interface prête, attente... (${waited}s/${STARTUP_WAIT}s)" | tee -a /var/log/failover.log
        sleep $STARTUP_RETRY
        waited=$((waited + STARTUP_RETRY))
    done

    echo "$(date) - WARNING: aucune interface prête après ${STARTUP_WAIT}s, démarrage quand même" | tee -a /var/log/failover.log
    return 1
}

bascule_backup() {
    if ! ping -c 2 -W 2 -I $BACKUP_DEV $BACKUP_GW &>/dev/null; then
        echo "$(date) - wlan0 KO mais eth0 injoignable aussi, on attend..." | tee -a /var/log/failover.log
        return 1
    fi

    echo "$(date) - Bascule sur eth0 (backup)" | tee -a /var/log/failover.log
    set_metric $PRIMARY_DEV $PRIMARY_GW 100
    set_metric $BACKUP_DEV  $BACKUP_GW  50

    echo "nameserver 8.8.8.8"  > /etc/resolv.conf
    echo "nameserver 1.1.1.1" >> /etc/resolv.conf

    current_gw="backup"
    success_streak=0
}

retour_primary() {
    echo "$(date) - Retour confirmé sur wlan0 (primary)" | tee -a /var/log/failover.log
    set_metric $PRIMARY_DEV $PRIMARY_GW 50
    set_metric $BACKUP_DEV  $BACKUP_GW  100

    # wlan0 confirmé fonctionnel → DNS local du routeur
    echo "nameserver 192.168.1.1" > /etc/resolv.conf

    current_gw="primary"
    success_streak=0
}

# ── Attente initiale au démarrage ──────────────────────────────────────────────
wait_for_any_interface

# ── Boucle principale ──────────────────────────────────────────────────────────
while true; do
    if check_primary; then
        success_streak=$((success_streak + 1))
        echo "$(date) - wlan0 OK (streak: $success_streak/$CONFIRM_COUNT)" | tee -a /var/log/failover.log

        if [ "$current_gw" = "backup" ] && [ "$success_streak" -ge "$CONFIRM_COUNT" ]; then
            retour_primary
        fi
    else
        echo "$(date) - wlan0 KO" | tee -a /var/log/failover.log
        success_streak=0

        if [ "$current_gw" = "primary" ]; then
            bascule_backup
        fi
    fi
    sleep $INTERVAL
done
