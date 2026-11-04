# Prompt 35 — Groupe 2 : documents (logo, ticket et facture, PDF à partager, exports PDF)

Branche de départ : `main` à jour, après le déploiement du groupe 1 (prompt 34). Règle du propriétaire : ce groupe est testé, fusionné et déployé avant le groupe 3. Une PR par bloc, dans l'ordre L, F, T, X, A.

Ce qui existe déjà (lu dans le code le 4 novembre 2026) :
- Réglages de la boutique : nom, **adresse**, téléphone, NINEA, RC, pied de reçu, format du reçu (`ticket` 80 mm ou `a4`) — `companies/schemas.py`.
- Reçu : `frontend/app/(app)/sales/[id]/receipt/receipt-view.tsx`, deux mises en page (ticket 80 mm, facture A4), impression par le navigateur ; l'adresse s'affiche déjà quand elle est remplie ; la facture montre les **initiales** de la boutique à la place d'un logo (`logoInitials`).
- Exports : référentiels en CSV/Excel (`importexport/service.py`, openpyxl), export des ventes en tâche de fond (file d'exports, fichiers à télécharger, Réglages → Fichiers). Aucune bibliothèque PDF, aucun stockage d'image.

Décisions du propriétaire : logo de l'entreprise sur le ticket et la facture ; « qualité » et « style » de la facture en un seul chantier, en gardant le contenu actuel et l'adresse ; ticket téléchargeable ou partageable en PDF (WhatsApp) ; exports PDF prêts à remettre à un comptable, dans cet ordre : ventes sur une période, journal de caisse, état du stock, dépenses par type, dettes.

```
Groupe 2 — documents (depuis main à jour). Règles habituelles : ADR au prochain numéro
libre, tests d'abord (rouge puis vert), aucun service payant, ne jamais ouvrir ni commiter
.env, deploy/.env.preprod ni backend/.vercel/. Résumé en français à la fin, questions ouvertes
par AskUserQuestion. Migrations : ajouts seuls, rétrocompatibles (ADR 0083). Une PR par bloc :
L (logo), F (facture et ticket refaits), T (PDF à partager), X (exports PDF), A (fin).

Q0. Décision à me faire valider AVANT de coder (AskUserQuestion, avec ta recommandation) :
le moteur PDF. Recommandation attendue : génération CÔTÉ SERVEUR, une seule bibliothèque
(libre, version figée, sans service payant ; par exemple ReportLab, ou WeasyPrint si ses
dépendances système passent dans l'image), polices embarquées (accents, « F CFA »), pour
que le ticket, la facture et les exports aient le même rendu partout, y compris sur un
téléphone qui n'imprime pas. L'impression par le navigateur reste disponible.

L. Logo de l'entreprise
- Réglages → Boutique : « Ajouter le logo » (gérant, droit company:update), aperçu,
  « Changer », « Retirer ».
- Fichiers acceptés : PNG, JPEG, WebP, 2 Mo au plus ; SVG REFUSÉ (risque de script). Le
  serveur vérifie le vrai type (pas l'extension), RÉ-ENCODE l'image (Pillow, version figée),
  retire les métadonnées (position GPS d'une photo), la réduit à 512 px de côté au plus, et
  garde un PNG de quelques dizaines de Ko. Refus clairs (« Image trop lourde », « Format non
  pris en charge »).
- Stockage : dans PostgreSQL (table dédiée sous RLS, une ligne par entreprise, ou colonne de
  companies — justifie), pour qu'il soit sauvegardé par la sauvegarde chiffrée existante sans
  rien ajouter. Pas de disque du VPS, pas de service externe. Tests de fuite inter-tenant.
- Lecture : GET authentifié (le front l'affiche par un blob, les jetons ne voyagent pas dans
  une URL) ; en-têtes no-store, nosniff ; le service worker ne le garde pas (ADR 0102).
- Audit critique de l'ajout, du changement et du retrait. Isolation par entreprise.

F. Ticket et facture refaits (un seul chantier « qualité + style »)
- Contenu : celui d'aujourd'hui, plus le logo, et l'adresse mise en évidence en tête (si
  l'adresse n'est pas remplie, Réglages le signale au gérant : « Ajoutez l'adresse de la
  boutique pour vos factures »).
- Facture A4 : en-tête (logo à gauche, nom, adresse, téléphone, NINEA, RC), bloc client,
  « Facture n° », date et heure, vendeur ; tableau des lignes (désignation avec la
  description de l'article en dessous si elle existe, quantité et unité, prix unitaire —
  « prix changé » n'est PAS indiqué au client —, remise s'il y en a, montant), totaux (sous-
  total, remises, taxe si activée, total, payé, reste dû, moyens de paiement), retours liés
  s'il y en a, pied de reçu, pagination « page 1/2 » si la facture est longue. Mise en page
  sobre, lisible imprimée en noir et blanc, alignement des montants, aucune couleur en dur
  (jetons, ou palette d'impression documentée).
- Ticket 80 mm : logo en petit et en noir et blanc en tête, nom, adresse, téléphone ; lignes
  courtes ; mêmes totaux ; pied de reçu.
- Le reçu à l'écran, l'impression et le PDF (bloc T) partagent la même source de données ;
  le rendu PDF suit la même mise en page que l'impression.
- Bon de retour (return-slip-view) : même en-tête (logo, adresse).
- Tests : rendu avec et sans logo, avec et sans adresse, facture longue (pagination),
  montants alignés, captures avant / après dans make maquette-check (écarts notés).

T. Ticket et facture en PDF, à télécharger ou partager
- Sur le reçu d'une vente (et le bon de retour) : « Télécharger le PDF » et « Partager »
  (WhatsApp, e-mail, etc.).
- Partager : API Web Share avec fichier (navigator.share({ files })) quand le téléphone la
  prend en charge, sinon téléchargement du PDF et lien WhatsApp existant avec le texte.
- PDF généré par le serveur (Q0), nommé « Facture-0042-Boutique.pdf », droit sales:read
  (bon de retour : sale_returns:read), en-têtes no-store, jamais gardé par le service worker
  ni dans une URL publique. Génération rapide (< 1 s pour un ticket) : mesure-la.
- Accès support en lecture seule (ADR 0092) : téléchargement permis, aucune écriture.
- Tests : PDF valide (lu par un parseur en test), contient le nom, le total, le logo ;
  autre entreprise refusée ; e2e du bouton (téléchargement, et partage simulé).

X. Exports PDF prêts pour le comptable
Pour chacun : en-tête (logo, nom, adresse, NINEA, période, date d'édition, « édité par »),
totaux, pagination, pied « Document généré par CoGes ». Période choisie à l'écran (jour,
semaine, mois, personnalisée, 366 jours au plus). Génération en tâche de fond par la file
d'exports existante dès que le document peut être long (ventes, caisse), avec le fichier dans
Réglages → Fichiers comme les exports actuels ; un document court peut être immédiat.
1. Ventes sur une période : liste (n°, date, client, total, payé, reste, moyen), totaux par
   jour et par moyen de paiement, remises, retours, total net.
2. Journal de caisse : entrées et sorties d'argent (compensations `offset` EXCLUES, comme
   partout), solde de début et de fin, par moyen.
3. État du stock à une date : article, rayon, quantité et unité, coût moyen, valeur ; valeur
   totale ; date de l'état (à aujourd'hui dans ce lot, sauf si l'historique permet une date
   passée simplement : dis-le).
4. Dépenses par type sur une période : total par type, détail, total général.
5. Dettes clients et fournisseurs : qui doit quoi, depuis quand (ancienneté 0-30, 31-60,
   61-90, plus de 90 jours), total.
- Droits : chaque export exige le droit de lecture de son écran ET un droit d'export
  existant (sales:export, analytics:export, audit:export, importexport:export — propose le
  bon pour chacun, sans nouveau droit, et ajoute-les au registre des écrans, ADR 0099) ;
  pose-moi la question si l'un te paraît ambigu.
- Les chiffres d'un PDF sont EXACTEMENT ceux de l'écran correspondant pour la même période
  (test qui compare les deux sources), et ceux de l'export Excel existant quand il existe.
- Bouton « Exporter en PDF » à côté de l'export Excel existant, et sur les écrans Argent,
  Caisse, Stock, Dépenses, Dettes.
- Tests : chaque PDF (valide, totaux justes sur des données de test connues, période vide,
  autre entreprise refusée, droit manquant refusé), e2e d'un export de bout en bout.

A. Fin du groupe
Suite backend complète, ruff, mypy, make front-check, make maquette-check, e2e des écrans
touchés, tests de fuite inter-tenant, CI verte. Image Docker : la bibliothèque PDF et
Pillow s'installent et passent les analyses de sécurité de la CI (pip-audit) ; poids de
l'image indiqué. ADR, CLAUDE.md §8, README. Liste dans le résumé ce que le propriétaire
vérifie après déploiement.
```

## Ce que le propriétaire fait lui-même

1. Répondre à la question du moteur PDF, et à celles sur les droits des exports si l'agent en pose.
2. Après le déploiement :
   - Réglages → Boutique : ajouter le logo, vérifier l'adresse ;
   - faire une vente, ouvrir le reçu : logo, adresse, mise en page ; « Partager » vers WhatsApp sur un téléphone ;
   - exporter en PDF les ventes du mois et le journal de caisse, et comparer les totaux à l'écran.
3. Seulement ensuite, passer au groupe 3 (vente en gros).
