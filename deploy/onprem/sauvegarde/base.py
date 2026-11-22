"""Opérations de base de données de la sauvegarde sur site (ADR 0127).

Lancé dans l'image `worker` (Python, `psycopg`), par le service `sauvegarde-py` qui partage
le réseau du conteneur `postgres` : on s'y connecte en superutilisateur sur 127.0.0.1, en
confiance locale (pg_hba de l'image officielle), donc SANS aucun mot de passe. Le
superutilisateur est le seul rôle du poste qui lit sans filtre de RLS (`coges_backup` y
existe, mais sans mot de passe, donc sans connexion possible).

Les contrôles d'une base restaurée sont ceux de la production : `verify_restore.py` est
une COPIE À L'OCTET PRÈS de `deploy/scripts/verify_restore.py` (un test le vérifie), à
qui l'on donne ici une connexion `psycopg` à la place de `psql` (absent de cette image).

    python base.py manifeste --sortie F --version V   lignes comptées AVANT le dump
    python base.py revisions                          révisions connues du programme installé
    python base.py preparer NOM                       base vide (coges_restauration, coges_verif)
    python base.py verifier NOM --manifeste F         contrôles de la production + du sur site
    python base.py supprimer NOM                      coges_verif, coges_restauration, anciennes
    python base.py bascule HORODATAGE                 coges → coges_avant_H, restauration → coges
    python base.py retour HORODATAGE                  coges → coges_echec_H, coges_avant_H → coges
    python base.py bases                              anciennes bases (hors copies de mise à jour)
    python base.py etat                               coges existe-t-elle ; sociétés et ventes

Mises à jour (lot 5, ADR 0128) : le retour arrière se fait SANS la clé privée (que le PC n'a
pas), par une copie de la base dans le même PostgreSQL, faite application arrêtée.

    python base.py copier HORODATAGE                  coges → copie coges_avant_maj_H (TEMPLATE)
    python base.py remettre H --ecarter E             coges → coges_<E>_maj_H, copie → coges
    python base.py copies                             les copies d'avant une mise à jour
    python base.py compter [--depuis ISO]             sociétés, ventes, codes, dernière activité

Support à distance (lot 6, ADR 0129) : la licence en nombres, sans nom ni code de boutique.

    python base.py licence                            licences par état, offres, sans fin ou non
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg
from psycopg import sql

sys.path.insert(0, str(Path(__file__).resolve().parent))
import verify_restore  # noqa: E402  (copie fidèle, à côté de ce fichier)

VERSIONS = Path("/srv/coges/migrations/versions")
MAIN = "coges"
SCRATCH = re.compile(r"^(coges_restauration|coges_verif)$")
KEPT = re.compile(r"^coges_(avant|echec)_\d{8}_\d{4,6}$")
#: Copie d'avant une mise à jour, et base écartée par un retour arrière (lot 5).
UPDATE_COPY = re.compile(r"^coges_avant_maj_\d{8}_\d{4,6}$")
UPDATE_KEPT = re.compile(r"^coges_(echec|apres)_maj_\d{8}_\d{4,6}$")
STAMP = re.compile(r"^\d{8}_\d{4,6}$")


class BaseError(Exception):
    """Refus expliqué en français."""


def connect(dbname: str, *, autocommit: bool = False) -> psycopg.Connection[Any]:
    return psycopg.connect(host="127.0.0.1", user="postgres", dbname=dbname, autocommit=autocommit)


def exists(name: str) -> bool:
    with connect("postgres") as conn:
        return (
            conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,)).fetchone()
            is not None
        )


class PsycopgDatabase(verify_restore.Database):
    """La `Database` de verify_restore.py, mais par psycopg ; même forme que `psql -A -t`."""

    def __init__(self, dbname: str) -> None:
        super().__init__(dbname)
        self.dbname = dbname

    def rows(self, query: str) -> list[list[str]]:
        try:
            with connect(self.dbname) as conn:
                result = conn.execute(query.encode()).fetchall()
        except psycopg.Error as error:
            raise RuntimeError(str(error).strip()) from error
        return [[_text(value) for value in row] for row in result]


def _text(value: object) -> str:
    if value is None:
        return ""
    if value is True:
        return "t"
    if value is False:
        return "f"
    return str(value)


# ---------------------------------------------------------------------------- manifeste


def cmd_manifest(target: Path, version: str) -> None:
    with connect(MAIN) as conn:
        server_version = str(conn.execute("SELECT current_setting('server_version')").fetchone()[0])  # type: ignore[index]
        revision = conn.execute("SELECT version_num FROM alembic_version").fetchone()
        slugs = [row[0] for row in conn.execute("SELECT slug FROM companies ORDER BY created_at")]
        tables = {
            str(table): int(count)
            for table, count in conn.execute(verify_restore.manifest_query().encode())
        }
        size = int(conn.execute("SELECT pg_database_size('coges')").fetchone()[0])  # type: ignore[index]
        # Identifiant du serveur et de la base : une installation neuve ou une base restaurée
        # en change, et la comparaison de taille à la précédente repart de zéro.
        base_id = "{}-{}".format(
            *conn.execute(
                "SELECT (SELECT system_identifier FROM pg_control_system()), "
                "(SELECT oid FROM pg_database WHERE datname = 'coges')"
            ).fetchone()  # type: ignore[misc]
        )
    if revision is None:
        raise BaseError("la base n'a pas de révision Alembic : migrations jamais jouées ?")
    manifest = {
        "format": "COGES-SAUV-1",
        "cree_le": datetime.now(UTC).isoformat(timespec="seconds"),
        "coges_version": version,
        "alembic_revision": revision[0],
        "companies": len(slugs),
        "boutiques": slugs,
        "server_version": server_version.split(" ")[0],
        "base_octets": size,
        "base_id": base_id,
        "tables": tables,
    }
    target.write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=1), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "boutiques": slugs,
                "base_octets": size,
                "base_id": base_id,
                "alembic_revision": revision[0],
            }
        )
    )


def cmd_revisions() -> None:
    known: list[str] = []
    for path in sorted(VERSIONS.glob("*.py")):
        found = verify_restore.REVISION.search(path.read_text(encoding="utf-8"))
        if found:
            known.append(found.group(1))
    print(json.dumps({"tete": verify_restore.head_revision(VERSIONS), "connues": known}))


# ---------------------------------------------------------------------------- bases


def _check_scratch(name: str) -> None:
    if not SCRATCH.match(name):
        raise BaseError(f"« {name} » n'est pas une base de travail de la sauvegarde")


def _terminate(conn: psycopg.Connection[Any], *names: str) -> None:
    conn.execute(
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
        "WHERE datname = ANY(%s) AND pid <> pg_backend_pid()",
        (list(names),),
    )


def cmd_prepare(name: str) -> None:
    _check_scratch(name)
    with connect("postgres", autocommit=True) as conn:
        _terminate(conn, name)
        conn.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(name)))
        # Comme postgres-init/01-roles.sql : propriétaire coges_owner. Les droits du schéma
        # public (REVOKE … FROM PUBLIC, USAGE des rôles) sont dans la sauvegarde.
        conn.execute(sql.SQL("CREATE DATABASE {} OWNER coges_owner").format(sql.Identifier(name)))
    print(f"base {name} prête (vide)")


def cmd_drop(name: str) -> None:
    if not (
        SCRATCH.match(name)
        or KEPT.match(name)
        or UPDATE_COPY.match(name)
        or UPDATE_KEPT.match(name)
    ):
        raise BaseError(f"« {name} » ne se supprime pas par cette commande")
    with connect("postgres", autocommit=True) as conn:
        _terminate(conn, name)
        conn.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(name)))
    print(f"base {name} supprimée")


def _rename(conn: psycopg.Connection[Any], old: str, new: str) -> None:
    conn.execute(
        sql.SQL("ALTER DATABASE {} RENAME TO {}").format(sql.Identifier(old), sql.Identifier(new))
    )


def cmd_switch(stamp: str) -> None:
    if not STAMP.match(stamp):
        raise BaseError("horodatage AAAAMMJJ_HHMM attendu")
    before = f"coges_avant_{stamp}"
    with connect("postgres", autocommit=True) as conn:
        names = {row[0] for row in conn.execute("SELECT datname FROM pg_database")}
        if "coges_restauration" not in names:
            raise BaseError("coges_restauration absente : rien à basculer")
        if before in names:
            raise BaseError(f"{before} existe déjà")
        _terminate(conn, MAIN, "coges_restauration")
        if MAIN in names:
            _rename(conn, MAIN, before)
        _rename(conn, "coges_restauration", MAIN)
    print(json.dumps({"ancienne": before if MAIN in names else None}))


def cmd_back(stamp: str) -> None:
    if not STAMP.match(stamp):
        raise BaseError("horodatage AAAAMMJJ_HHMM attendu")
    before, failed = f"coges_avant_{stamp}", f"coges_echec_{stamp}"
    with connect("postgres", autocommit=True) as conn:
        names = {row[0] for row in conn.execute("SELECT datname FROM pg_database")}
        if before not in names:
            raise BaseError(f"{before} absente : retour impossible")
        _terminate(conn, MAIN, before)
        if MAIN in names:
            _rename(conn, MAIN, failed)
        _rename(conn, before, MAIN)
    print(json.dumps({"remise": before, "ecartee": failed if MAIN in names else None}))


def _databases(pattern: re.Pattern[str]) -> list[dict[str, Any]]:
    with connect("postgres") as conn:
        rows = conn.execute(
            "SELECT datname, pg_database_size(datname) FROM pg_database ORDER BY datname"
        ).fetchall()
    return [{"nom": name, "octets": int(size)} for name, size in rows if pattern.match(name)]


#: Ce que NettoyerAncienneBase propose : les bases d'une restauration, et celles qu'un
#: retour arrière a écartées. Jamais la copie d'avant une mise à jour : c'est elle qui permet
#: de revenir à la version précédente pendant 7 jours, puis la tâche la supprime.
LISTED = re.compile(r"^coges_((avant|echec)|(echec|apres)_maj)_\d{8}_\d{4,6}$")


def cmd_list() -> None:
    print(json.dumps(_databases(LISTED)))


def cmd_copies() -> None:
    print(json.dumps(_databases(UPDATE_COPY)))


def cmd_copy(stamp: str) -> None:
    """Copie de `coges` faite application arrêtée (aucune autre connexion à la base)."""
    if not STAMP.match(stamp):
        raise BaseError("horodatage AAAAMMJJ_HHMM attendu")
    copy = f"coges_avant_maj_{stamp}"
    with connect("postgres", autocommit=True) as conn:
        names = {row[0] for row in conn.execute("SELECT datname FROM pg_database")}
        if MAIN not in names:
            raise BaseError("la base coges n'existe pas : rien à copier")
        if copy in names:
            raise BaseError(f"{copy} existe déjà")
        _terminate(conn, MAIN)
        conn.execute(
            sql.SQL("CREATE DATABASE {} TEMPLATE {} OWNER coges_owner").format(
                sql.Identifier(copy), sql.Identifier(MAIN)
            )
        )
        size = int(conn.execute("SELECT pg_database_size(%s)", (copy,)).fetchone()[0])  # type: ignore[index]
    print(json.dumps({"copie": copy, "octets": size}))


def cmd_put_back(stamp: str, set_aside: str) -> None:
    """La copie redevient `coges` ; la base en place est gardée sous coges_<E>_maj_H."""
    if not STAMP.match(stamp):
        raise BaseError("horodatage AAAAMMJJ_HHMM attendu")
    if set_aside not in ("echec", "apres"):
        raise BaseError("--ecarter echec ou apres attendu")
    copy, aside = f"coges_avant_maj_{stamp}", f"coges_{set_aside}_maj_{stamp}"
    with connect("postgres", autocommit=True) as conn:
        names = {row[0] for row in conn.execute("SELECT datname FROM pg_database")}
        if copy not in names:
            raise BaseError(f"{copy} absente : retour impossible")
        if aside in names:
            raise BaseError(f"{aside} existe déjà")
        _terminate(conn, MAIN, copy)
        if MAIN in names:
            _rename(conn, MAIN, aside)
        _rename(conn, copy, MAIN)
    print(json.dumps({"remise": copy, "ecartee": aside if MAIN in names else None}))


def cmd_count(since: str | None) -> None:
    """Ce que la mise à jour compare avant et après, et l'activité de vente (30 minutes)."""
    result: dict[str, Any] = {
        "existe": exists(MAIN),
        "societes": 0,
        "ventes": 0,
        "boutiques": [],
        "derniere_activite": None,
        "ventes_depuis": None,
    }
    if result["existe"]:
        with connect(MAIN) as conn:
            if conn.execute("SELECT to_regclass('public.companies')").fetchone()[0]:  # type: ignore[index]
                result["boutiques"] = [
                    row[0] for row in conn.execute("SELECT slug FROM companies ORDER BY created_at")
                ]
                result["societes"] = len(result["boutiques"])
            if conn.execute("SELECT to_regclass('public.sales')").fetchone()[0]:  # type: ignore[index]
                count, last = conn.execute(
                    "SELECT count(*), max(greatest(created_at, updated_at, "
                    "coalesce(confirmed_at, created_at))) FROM sales"
                ).fetchone()  # type: ignore[misc]
                result["ventes"] = int(count)
                result["derniere_activite"] = last.isoformat() if last else None
                if since:
                    result["ventes_depuis"] = int(
                        conn.execute(
                            "SELECT count(*) FROM sales WHERE created_at > %s::timestamptz",
                            (since,),
                        ).fetchone()[0]  # type: ignore[index]
                    )
    print(json.dumps(result))


