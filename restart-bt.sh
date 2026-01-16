#!/bin/bash

sudo systemctl stop bluetooth
sudo rmmod hci_uart
sleep 2
sudo modprobe hci_uart
sudo systemctl start bluetooth
