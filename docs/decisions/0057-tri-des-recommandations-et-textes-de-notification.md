# 0057 — Recommandations triées par sévérité ; textes de notification à la française

- **Date** : 2026-10-01
- **Phase** : 14 (retouches après clôture)
- **Statut** : acceptée
- **Décideur** : utilisateur (via AskUserQuestion)

## Contexte

1. `GET /api/v1/insights` triait par date seule (`generated_at DESC`) : une information récente
   passait devant une recommandation critique plus ancienne, sur l'API comme à l'écran CoGes
   Intelligence, qui affiche l'ordre de l'API.
2. Le worker de notifications composait ses textes avec des valeurs brutes (« Une dette de
   21830.00 est échue depuis le 2026-09-17 », « Il reste 1.000 de… »), contraires aux formats
   d'affichage de `CLAUDE.md` § 5 (reporté par l'ADR 0056).

## Décision

1. **Tri** : sévérité (critique, attention, information) par un `CASE` explicite — pas l'ordre de
   déclaration de l'ENUM `insight_severity` —, puis `generated_at DESC`, puis `id DESC` pour une
   pagination stable. Filtres, comptage et résumé inchangés ; le front n'a rien à trier.
2. **Formateurs partagés** dans `app/core/display.py` (`fcfa`, `dmy`, `number`, `qty`), mêmes
   sorties que le front : milliers en espace fine insécable, espace insécable avant « FCFA »,
   montants sans décimales, dates `jj/mm/aaaa`, quantités à trois décimales au plus sans zéros
   inutiles. Les gabarits d'Intelligence les importent (leur `qty` à une décimale reste local).
3. **FCFA fixe** : V1 est mono-devise (XOF) ; aucune lecture de la devise dans le worker.
4. Seul le **texte** change : les champs `data` des notifications gardent leurs valeurs machine
   (décimal sérialisé, date ISO) pour les liens et traitements.

## Conséquences

- Tests : `tests/unit/test_display.py`, `test_alert_texts_read_like_the_screen`
  (notifications), `test_insights_are_listed_by_severity_then_newest_first` (vérifié en échec
  sans le tri).
- Les textes d'Intelligence prennent l'espace insécable du front avant « FCFA » (une assertion
  de `test_intelligence_templates.py` suit).
- Les notifications déjà en base ne sont pas réécrites ; le worker déployé (image Docker de la
  zone B) doit être reconstruit pour produire les nouveaux textes.
- Le spec `captures-pilotage` filtre sur « Écoulement lent » avant d'ouvrir le panneau : avec le
  tri, une information n'est plus forcément en première page.
