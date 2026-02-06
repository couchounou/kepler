#!/bin/bash
sudo nmcli connection modify "netplan-wlan0-SABLONS_MILIEU" ipv4.route-metric 50
sudo nmcli connection modify "iphoneA1" ipv4.route-metric 50
cd /home/$USER/kepler || exit 1
/usr/bin/git pull
#echo "Updating git-update.sh script and restarting service..."
# sudo systemctl restart kepler
# sudo cp /home/kepler/kepler/services/git-update.sh /home/kepler/
# sudo chmod +x /home/kepler/git-update.sh