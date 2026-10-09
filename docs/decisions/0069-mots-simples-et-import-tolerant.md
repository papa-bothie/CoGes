# 0069 — Mots simples, en-têtes d'import tolérants

- **Date** : 2026-10-08
- **Phase** : 15 (lot 2)
- **Statut** : acceptée
- **Décideur** : utilisateur (via AskUserQuestion, 2026-10-08)

## Contexte
Le lot 2 du prompt de phase 15 remplace le vocabulaire de gestionnaire (CA, CMP, marge,
trésorerie, créance, SKU, motif, échéance…) par des mots simples, « dans `labels.ts`, les
en-têtes de tableaux, les exports et les notifications ». Trois points n'étaient pas
tranchés :

- les en-têtes d'export (`sku`, `prix_vente`, `numero`…) servent aussi de format d'import,
  et des fichiers préparés par les utilisateurs les emploient déjà ;
- une partie des textes vient du serveur : libellés des métriques et des séries, titres et
  textes d'insight, notifications ;
- seules les ventes sont citées pour « N° » → « Vente n° ».

## Options envisagées
Exports :
1. **Mots simples partout, import tolérant (retenue).**
2. Mots simples pour l'export des ventes seulement, clés techniques ailleurs.
3. Ne pas toucher aux exports.

Textes du serveur :
1. **Le serveur parle aussi en mots simples (retenue).**
2. Le front traduit les textes du serveur.

Numéros : **« Retour n° » et « Dépense n° » sur le modèle de « Vente n° » (retenue)**, ou
garder « N° » hors des ventes.

## Décision
- **Colonnes d'import** : chaque `Column` porte un mot (`Référence`, `Prix de vente`,
  `Seuil d'alerte`…) et ses anciens noms (`aliases`). `Importer.canonical` ramène chaque
  en-tête reconnu, mot ou ancien nom, à la clé normalisée de sa colonne ; la comparaison
  reste sans casse, accents ni petits mots. Les modèles et les exports écrivent les mots ;
  le rapport d'erreurs nomme la colonne par son mot. L'export des ventes prend aussi des
  mots (`Vente n°`, `Payé`, `Retourné`…).
- **`Référence` devient facultative à l'import** : vide, elle est générée comme à l'écran
  (ADR 0066).
- **Serveur** : `METRIC_LABELS` (« Ventes générées », « Gagné sur les ventes »),
  `SERIES_LABELS` (« Vendu », « Gagné sur les ventes »), gabarits d'insight (« Gain en
  baisse », « Client en retard de paiement », « Part gagnée sur les ventes »),
  notifications (« Pourquoi : », « Dette à payer : date dépassée »). Les huit métriques
  gardent des noms distincts (ADR 0033). Les insights et notifications déjà enregistrés
  gardent leur titre : l'historique n'est pas réécrit.
- **Front** : lexique appliqué à `labels.ts` et `metrics.ts` ; « Gagné » devient « Perdu »
  sous zéro, montant positif (maquette 17) ; sous-titres qui expliquaient un calcul
  supprimés.

## Conséquences
- Tests : `frontend/lib/plain-words.test.ts` et `backend/tests/unit/test_plain_words.py`
  interdisent les anciens termes (liste d'exceptions commentée, vide à ce jour) ;
  `test_import_plain_headers.py` vérifie modèle, aller-retour dans une entreprise neuve,
  anciens en-têtes et nom de colonne dans le rapport.
- `docs/guides/import-formats.md` donne le mot et l'ancien nom de chaque colonne.
- Les ADR suivants du prompt de phase 15 décalent encore d'un rang : la refonte visuelle
  devient 0070.
