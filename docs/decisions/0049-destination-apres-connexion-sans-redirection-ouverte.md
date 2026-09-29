# 0049 — Destination après connexion sans redirection ouverte

- **Date** : 2026-09-29
- **Phase** : 11 (correctif de sécurité avant la phase 12)
- **Statut** : acceptée — complète l'ADR 0048
- **Décideur** : utilisateur (correctif demandé et spécifié)

## Contexte

L'ADR 0048 acceptait `?next=` s'il commençait par `/` sans commencer par `//`.
`/login?next=/\evil.example` passait ce contrôle : le navigateur lit `\` comme `/`, et
`location.assign("/\evil.example")` sortait du site après une connexion réussie. C'est une
**redirection ouverte**, exploitable pour de l'hameçonnage à partir d'un vrai lien CoGes.

Deux autres formes contournent un contrôle sur la chaîne brute : les tabulations et retours à
la ligne, que le parseur d'URL supprime (`/\t/evil.example`), et les segments relatifs, qui se
normalisent en chemin protocole-relatif (`/.//evil.example`, `/%2e//evil.example` donnent le
chemin `//evil.example`, **de même origine** pour `new URL`).

## Options envisagées

1. **Parser avec `new URL(next, origine)` et contrôler le résultat (retenue)** : c'est le
   même algorithme que le navigateur, qui décide seul de ce qu'est une origine.
2. Durcir le test sur la chaîne brute : liste de motifs toujours incomplète.

## Décision

`lib/auth/safe-next.ts` → `safeNext(next, origine)`, sans `window` :

1. refuse toute valeur vide, contenant `\` ou un caractère de contrôle (C0, DEL) ;
2. résout avec `new URL(next, origine)` ; refuse une origine différente ;
3. refuse un chemin résolu qui commence par `//` (il repartirait ailleurs une fois réutilisé
   comme URL relative) ;
4. refuse `/login` (et ses sous-chemins) ;
5. renvoie `pathname + search + hash` ; sinon `/dashboard`.

Appliquée **partout** où un `next` est lu ou construit : formulaire de connexion (lecture),
`loginUrl` (session expirée) et `proxy.ts` (redirection vers la connexion). Un `next` douteux
n'est donc jamais propagé, ni accepté.

## Conséquences

- Tests Vitest : `//evil.example`, `/\evil.example`, `/\t/evil.example`,
  `https://evil.example`, `javascript:alert(1)`, `/.//evil.example`, `/%2e//evil.example`,
  `/login`, chemin interne avec paramètres et ancre. `/%2F%2Fevil.example` reste accepté
  **tel quel, encodé** : il désigne un chemin du site (introuvable), pas une autre origine.
- Parcours Playwright : connexion avec `next=/\evil.example` ⇒ l'utilisateur reste sur
  `/dashboard` du site.