def cmd_state() -> None:
    present = exists(MAIN)
    companies = sales = 0
    if present:
        with connect(MAIN) as conn:
            table = conn.execute("SELECT to_regclass('public.companies')").fetchone()
            if table and table[0]:
                companies = int(conn.execute("SELECT count(*) FROM companies").fetchone()[0])  # type: ignore[index]
            # Même mesure que le manifeste (toutes les lignes de sales) : comparée à celle de
            # la sauvegarde choisie avant de restaurer (lot 5, bloc 0).
            table = conn.execute("SELECT to_regclass('public.sales')").fetchone()
            if table and table[0]:
                sales = int(conn.execute("SELECT count(*) FROM sales").fetchone()[0])  # type: ignore[index]
    print(json.dumps({"existe": present, "societes": companies, "ventes": sales}))


def cmd_license() -> None:
    """Ce que le résumé du support dit de la licence (lot 6) : des nombres et les codes
    d'offre (starter, business, premium), jamais un nom, un code de boutique ni une note."""
    result: dict[str, Any] = {"societes": 0, "etats": {}, "offres": [], "sans_fin": 0}
    if exists(MAIN):
        with connect(MAIN) as conn:
            table = conn.execute("SELECT to_regclass('public.subscriptions')").fetchone()
            if table and table[0]:
                rows = conn.execute(
                    "SELECT s.status::text, p.code, s.current_period_end IS NULL "
                    "FROM subscriptions s JOIN plans p ON p.id = s.plan_id"
                ).fetchall()
                result["societes"] = len(rows)
                states: dict[str, int] = {}
                for status, _code, _endless in rows:
                    states[status] = states.get(status, 0) + 1
                result["etats"] = dict(sorted(states.items()))
                result["offres"] = sorted({code for _status, code, _endless in rows})
                result["sans_fin"] = sum(
                    1 for status, _code, endless in rows if status == "active" and endless
                )
    print(json.dumps(result))


