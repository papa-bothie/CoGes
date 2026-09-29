/**
 * Textes de l'interface, regroupés ici pour éviter leur dispersion dans les composants.
 * Les messages d'erreur **métier** viennent de l'API (déjà en français) : ils ne sont pas
 * dupliqués ici.
 */
export const labels = {
  app: {
    name: "CoGes",
    tagline: "Gestion commerciale",
    version: (v: string) => `Version ${v}`,
    skipToContent: "Aller au contenu",
  },
  nav: {
    dashboard: "Tableau de bord",
    sales: "Ventes",
    inventory: "Stock",
    products: "Produits",
    customers: "Clients",
    suppliers: "Fournisseurs",
    finance: "Finance",
    analytics: "Analytics",
    insights: "CoGes Intelligence",
    settings: "Paramètres",
    notifications: "Notifications",
    openMenu: "Ouvrir le menu",
    mainNavigation: "Navigation principale",
  },
  header: {
    notifications: (count: number) =>
      count === 0
        ? "Notifications, aucune non lue"
        : `Notifications, ${count} non lue${count > 1 ? "s" : ""}`,
    logout: "Se déconnecter",
    theme: "Changer de thème",
    themeLight: "Clair",
    themeDark: "Sombre",
    themeSystem: "Système",
  },
  login: {
    title: "Connexion",
    subtitle: "Accédez à l'espace de gestion de votre entreprise.",
    companySlug: "Identifiant d'entreprise",
    companySlugHint: "Communiqué à la création de votre compte, par exemple « ma-boutique ».",
    email: "Adresse e-mail",
    password: "Mot de passe",
    submit: "Se connecter",
    submitting: "Connexion…",
    sessionExpired: "Votre session a expiré. Reconnectez-vous.",
    loggedOut: "Vous êtes déconnecté.",
  },
  validation: {
    required: "Ce champ est obligatoire.",
    slug: "3 à 40 caractères : lettres minuscules, chiffres et tirets.",
    email: "Adresse e-mail invalide.",
    invalidValue: "Valeur refusée par le serveur.",
  },
  errors: {
    generic: "Une erreur inattendue est survenue. Réessayez.",
    network: "Le serveur est injoignable. Vérifiez votre connexion.",
    notFoundTitle: "Page introuvable",
    notFoundBody: "Cette page n'existe pas, ou la ressource demandée n'est pas accessible.",
    backToDashboard: "Retour au tableau de bord",
    forbidden: "Vous n'avez pas la permission d'effectuer cette action.",
    retry: "Réessayer",
    loadFailed: "Impossible de charger ces données",
  },
  table: {
    search: "Rechercher",
    empty: "Aucun élément à afficher.",
    loading: "Chargement…",
    previous: "Page précédente",
    next: "Page suivante",
    pageOf: (page: number, pages: number) => `Page ${page} sur ${pages}`,
    total: (count: number) => `${count} élément${count > 1 ? "s" : ""}`,
    sortAscending: "tri croissant",
    sortDescending: "tri décroissant",
  },
  forecast: {
    metric: "Métrique",
    computedAt: "Date de calcul",
    model: "Modèle",
    uncertainty: "Incertitude",
    insufficientData: "Données insuffisantes",
  },
  dashboard: {
    revenueToday: "CA du jour",
    revenueMonth: "CA du mois",
    marginMonth: "Marge estimée du mois",
    salesToday: "Ventes du jour",
    receivables: "Créances clients en cours",
    stockAlerts: "Alertes de stock",
    stockAlertsHint: (count: number) =>
      count === 0 ? "Aucun article sous le seuil" : "Articles sous le seuil ou en rupture",
    monthHint: (from: string, to: string) => `Du ${from} au ${to}`,
    marginHint: "Prix de vente − coût moyen pondéré",
    revenueTrend: "Chiffre d'affaires des 30 derniers jours",
    revenueTrendLabel: "Chiffre d'affaires net par jour sur 30 jours",
    recentSales: "Dernières ventes",
    noRecentSales: "Aucune vente confirmée pour l'instant.",
    anonymousCustomer: "Client anonyme",
    computedAt: (at: string) => `Chiffres calculés le ${at}`,
    seeAllSales: "Toutes les ventes",
    alerts: "Alertes",
    stockAlertBanner: (count: number) =>
      count > 1
        ? `${count} articles sous le seuil d'alerte ou en rupture`
        : "1 article sous le seuil d'alerte ou en rupture",
    seeStock: "Voir le stock",
    alertGroup: (title: string, count: number) => `${title} (${count})`,
  },
  sales: {
    status: {
      draft: "Brouillon",
      confirmed: "Confirmée",
      cancelled: "Annulée",
      returned: "Retournée",
    },
  },
  stock: {
    status: { ok: "Disponible", low: "Seuil bas", out: "Rupture" },
  },
  emptyPage: {
    title: "Bientôt disponible",
    body: "Cet écran sera construit dans une prochaine phase.",
  },
} as const;
