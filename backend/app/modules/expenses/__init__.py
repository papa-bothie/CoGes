"""Module Expenses — dépenses et charges catégorisées (bande D).

Une dépense est une **charge constatée** : ce que l'entreprise a dépensé, quand, et
pour quoi. Qu'elle soit payée ou non ne se lit pas ici mais dans `finance` — un
décaissement rattaché à la dépense (`payments.expense_id`), ou une dette
fournisseur ouverte à la main.

Hors V1, explicitement : aucune charge récurrente automatisée. `kind`
(`fixed` / `variable`) vit sur la **catégorie**, comme le veut le § 8.6, et
« dupliquer le mois précédent » sera un formulaire pré-rempli, pas un job.
"""
