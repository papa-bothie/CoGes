# Spécification fonctionnelle des écrans (issue du prompt Bolt du prototype, 21/09/2026)

> Extrait utile au frontend réel. Le prototype utilisait des données fictives et une logique
> côté client. Dans CoGes réel, **chaque chiffre vient de l'API** et chaque règle est appliquée
> par le serveur : le front affiche, guide et bloque en amont seulement pour le confort.

## Écrans

1. **Tableau de bord** : cartes KPI (CA du jour, CA du mois, marge estimée, ventes du jour,
   dettes clients en cours, alertes de stock bas), graphique du CA sur 30 jours, 5 dernières
   ventes, bandeau d'alertes (stock bas, dette échue) avec un lien vers l'élément concerné.
2. **Ventes : nouvelle vente** : choix du client ; ajout de lignes (recherche par nom ou SKU,
   quantité, remise, taxe si activée) ; totaux en temps réel (sous-total, remises, taxes, total) ;
   règlement total, partiel (le solde devient une dette) ou « à crédit ». Deux boutons :
   « Enregistrer en brouillon » (aucun effet sur le stock ni la finance) et « Confirmer la
   vente » (verrouille, déduit le stock, crée l'écriture financière, produit un reçu imprimable).
   Stock insuffisant ⇒ message clair : « Stock insuffisant — X unités disponibles ».
3. **Ventes : liste et détail** : statut visuel (brouillon, confirmée, annulée, retournée),
   filtres par statut et par période. Actions selon le statut : Confirmer (brouillon), Annuler
   ou Effectuer un retour (confirmée). Le formulaire de retour permet de choisir les lignes et
   les quantités, puis le règlement (remboursement en trésorerie ou extinction de dette).
4. **Produits** : tableau (icône, nom, SKU, catégorie, prix actuel, stock, statut
   actif / seuil bas / rupture). La fiche produit affiche l'historique des prix (frise), la
   courbe des ventes récentes, les derniers mouvements et un bouton « Ajuster le stock » (motif
   obligatoire). Formulaire d'ajout et de modification.
5. **Clients / Fournisseurs** : listes avec recherche. Fiche client : coordonnées, encours
   autorisé, historique d'achats, dettes en cours. Fiche fournisseur : délai de paiement,
   historique des charges.
6. **Stock** : stock courant (quantité, valeur au CMP, dernier mouvement, surlignage sous le
   seuil d'alerte) ; journal des mouvements filtrable par produit et par type.
7. **Finance** : vue d'ensemble (trésorerie simple entrées/sorties, revenus, dépenses, marge
   estimée, évolution sur 30 jours). Onglets Paiements, Dettes (créances et dettes fournisseurs,
   échéance, solde, « Enregistrer un règlement ») et Dépenses (catégorisées, ajout).
8. **Analytics** : sélecteur des 8 métriques (CA généré, marge générée, quantité vendue,
   fréquence de vente, rotation du stock, vélocité des ventes, évolution de la demande,
   potentiel futur estimé). Top 10 produits **pour la métrique choisie uniquement**, avec le nom
   de la métrique visible. Séries temporelles du CA et de la marge.
9. **CoGes Intelligence** : cartes de recommandation avec la métrique, la valeur, la date de
   calcul et le niveau d'incertitude. Exemples : risque de rupture, demande en hausse, anomalie.
   « Données insuffisantes pour ce produit » plutôt qu'une valeur inventée. Jamais « meilleur
   produit ».
10. **Paramètres** : Entreprise (nom, devise, TVA activée, seuils par défaut) ; Utilisateurs et
    rôles (gérant, vendeur, comptable) avec l'aperçu des permissions ; Journal d'activité.

## Règles d'UX à garder

- Brouillon = aucun effet. Seule la confirmation déclenche stock, finance et reçu.
- Une vente confirmée n'est plus modifiable : seules l'annulation et le retour restent possibles.
- Le stock ne peut jamais devenir négatif : l'action est bloquée avec un message explicite.
- Toute recommandation ou tout classement nomme sa métrique et sa date de calcul.
- Montants en FCFA sans décimales, séparateur de milliers espace.
- Interface pensée d'abord pour l'ordinateur (gérant, comptable), correcte sur tablette.
