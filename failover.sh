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

set_metric() {
    local dev=$1
    local gw=$2
    local metric=$3

    if ip route show dev $dev | grep -q "^default.*proto dhcp"; then
        # Route DHCP existante → modifie en place, zéro doublon
        ip route change default via $gw dev $dev proto dhcp metric $metric
    elif ip route show dev $dev | grep -q "^default"; then
        # Route default sans proto dhcp → modifie quand même
        ip route change default via $gw dev $dev metric $metric
    else
        # Aucune route default → création manuelle
        echo "$(date) - WARNING: pas de route default sur $dev, création manuelle"
        ip route add default via $gw dev $dev metric $metric
    fi
}

bascule_backup() {
    # Vérifie que le backup est disponible avant de basculer
    if ! ping -c 2 -W 2 -I $BACKUP_DEV $BACKUP_GW &>/dev/null; then
        echo "$(date) - wlan0 KO mais eth0 injoignable aussi, on attend..."
        return 1
    fi

    echo "$(date) - Bascule sur eth0 (backup)"
    set_metric $PRIMARY_DEV $PRIMARY_GW 100
    set_metric $BACKUP_DEV  $BACKUP_GW  50

    # Basculer le DNS sur un serveur public joignable partout
    echo "nameserver 8.8.8.8"  > /etc/resolv.conf
    echo "nameserver 1.1.1.1" >> /etc/resolv.conf

    current_gw="backup"
    success_streak=0
}

retour_primary() {
    echo "$(date) - Retour confirmé sur wlan0 (primary)"
    set_metric $PRIMARY_DEV $PRIMARY_GW 50
    set_metric $BACKUP_DEV  $BACKUP_GW  100

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