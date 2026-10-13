# Présentation du projet

Supervision bluetooth et ADS1115 de 2 Batteries, temp  et panneaux PV via pi en LTE

## Consulter l'état en direct

Sur le Raspberry Pi, lancez `kepler-status` pour afficher le dernier état lu par le
superviseur, au format JSON. La commande est installée par `install-rpi.sh`.
L'état est actualisé à chaque cycle de supervision; avant le premier cycle, vérifiez
que `kepler.service` tourne.