# ---------------------------------------------------------------------------- vérifier


def _acl_snapshot(dbname: str) -> dict[str, Any]:
    """Propriétaires et droits, pour comparer une base restaurée à une base de référence."""
    with connect(dbname) as conn:
        owner = conn.execute(
            "SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname = current_database()"
        ).fetchone()[0]  # type: ignore[index]
        schema = conn.execute(
            "SELECT pg_get_userbyid(nspowner), coalesce(nspacl::text, '') FROM pg_namespace "
            "WHERE nspname = 'public'"
        ).fetchone()
        tables = {
            name: [table_owner, acl, rls]
            for name, table_owner, acl, rls in conn.execute(
                "SELECT relname, pg_get_userbyid(relowner), coalesce(relacl::text, ''), "
                "relrowsecurity::text || relforcerowsecurity::text FROM pg_class "
                "WHERE relnamespace = 'public'::regnamespace AND relkind IN ('r', 'p', 'v', 'S')"
            )
        }
    return {"owner": owner, "schema": list(schema or []), "tables": tables}


def acl_differences(reference: dict[str, Any], restored: dict[str, Any]) -> list[str]:
    """Écarts de droits sur ce que les deux bases ont en commun (le reste suit les migrations)."""
    found = []
    if reference["owner"] != restored["owner"]:
        found.append(
            f"propriétaire de la base : {restored['owner']} (attendu {reference['owner']})"
        )
    if reference["schema"] != restored["schema"]:
        found.append("droits du schéma public différents")
    for name in sorted(set(reference["tables"]) & set(restored["tables"])):
        if reference["tables"][name] != restored["tables"][name]:
            found.append(f"droits de {name} différents")
    return found


