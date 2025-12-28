#!/bin/bash

cd /home/$USER/kepler || exit 1
/usr/bin/git pull
#echo "Updating git-update.sh script and restarting service..."
# sudo systemctl restart kepler
# sudo cp /home/kepler/kepler/services/git-update.sh /home/kepler/
# sudo chmod +x /home/kepler/git-update.sh