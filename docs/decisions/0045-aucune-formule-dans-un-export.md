# 0045 — Aucune formule dans un export (CSV et .xlsx)

- **Date** : 2026-09-27
- **Phase** : 10 (correctif de sécurité, avant la phase 11)
- **Statut** : acceptée
- **Décideur** : utilisateur (via AskUserQuestion)

## Contexte
Les exports de l'ADR 0041 (référentiels et ventes) recopiaient les textes tels quels. Un nom
de client `=HYPERLINK("http://evil.example","x")`, saisi par n'importe quel compte ou par
import, ressortait comme **formule active** dans le .xlsx (openpyxl fait d'une chaîne qui
commence par `=` une cellule de type `f`) et brut dans le CSV : c'est une injection de
formules (CSV/Excel injection) chez le gérant qui ouvre le fichier.

## Options envisagées
1. **CSV : apostrophe ; .xlsx : type texte sans apostrophe (retenu)** : en .xlsx, toute
   chaîne est une cellule de type `s`, et celles qui commencent par un caractère de
   formule reçoivent le style *quotePrefix* (Excel les garde en texte même après une
   modification). La valeur affichée est identique.
2. Apostrophe dans les deux formats : uniforme, mais l'apostrophe devient un caractère
   visible dans la cellule Excel.

## Décision
- Un texte qui commence par `=`, `+`, `-`, `@`, une tabulation ou un retour chariot est
  préfixé de `'` **dans le CSV**. Dans le **.xlsx**, **tout** texte est écrit en type
  chaîne, avec *quotePrefix* pour ces mêmes débuts. Aucune cellule exportée n'est jamais
  une formule.
- Les vrais nombres (montants `Decimal`, quantités, entiers) restent des nombres : un
  montant négatif n'est pas préfixé.
- À l'import, un `'` suivi d'un de ces caractères est retiré : l'aller-retour export →
  import rend la valeur d'origine (`docs/guides/import-formats.md`).
- La règle vit dans l'écrivain commun `app/modules/importexport/tabular.py` : tout export
  présent ou futur passe par `write_csv` / `write_xlsx`.

## Conséquences
- En CSV ouvert dans un tableur, un téléphone `+221 …` apparaît `'+221 …` : prix accepté
  de la neutralisation.
- En .xlsx, un `\r` est relu `\n` par tout parseur XML (propre au format, pas à CoGes).
- Tests : `tests/unit/test_tabular_formula_injection.py` et
  `tests/integration/test_export_formula_injection.py` (client, produit, vente, CSV et
  .xlsx, aller-retour entre deux entreprises neuves).
- Au passage : `tests/__init__.py` force les trois `COGES_RATE_LIMIT_*_PER_MINUTE` à 0
  (une valeur exportée dans le shell faisait échouer la suite en 429), et les tests T40
  vident l'outbox avant de s'exécuter (un arriéré de plus de 500 événements, laissé par les
  autres suites, repoussait l'événement du test hors du lot).
