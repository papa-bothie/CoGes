"""Les données d'une installation sur site sont-elles toujours là ? (ADR 0124)

Se connecte par l'API publique (http://localhost) avec le gérant, relit la société et
compte ses ventes confirmées. Lancé par deploy/onprem-ci/verifier.sh après chaque
redémarrage, changement de version ou arrêt brutal de PostgreSQL.

Usage : python3 controle_donnees.py --url http://localhost --slug S --email E
        --min-sales 1 [--exact]   (mot de passe : variable ONPREM_PASSWORD)
Bibliothèque standard seulement.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from typing import Any


def call(url: str, *, token: str | None = None, body: dict[str, Any] | None = None) -> Any:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, headers=headers)  # noqa: S310
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
        return json.load(response)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--url", default="http://localhost")
    parser.add_argument("--slug", required=True)
    parser.add_argument("--email", required=True)
    parser.add_argument("--min-sales", type=int, default=1)
    # Après une restauration (ADR 0127) : exactement le nombre de ventes de la sauvegarde.
    parser.add_argument("--exact", action="store_true")
    args = parser.parse_args(argv)
    password = os.environ.get("ONPREM_PASSWORD")
    if not password:
        print("ONPREM_PASSWORD manque", file=sys.stderr)
        return 2

    api = args.url.rstrip("/") + "/api/v1"
    login = {"company_slug": args.slug, "email": args.email, "password": password}
    token = call(f"{api}/auth/login", body=login)["access_token"]
    company = call(f"{api}/companies/me", token=token)
    sales = call(f"{api}/sales?page=1&page_size=1&status=confirmed", token=token)

    if company.get("slug") != args.slug:
        print(f"ÉCHEC — société attendue « {args.slug} », lue « {company.get('slug')} »")
        return 1
    if args.exact and sales["total"] != args.min_sales:
        print(f"ÉCHEC — {sales['total']} vente(s), exactement {args.min_sales} attendue(s)")
        return 1
    if sales["total"] < args.min_sales:
        print(f"ÉCHEC — {sales['total']} vente(s), {args.min_sales} attendue(s) au moins")
        return 1
    print(f"OK — société « {company['name']} », {sales['total']} vente(s) retrouvée(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
