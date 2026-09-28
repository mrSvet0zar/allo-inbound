"""Isole la suite de tests de la configuration développeur ambiante.

`Settings` charge `.env` par défaut (cf app/config.py) — sans ceci, les
tests hériteraient de la vraie `DATABASE_URL` et `ADMIN_API_KEY` du
développeur dès que celui-ci configure son `.env` local, et certains tests
(simulation d'appel WebSocket complet) écriraient alors réellement dans sa
base de données de production. Les variables d'environnement du process
priment sur `.env` pour pydantic-settings — les fixer ici, en code de
module exécuté avant l'import de tout module applicatif par les tests,
garantit que la suite tourne toujours contre les backends en mémoire.
"""

import os

os.environ["DATABASE_URL"] = ""
os.environ["ADMIN_API_KEY"] = ""
