# Structure de projet Python

Voici un template de structure pour un projet Python classique :

```
mon_projet/
│
├── mon_projet/           # Code source principal du projet (package Python)
│   ├── __init__.py
│   └── ...
│
├── tests/                # Tests unitaires et d'intégration
│   └── test_exemple.py
│
├── docs/                 # Documentation du projet
│   └── index.md
│
├── .gitignore            # Fichiers à ignorer par git
├── requirements.txt      # Dépendances du projet
├── README.md             # Présentation du projet
├── setup.py              # Script d'installation (optionnel)
└── pyproject.toml        # Configuration du projet (recommandé)
```

- Remplace `mon_projet` par le nom de ton projet.
- Ajoute ou retire des dossiers selon tes besoins (ex : `notebooks/`, `scripts/`, etc).
- Utilise `pyproject.toml` pour la configuration moderne (outils, dépendances, etc).
- Place tes modules Python dans le dossier du même nom que ton projet.

N'hésite pas à demander si tu veux générer cette structure automatiquement ou l'adapter à un cas particulier !