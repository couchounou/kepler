#!/bin/bash

# priotité wifi 





sudo nmcli connection add \
  type wifi \
  ifname wlan0 \
  con-name iphoneA1 \
  ssid "iphoneA1"

sudo nmcli connection modify iphoneA1 \
  wifi-sec.key-mgmt wpa-psk \
  wifi-sec.psk "mot2passe2m"

sudo nmcli connection modify "netplan-wlan0-SABLONS_MILIEU" ipv4.route-metric 50
sudo nmcli connection modify "iphoneA1" ipv4.route-metric 50

sudo rfkill unblock bluetooth

cd ~
mkdir -p kepler
sudo apt-get install -y git
git clone https://github.com/couchounou/kepler.git
sudo git config --global --add safe.directory ~/kepler
cd ~/kepler
/usr/bin/git pull
sudo apt-get install -y python3-pip
python3 -m venv ./venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
deactivate

# utilisateur cible
REAL_USER=$(logname 2>/dev/null || echo "$SUDO_USER")
echo "Configuring services for user: $REAL_USER"

TEMPLATE=~/kepler/services/kepler.service
TARGET=/etc/systemd/system/kepler.service
sudo sed "s|\$USER|${REAL_USER}|g" "$TEMPLATE" | sudo tee "$TARGET" > /dev/null

TEMPLATE=~/kepler/services/git-update.service
TARGET=/etc/systemd/system/git-update.service
sudo sed "s|\$USER|${REAL_USER}|g" "$TEMPLATE" | sudo tee "$TARGET" > /dev/null

sudo chmod +x ~/kepler/git-update.sh
TEMPLATE=~/kepler/git-update.sh
TARGET=/home/$REAL_USER/git-update.sh
sudo sed "s|\$USER|${REAL_USER}|g" "$TEMPLATE" | sudo tee "$TARGET" > /dev/null


sudo systemctl daemon-reload
sudo systemctl enable git-update.service
sudo systemctl start git-update.service
sudo systemctl enable kepler.service
sudo systemctl start kepler.service
echo "Installation complete."

sudo apt clean
sudo apt autoclean
sudo apt autoremove -y
sudo rm -rf /tmp/* /var/tmp/*
sudo rm -rf /var/cache/apt/archives/*
sudo journalctl --rotate
sudo journalctl --vacuum-time=1d