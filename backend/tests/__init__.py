"""Suites de tests du backend CoGes."""

import os

# Importé par pytest avant `conftest.py`, donc avant la première lecture des réglages.
# La suite enchaîne des milliers de requêtes depuis la même « IP » de TestClient et pour
# une poignée d'entreprises : la limitation de débit y est coupée.
# `tests/integration/test_rate_limit.py` la rallume pour ses propres cas.
for _limit in ("IP", "TENANT", "LOGIN"):
    os.environ.setdefault(f"COGES_RATE_LIMIT_{_limit}_PER_MINUTE", "0")
