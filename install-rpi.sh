#!/bin/bash

# priotité wifi 
sudo nmcli connection modify "wlan0" ipv4.route-metric 100
sudo nmcli connection modify "eth0" ipv4.route-metric 200


cd ~
mkdir -p kepler
sudo apt-get install -y git
git clone https://github.com/couchounou/kepler.git
sudo git config --global --add safe.directory ~/kepler
cd ~/kepler
sudo apt-get install -y python3-pip
python3 -m venv ./venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
deactivate

# utilisateur cible
REAL_USER=$(logname 2>/dev/null || echo "$SUDO_USER")

TEMPLATE=~/kepler/services/kepler.service
TARGET=/etc/systemd/system/kepler.service
sudo sed "s|\$USER|${REAL_USER}|g" "$TEMPLATE" | sudo tee "$TARGET" > /dev/null

TEMPLATE=~/kepler/services/git-update.service
TARGET=/etc/systemd/system/git-update.service
sudo sed "s|\$USER|${REAL_USER}|g" "$TEMPLATE" | sudo tee "$TARGET" > /dev/null

TEMPLATE=~/kepler/git-update.sh
TARGET=/home/$REAL_USER/git-update.sh
sudo sed "s|\$USER|${REAL_USER}|g" "$TEMPLATE" | sudo tee "$TARGET" > /dev/null

sudo chmod +x ~/git-update.sh
sudo systemctl daemon-reload
sudo systemctl enable gitupdate.service
sudo systemctl start gitupdate.service
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