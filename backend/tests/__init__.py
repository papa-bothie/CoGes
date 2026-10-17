"""Suites de tests du backend CoGes."""

import os

# Importé par pytest avant `conftest.py`, donc avant la première lecture des réglages.
# La suite enchaîne des milliers de requêtes depuis la même « IP » de TestClient et pour
# une poignée d'entreprises : la limitation de débit y est coupée.
# `tests/integration/test_rate_limit.py` la rallume pour ses propres cas. Affectation
# forcée : une valeur déjà exportée dans le shell ferait échouer la suite en 429.
for _limit in ("IP", "TENANT", "LOGIN"):
    os.environ[f"COGES_RATE_LIMIT_{_limit}_PER_MINUTE"] = "0"

# Freinage par compte (ADR 0078) : la suite enchaîne des refus volontaires sur les
# mêmes comptes. Seuil hors d'atteinte ; `test_login_throttle.py` pose le sien.
os.environ["COGES_LOGIN_THROTTLE_FREE_FAILURES"] = "1000000"
os.environ["COGES_LOGIN_THROTTLE_ALERT_AFTER"] = "1000000"
