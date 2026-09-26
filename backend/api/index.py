"""Point d'entrée de la fonction Python Vercel (zone A du Diagramme 2).

Vercel sert les fonctions du dossier `api/` ; toutes les URL y sont réécrites
(`vercel.json`). L'application elle-même vit dans `app/main.py` : ce fichier ne fait
que l'exposer, sans aucune logique.
"""

from app.main import app

__all__ = ["app"]
