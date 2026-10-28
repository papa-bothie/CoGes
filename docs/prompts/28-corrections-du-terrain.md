# Prompt 28 — Corrections du terrain : retours, mots de passe, droits, dernières ventes

Branche `feat/field-fixes`, depuis `main` à jour. Quatre défauts remontés à l'usage, à corriger dans l'application des commerçants (`frontend/` et `backend/`). Chacun est **d'abord reproduit par un test qui échoue**, puis corrigé à la racine ; un constat qui ne se reproduit pas est consigné tel quel dans l'ADR, sans rien changer.

Ce que le propriétaire a constaté :
1. Le retour d'un produit est refusé ou impossible sur certaines ventes : **vente payée en totalité** et **vente partiellement payée** (la vente à crédit non payée, elle, marche). Dans l'historique, certaines ventes offrent le retour, d'autres non.
2. Quand un vendeur ou un comptable change son mot de passe, il ne peut ni afficher ni masquer ce qu'il tape.
3. Le comptable voit tout le logiciel, alors que le gérant ne lui a donné que certaines fonctions.
4. Dans l'onglet Vendre, on ne peut pas voir la liste des dernières ventes.

```
Lot « Corrections du terrain » (branche feat/field-fixes, depuis main à jour).
Règles habituelles : ADR au prochain numéro libre, tests d'abord (rouge puis vert), aucun
service payant, ne jamais ouvrir ni commiter .env, deploy/.env.preprod ni backend/.vercel/.
Résumé en français à la fin, questions ouvertes par AskUserQuestion. Aucune règle de sécurité
ne s'assouplit : le serveur reste l'autorité des droits, l'écran ne fait que les refléter.

C1. Retours : une vente confirmée se retourne, quel que soit son état de paiement
Pistes relevées à la lecture (À VÉRIFIER, ne pas les croire) :
 - backend/app/modules/sales/service.py `create_return` n'exige que « vente confirmée » ;
   rien n'y dépend du paiement. La différence vient donc du remboursement (`refund_return`,
   `finance.record_return_refund` / `record_return_offset`, triggers `refund_check` CG041,
   `return_refund_status_set`) ou de l'écran.
 - frontend/app/(app)/sales/[id]/returns/new/return-form.tsx : sans dette ouverte, le mode
   par défaut est « cash » ; avec dette partielle, « debt » ; le remboursement est tenté
   juste après la création du retour, et son échec est avalé (`settled = false`).
 - `sale_returns:confirm` (remboursement) est au gérant seul (ADR 0025) : un vendeur
   enregistre le retour mais son remboursement échoue.
 - Le bouton « Retour » de sale-detail-view.tsx dépend de `returned_qty` et de
   `sale_returns:create` ; la liste des ventes (sales-list-view.tsx) a ses propres états.
Méthode :
 a. Construis une MATRICE de cas, en test d'intégration backend ET en e2e :
    paiement (payée en espèces, payée en mobile money, partiellement payée, à crédit non
    payée, dette passée en perte) x client (identifié, anonyme) x article (suivi, non suivi,
    supprimé depuis la vente) x retour (total, partiel, second retour après un partiel) x rôle
    (gérant, vendeur, comptable) x chemin de remboursement (espèces, mobile money, déduction
    de la dette, « plus tard »). Pour chaque case : le bouton « Retour » apparaît-il ? le
    retour s'enregistre-t-il ? le stock rentre-t-il ? le remboursement passe-t-il ?
 b. Liste les cases rouges dans l'ADR (tableau reproduit / non reproduit), puis corrige à la
    racine, case par case, test rouge d'abord.
 c. Règles à garantir après correction (propriétaire) :
    - une vente confirmée peut TOUJOURS être retournée pour ses quantités restantes, payée,
      partiellement payée ou à crédit ; le bouton est présent dans le détail ET proposé depuis
      la liste de l'historique pour les mêmes ventes ;
    - vente payée : remboursement en espèces ou mobile money, ou « plus tard » ;
    - vente partiellement payée : la déduction de la dette restante vient d'abord, le surplus
      se rembourse (ou se met « plus tard ») dans le MÊME écran, sans deux opérations à la
      main ; si cette règle te paraît ambiguë (ordre, plafond), pose-moi la question avant de
      coder ;
    - vendeur : il enregistre le retour (stock, montants) ; le remboursement, réservé au
      gérant, n'est pas tenté pour lui. L'écran dit en mots simples « Retour enregistré. Le
      gérant doit encore rembourser X F », le retour apparaît « à rembourser » côté gérant, et
      jamais d'erreur muette (`settleFailed` ne doit plus cacher la vraie cause) ;
    - aucun montant remboursé ne dépasse la valeur des articles rendus (CG041 reste l'autorité),
      aucune ligne de trésorerie fantôme pour une compensation (ADR 0024, 0062) ;
    - le comptable ne crée ni ne rembourse un retour (matrice inchangée).
 d. Cas de non-régression : les tests T18 à T22 et ceux des ADR 0024, 0025 et 0062 restent
    verts sans être modifiés ; si l'un doit changer, dis-le et justifie-le dans l'ADR.

C2. Mots de passe : afficher / masquer partout
 - Un seul composant `PasswordField` (frontend/components/) : champ + bouton « Afficher /
   Cacher » (aria-pressed, nom accessible, cible tactile 44 px), valeur conservée quand on
   bascule, retour au mode masqué à l'envoi et quand l'onglet est caché, `autocomplete`
   correct (`current-password` / `new-password`), jamais de valeur dans l'URL ni dans un
   journal. S'inspire du bouton déjà présent dans login-form.tsx, qu'il remplace.
 - Utilisé dans : connexion, « Choisissez votre mot de passe » (première connexion,
   first-password-form.tsx : trois champs aujourd'hui sans bouton), et dans un nouvel écran
   « Changer mon mot de passe ».
 - « Changer mon mot de passe » : accessible à TOUS les rôles depuis le menu du compte (pas
   depuis Réglages, que le vendeur et le comptable n'ont pas), qui appelle POST
   /api/v1/auth/password (existant). Règle de longueur affichée avant l'erreur, même message
   d'erreur que partout, confirmation « Retapez le nouveau mot de passe » avec contrôle de
   concordance avant l'envoi. Vérifie ce que le serveur fait des autres sessions après un
   changement (révocation) et dis-le dans l'ADR ; ne change cette règle qu'après accord.
 - Même composant dans l'administration (frontend-admin/) pour sa connexion : copie, pas
   d'import entre applications.
 - Tests : Vitest (bascule, valeur conservée, retour au masqué), e2e (un vendeur et un
   comptable changent leur mot de passe, se reconnectent avec le nouveau), axe 0 violation.

C3. Droits : un compte ne voit et ne fait que ce que son rôle autorise
Constat : le comptable voit presque tout, malgré la grille « Qui peut faire quoi » (Réglages,
ADR 0075). Pistes (À VÉRIFIER) : les entrées de navigation (lib/navigation.ts) utilisent des
droits larges (`anyOf: products:create | analytics:read` pour Stock) ; des pages et boutons
n'ont peut-être pas de garde propre ; la grille ne couvre que huit gestes ; la matrice par
défaut du comptable (rbac/matrix.py) est large (31 droits).
Méthode :
 a. Reproduis : crée un comptable, retire dans la grille tout sauf un geste, connecte-toi
    avec lui et relève ce qu'il voit et ce qu'il peut atteindre par adresse directe. Écris-le
    en test e2e (rouge).
 b. Cartographie en test : pour CHAQUE écran, entrée de navigation, tuile du tableau de
    bord, bouton d'action et route de l'API, le droit exact exigé ; un test échoue si une
    entrée n'a pas de droit déclaré (registre, comme les routes de l'API).
 c. Corrige : entrées de navigation sur le droit précis de leur écran (plus de `anyOf` qui
    ouvre un écran par un droit voisin) ; garde de page pour l'adresse directe (message
    « Vous n'avez pas accès à cette page », aucune donnée chargée, aucun appel d'API inutile) ;
    tuiles et raccourcis du tableau de bord filtrés ; une grille modifiée par le gérant prend
    effet pour la personne concernée à sa requête suivante (pas seulement à sa reconnexion).
 c2. CAUSE DÉJÀ REPÉRÉE À LA LECTURE (à confirmer par test rouge) : la grille « Qui peut
    faire quoi » (rbac/matrix.py `ABILITIES`, rbac/service.py `set_role_abilities`) ne pilote
    que 8 gestes. Les autres droits d'un rôle système « ne bougent pas » : le comptable garde
    donc, quoi que fasse le gérant, `debts:*`, `payments:update|cancel`, `expenses:create|
    update|delete`, `audit:read|export`, `insights:*`, `analytics:export`, `sales:export`,
    `importexport:export`, `company:read`… et les entrées du menu qui en découlent
    (« Argent » s'ouvre sur `debts:read`). Le gérant ne peut pas retirer ce qu'elle ne montre
    pas. Correction attendue : tout droit du catalogue (sauf ceux réservés au gérant,
    `users:` et `roles:`) appartient à au moins un geste de la grille, en mots simples
    (ex. « Gérer les dépenses », « Voir le journal d'activité », « Exporter des fichiers »,
    « Voir les conseils », « Corriger ou annuler un paiement »), avec un test-registre qui
    échoue si un droit n'est dans aucun geste. Propose-moi la liste des gestes en français
    simple AVANT de coder (AskUserQuestion) ; une ligne décochée retire tous ses droits.
 d. NE CHANGE PAS la matrice par défaut des rôles (ADR 0007) sans me demander : si elle te
    semble trop large pour le comptable, liste les droits en cause avec ta recommandation et
    pose-moi la question (AskUserQuestion).
 e. Tests : matrice rôle x écran en e2e (gérant, vendeur, comptable par défaut, comptable
    restreint, rôle sur mesure), chaque refus testé côté serveur ET côté écran ; tests de
    fuite inter-tenant inchangés et verts.

C4. Vendre : les dernières ventes
 - Sur l'écran Vendre (/sales/new), un bloc « Dernières ventes » : les 8 dernières ventes de
   l'entreprise (numéro, heure, client, montant, pastille payée / à crédit / annulée /
   retournée), un toucher ouvre le détail, « Voir toutes les ventes » mène à /sales. Réutilise
   le point d'accès de liste existant avec une limite (pas de nouvelle route sauf si
   indispensable) et les composants du kit (list-row, status-pill).
 - Visible pour qui a `sales:read` (le vendeur l'a). Mise en page : colonne à droite dès
   1024 px, sous le panier sur téléphone, repliable ; ne doit jamais pousser le panier ni
   le bouton d'encaissement hors de l'écran. Actualisé après chaque vente confirmée ou
   annulée ; squelette de chargement, état vide « Aucune vente pour l'instant », erreur de
   chargement qui n'empêche pas de vendre.
 - Chaque ligne annulée ou retournée est lisible sans couleur seule (texte + icône).
 - Tests : Vitest du bloc (vide, erreur, ligne annulée), e2e (confirmer une vente la fait
   apparaître en tête), axe 0 violation, 360 px sans défilement horizontal.

Fin de lot
Suite backend complète, ruff, mypy, make front-check, e2e des écrans touchés, tests de fuite
inter-tenant, CI verte. ADR : tableau des cas de retour (reproduit / non reproduit / corrigé),
causes racines, décisions sur les sessions après changement de mot de passe, liste des droits
exigés par écran. Mets à jour CLAUDE.md §8 et la table des ADR.

Hors lot, volontairement : brouillons conservés d'un écran à l'autre, application installable,
inscription libre-service, thème de l'administration (prompts 27, 29 et 30).
```

## Ce que le propriétaire fait lui-même

1. Après le déploiement, refaire à la main les deux cas qui échouaient : retour d'une vente **payée en totalité**, puis d'une vente **partiellement payée**, avec le gérant puis avec un vendeur.
2. Créer un comptable de test, lui retirer des fonctions dans Réglages, se connecter avec lui et vérifier qu'il ne voit que le reste.
3. Répondre aux questions de l'agent sur la matrice par défaut du comptable et sur l'ordre de remboursement d'une vente partiellement payée : ce sont des choix métier.
