# Publier une nouvelle version des textes légaux

Conditions générales d'utilisation et de vente et politique de confidentialité (ADR 0117).
Les textes vivent dans `frontend/content/legal/` ; le serveur garde leur version dans
`backend/app/core/legal.py` (`LEGAL_VERSION`). Une nouvelle version redemande
l'acceptation à **tous les comptes** dès leur requête suivante.

## Étapes

1. **Rédiger** le texte dans son document, puis l'exporter en Markdown.
2. **Remplacer** le fichier concerné, sans retoucher le Markdown à la main :
   - `frontend/content/legal/conditions.md` (CGU et CGV, un seul texte) ;
   - `frontend/content/legal/confidentialite.md`.
3. **Mettre la date d'entrée en vigueur** en toute première ligne :
   `<!-- version: AAAA-MM-JJ -->`. Si seul un des deux textes change, seule sa ligne
   change.
4. **Changer `LEGAL_VERSION`** dans `backend/app/core/legal.py` : la **plus récente** des
   deux dates. `tests/unit/test_legal_version.py` échoue tant que ce n'est pas fait.
   Le même test refuse un crochet oublié (« [à définir] », « [à confirmer] », « [date …] »).
5. **Vérifier en local** :
   - `make test` (ou au moins `uv run --directory backend pytest tests/unit/test_legal_version.py`) ;
   - `make front-check` : le build échoue si le texte contient un élément Markdown non pris
     en charge (citation, titre de niveau 4…). Il faut alors simplifier le texte, ou ajouter
     l'élément au rendu (`frontend/components/legal/legal-markdown.tsx`) ;
   - `make front-dev`, puis ouvrir `/conditions` et `/confidentialite` (date en tête,
     tableaux lisibles à 360 px).
6. **Ouvrir une PR**, la faire relire (le texte juridique doit être celui du document),
   fusionner.
7. **Déployer** : Actions → « Déployer » → production, puis sur le VPS
   `sudo -u deploy /opt/coges/deploy.sh production vX.Y.Z`. Aucune migration n'est
   nécessaire.

## Ce qui se passe ensuite

- Les pages publiques montrent la nouvelle version tout de suite : elles sont rendues au
  build et le service worker ne garde aucune page.
- À sa requête suivante, chaque compte reçoit 409 `legal_acceptance_required` : le front
  ouvre « Avant de continuer ». Une fois la case cochée, la version et l'heure sont
  enregistrées sur `users` (`legal_accepted_version`, `legal_accepted_at`) avec une ligne
  d'audit critique.
- Les conditions (article 15) promettent un préavis de 30 jours : annoncer la nouvelle
  version dans l'application **avant** de la publier ainsi.

## Vérifier qui a accepté

En lecture, sous la RLS d'une entreprise (ou par le journal d'activité, « a accepté les
conditions… ») :

```sql
SELECT full_name, legal_accepted_version, legal_accepted_at
FROM users WHERE deleted_at IS NULL ORDER BY legal_accepted_at NULLS FIRST;
```
