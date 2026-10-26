"""Vérifie une base restaurée depuis une sauvegarde (ADR 0084, docs/runbooks/sauvegarde.md).

Lancé par `restore_backup.sh` après `pg_restore`, ou seul :

  python3 deploy/scripts/verify_restore.py "postgresql://postgres:…@localhost:5433/coges_restore"

Contrôles (sortie lisible, code 0 si tout est vert, 1 sinon) :

1. révision Alembic = celle de la base sauvegardée, notée dans le manifeste
   (`alembic_revision`) ; à défaut (manifeste plus ancien, ou absent), la dernière du dépôt
   (`backend/migrations/versions`) ;
2. lignes des tables clés, par entreprise (identifiant court, jamais de nom) ; « au moins
   une entreprise » n'est qu'un avertissement si le manifeste en compte 0 (base de
   production encore vide) ;
3. RLS active et FORCE sur chaque table qui porte `company_id` ;
4. partition d'audit du mois courant présente, séquences présentes ;
5. cohérence : stock projeté = somme des mouvements, dans les deux sens (une projection
   sans mouvement comme des mouvements sans projection), aucun stock négatif, dettes
   cohérentes (0 ≤ payé ≤ principal, « payée » ⇔ solde nul), aucun paiement plus lettré
   que son montant ;
6. manifeste (ADR 0088) : chaque table clé a au moins autant de lignes qu'au moment de la
   sauvegarde. `backup.sh` compte **avant** le dump, et ces tables ne perdent jamais de
   ligne (suppression logique) : une restauration tronquée se voit, une écriture pendant
   le dump n'est pas un écart.

La base doit être lue sans être filtrée par la RLS : connexion en superutilisateur, en
propriétaire de la base restaurée avec BYPASSRLS, ou en `coges_backup`.
Bibliothèque standard seulement (appelle `psql`).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

VERSIONS = Path(__file__).resolve().parents[2] / "backend" / "migrations" / "versions"
KEY_TABLES = (
    "users",
    "products",
    "customers",
    "inventory_movements",
    "sales",
    "payments",
    "debts",
    "expenses",
)
REVISION = re.compile(r'^revision: str = "([^"]+)"', re.M)
DOWN = re.compile(r'^down_revision: str \| None = (?:"([^"]+)"|None)', re.M)


def manifest_query() -> str:
    """Le comptage des tables clés, que `backup.sh` joue avant le dump."""
    return " UNION ALL ".join(f"SELECT '{table}', count(*) FROM {table}" for table in KEY_TABLES)


def manifest_gaps(expected: dict[str, int], actual: dict[str, int]) -> list[str]:
    """Tables qui ont moins de lignes que dans le manifeste de la sauvegarde."""
    return [
        f"{table} : {actual.get(table, 0)} restaurées, {count} au moment de la sauvegarde"
        for table, count in sorted(expected.items())
        if actual.get(table, 0) < count
    ]


def head_revision(versions: Path = VERSIONS) -> str:
    """La révision que nulle autre ne prolonge : la tête du dépôt."""
    revisions: set[str] = set()
    parents: set[str] = set()
    for path in versions.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        found = REVISION.search(text)
        if found is None:
            continue
        revisions.add(found.group(1))
        down = DOWN.search(text)
        if down and down.group(1):
            parents.add(down.group(1))
    heads = sorted(revisions - parents)
    if len(heads) != 1:
        raise SystemExit(f"tête Alembic ambiguë : {heads}")
    return heads[0]


class Database:
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn

    def rows(self, sql: str) -> list[list[str]]:
        result = subprocess.run(
            ["psql", self.dsn, "-X", "-A", "-t", "-F", "\t", "-v", "ON_ERROR_STOP=1", "-c", sql],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip())
        return [line.split("\t") for line in result.stdout.splitlines() if line]

    def value(self, sql: str) -> str:
        rows = self.rows(sql)
        return rows[0][0] if rows else ""


class Manifest:
    """Ce que `backup.sh` a noté avant le dump (champs absents des anciens manifestes)."""

    def __init__(self, data: dict[str, Any]) -> None:
        self.tables = {str(table): int(count) for table, count in data["tables"].items()}
        self.alembic_revision: str | None = data.get("alembic_revision") or None
        companies = data.get("companies")
        self.companies = None if companies is None else int(companies)


class Report:
    def __init__(self) -> None:
        self.failures = 0
        self.warnings = 0

    def warn(self, label: str, detail: str = "") -> None:
        print(f"  AVERT {label}{f' — {detail}' if detail else ''}")
        self.warnings += 1

    def check(self, label: str, ok: bool, detail: str = "") -> None:
        mark = "OK    " if ok else "ÉCHEC "
        print(f"  {mark}{label}{f' — {detail}' if detail else ''}")
        if not ok:
            self.failures += 1


def verify(
    db: Database,
    *,
    expected_revision: str,
    today: datetime,
    manifest: Manifest | None = None,
) -> int:
    report = Report()

    print("1. Migrations")
    current = db.value("SELECT version_num FROM alembic_version")
    if manifest is not None and manifest.alembic_revision:
        expected, source = manifest.alembic_revision, "de la sauvegarde"
    else:
        expected, source = expected_revision, "tête du dépôt, manifeste sans révision"
    report.check(
        "révision Alembic",
        current == expected,
        f"{current} (attendue {expected}, {source})",
    )

    print("2. Lignes par entreprise")
    companies = db.rows("SELECT id FROM companies ORDER BY created_at")
    if not companies and manifest is not None and manifest.companies == 0:
        report.warn("au moins une entreprise", "0, comme la base sauvegardée")
    else:
        report.check("au moins une entreprise", bool(companies), f"{len(companies)} entreprise(s)")
    for (company_id,) in companies:
        counts = []
        for table in KEY_TABLES:
            n = db.value(f"SELECT count(*) FROM {table} WHERE company_id = '{company_id}'")
            counts.append(f"{table} {n}")
        print(f"      {company_id[:8]} : " + ", ".join(counts))

    print("3. Isolation des entreprises (RLS)")
    unprotected = db.rows(
        """
        SELECT c.relname FROM pg_class c
        JOIN pg_attribute a
          ON a.attrelid = c.oid AND a.attname = 'company_id' AND NOT a.attisdropped
        WHERE c.relnamespace = 'public'::regnamespace AND c.relkind IN ('r', 'p')
          AND NOT (c.relrowsecurity AND c.relforcerowsecurity)
        ORDER BY c.relname
        """
    )
    report.check(
        "RLS active et FORCE sur chaque table d'entreprise",
        not unprotected,
        ", ".join(row[0] for row in unprotected),
    )

    print("4. Partitions et séquences")
    partition = f"audit_logs_{today:%Y}m{today:%m}"
    present = db.value(f"SELECT count(*) FROM pg_class WHERE relname = '{partition}'") == "1"
    report.check(f"partition d'audit du mois ({partition})", present)
    sequences = int(db.value("SELECT count(*) FROM pg_sequences WHERE schemaname = 'public'"))
    report.check("séquences présentes", sequences > 0, f"{sequences}")

    print("5. Cohérence des chiffres")
    stock_gap = db.value(
        """
        SELECT count(*) FROM product_stock s
        FULL JOIN (SELECT company_id, product_id, sum(qty_delta) AS total
                   FROM inventory_movements GROUP BY company_id, product_id) m
          ON m.company_id = s.company_id AND m.product_id = s.product_id
        WHERE coalesce(s.qty_on_hand, 0) <> coalesce(m.total, 0)
        """
    )
    report.check("stock = somme des mouvements", stock_gap == "0", f"{stock_gap} écart(s)")
    negative = db.value("SELECT count(*) FROM product_stock WHERE qty_on_hand < 0")
    report.check("aucun stock négatif", negative == "0", f"{negative}")
    bad_debts = db.value(
        """
        SELECT count(*) FROM debts
        WHERE amount_paid < 0 OR amount_paid > principal
           OR (status = 'paid' AND balance <> 0)
           OR (status IN ('open', 'partially_paid') AND balance <= 0)
        """
    )
    report.check("dettes cohérentes", bad_debts == "0", f"{bad_debts} incohérente(s)")
    over_allocated = db.value(
        """
        SELECT count(*) FROM payments p
        JOIN (SELECT company_id, payment_id, sum(amount) AS lettered
              FROM payment_allocations GROUP BY company_id, payment_id) a
          ON a.company_id = p.company_id AND a.payment_id = p.id
        WHERE a.lettered > p.amount
        """
    )
    report.check(
        "aucun paiement plus lettré que son montant",
        over_allocated == "0",
        f"{over_allocated}",
    )

    print("6. Manifeste de la sauvegarde")
    if manifest is None:
        report.check("manifeste", True, "absent : sauvegarde antérieure à l'ADR 0088")
    else:
        actual = {table: int(count) for table, count in db.rows(manifest_query())}
        gaps = manifest_gaps(manifest.tables, actual)
        report.check("autant de lignes qu'à la sauvegarde", not gaps, "; ".join(gaps))

    if report.failures:
        print(f"Restauration : {report.failures} contrôle(s) en échec")
        return 1
    if report.warnings:
        print(f"Restauration vérifiée : tout est vert ({report.warnings} avertissement(s)).")
        return 0
    print("Restauration vérifiée : tout est vert.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("dsn", nargs="?", help="base restaurée (jamais la production)")
    parser.add_argument("--expected-revision", default=None)
    parser.add_argument("--manifest", type=Path, default=None, help="manifeste de la sauvegarde")
    parser.add_argument(
        "--print-manifest-query", action="store_true", help="la requête de comptage, pour backup.sh"
    )
    args = parser.parse_args(argv)
    if args.print_manifest_query:
        print(manifest_query())
        return 0
    if not args.dsn:
        parser.error("la base restaurée est requise")
    manifest = None
    if args.manifest is not None:
        manifest = Manifest(json.loads(args.manifest.read_text()))
    db = Database(args.dsn)
    try:
        return verify(
            db,
            expected_revision=args.expected_revision or head_revision(),
            today=datetime.now(UTC),
            manifest=manifest,
        )
    except RuntimeError as error:
        print(f"ÉCHEC : {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