def cmd_verify(name: str, manifest_path: Path) -> int:
    if not (SCRATCH.match(name) or name == MAIN):
        raise BaseError(f"« {name} » ne se vérifie pas par cette commande")
    manifest = verify_restore.Manifest(json.loads(manifest_path.read_text(encoding="utf-8")))
    code = verify_restore.verify(
        PsycopgDatabase(name),
        expected_revision=manifest.alembic_revision or verify_restore.head_revision(VERSIONS),
        today=datetime.now(UTC),
        manifest=manifest,
    )
    print("7. Propre au sur site")
    failures = 0
    db = PsycopgDatabase(name)
    # La clé COGES_MFA_ENCRYPTION_KEY ne chiffre que les secrets TOTP de l'administration,
    # absente du poste : une base restaurée ne doit en contenir aucun (sinon un coges.env
    # neuf la rendrait illisible).
    has_mfa = db.value(
        "SELECT count(*) FROM information_schema.columns "
        "WHERE table_name = 'platform_users' AND column_name = 'mfa_secret'"
    )
    mfa = (
        db.value("SELECT count(*) FROM platform_users WHERE mfa_secret IS NOT NULL")
        if has_mfa == "1"
        else "0"
    )
    ok = mfa == "0"
    failures += not ok
    print(
        f"  {'OK    ' if ok else 'ÉCHEC '}aucun secret chiffré par COGES_MFA_ENCRYPTION_KEY — {mfa}"
    )
    roles = db.value(
        "SELECT string_agg(r, ', ') FROM unnest(ARRAY['coges_owner','coges_app','coges_auth',"
        "'coges_relay',"
        "'coges_analytics','coges_bus','coges_ops','coges_backup','coges_app_platform','coges_billing',"
        "'coges_signup']) r WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r)"
    )
    failures += bool(roles)
    print(
        f"  {'ÉCHEC ' if roles else 'OK    '}rôles de postgres-init présents"
        + (f" — absents : {roles}" if roles else "")
    )
    if name != MAIN and exists(MAIN):
        reference, restored = _acl_snapshot(MAIN), _acl_snapshot(name)
        with connect(MAIN) as conn:
            current = conn.execute("SELECT to_regclass('public.alembic_version')").fetchone()
            same_revision = (
                bool(current and current[0])
                and (conn.execute("SELECT version_num FROM alembic_version").fetchone() or [None])[
                    0
                ]
                == manifest.alembic_revision
            )
        if not same_revision:
            # Révisions différentes : seuls le propriétaire et le schéma se comparent.
            reference["tables"], restored["tables"] = {}, {}
        gaps = acl_differences(reference, restored)
        failures += bool(gaps)
        print(
            f"  {'ÉCHEC ' if gaps else 'OK    '}mêmes propriétaires et droits que la base en place"
            + (" — " + "; ".join(gaps) if gaps else "")
        )
    if failures:
        print(f"Sur site : {failures} contrôle(s) en échec")
        return 1
    return code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    man = sub.add_parser("manifeste")
    man.add_argument("--sortie", type=Path, required=True)
    man.add_argument("--version", required=True)
    sub.add_parser("revisions")
    for command in ("preparer", "supprimer"):
        sub.add_parser(command).add_argument("nom")
    ver = sub.add_parser("verifier")
    ver.add_argument("nom")
    ver.add_argument("--manifeste", type=Path, required=True)
    for command in ("bascule", "retour"):
        sub.add_parser(command).add_argument("horodatage")
    sub.add_parser("bases")
    sub.add_parser("etat")
    sub.add_parser("copier").add_argument("horodatage")
    back = sub.add_parser("remettre")
    back.add_argument("horodatage")
    back.add_argument("--ecarter", required=True, choices=("echec", "apres"))
    sub.add_parser("copies")
    count = sub.add_parser("compter")
    count.add_argument("--depuis", default=None)
    sub.add_parser("licence")
    args = parser.parse_args(argv)
    try:
        if args.command == "manifeste":
            cmd_manifest(args.sortie, args.version)
        elif args.command == "revisions":
            cmd_revisions()
        elif args.command == "preparer":
            cmd_prepare(args.nom)
        elif args.command == "supprimer":
            cmd_drop(args.nom)
        elif args.command == "verifier":
            return cmd_verify(args.nom, args.manifeste)
        elif args.command == "bascule":
            cmd_switch(args.horodatage)
        elif args.command == "retour":
            cmd_back(args.horodatage)
        elif args.command == "bases":
            cmd_list()
        elif args.command == "copies":
            cmd_copies()
        elif args.command == "copier":
            cmd_copy(args.horodatage)
        elif args.command == "remettre":
            cmd_put_back(args.horodatage, args.ecarter)
        elif args.command == "compter":
            cmd_count(args.depuis)
        elif args.command == "licence":
            cmd_license()
        else:
            cmd_state()
    except (BaseError, psycopg.Error, OSError) as error:
        print(f"ÉCHEC — {str(error).strip()}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
