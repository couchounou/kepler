#!/bin/bash

PRIMARY_GW="192.168.1.1"
BACKUP_GW="192.168.10.1"
PRIMARY_DEV="wlan0"
BACKUP_DEV="eth0"
TEST_IP="8.8.8.8"
PING_COUNT=3
INTERVAL=60
CONFIRM_COUNT=3

current_gw="primary"
success_streak=0

check_primary() {
    # 1. Gateway locale joignable ?
    ping -c 2 -W 2 -I $PRIMARY_DEV $PRIMARY_GW &>/dev/null || return 1
    # 2. Route hôte temporaire pour forcer le chemin via wlan0
    ip route replace $TEST_IP via $PRIMARY_GW dev $PRIMARY_DEV
    ping -c $PING_COUNT -W 2 -I $PRIMARY_DEV -B $TEST_IP &>/dev/null
    result=$?
    ip route del $TEST_IP 2>/dev/null
    return $result
}

bascule_backup() {
    echo "$(date) - Bascule sur eth0 (backup)"
    # Dégrader wlan0 plutôt que supprimer
    ip route replace default via $PRIMARY_GW dev $PRIMARY_DEV metric 100
    ip route replace default via $BACKUP_GW dev $BACKUP_DEV metric 50

    # Basculer le DNS sur un serveur public joignable partout
    echo "nameserver 8.8.8.8" > /etc/resolv.conf
    echo "nameserver 1.1.1.1" >> /etc/resolv.conf

    current_gw="backup"
    success_streak=0
}

retour_primary() {
    echo "$(date) - Retour confirmé sur wlan0 (primary)"
    # Restaurer la métrique d'origine
    ip route replace default via $PRIMARY_GW dev $PRIMARY_DEV metric 50
    ip route replace default via $BACKUP_GW dev $BACKUP_DEV metric 100

    # Restaurer le DNS d'origine
    echo "nameserver 192.168.1.1" > /etc/resolv.conf

    current_gw="primary"
    success_streak=0
}

while true; do
    if check_primary; then
        success_streak=$((success_streak + 1))
        echo "$(date) - wlan0 OK (streak: $success_streak/$CONFIRM_COUNT)"

        if [ "$current_gw" = "backup" ] && [ "$success_streak" -ge "$CONFIRM_COUNT" ]; then
            retour_primary
        fi
    else
        echo "$(date) - wlan0 KO"
        success_streak=0

        if [ "$current_gw" = "primary" ]; then
            bascule_backup
        fi
    fi
    sleep $INTERVAL
done
