"""Support à distance sur site (lot 6, ADR 0129) : ce que la CI vérifie de ce qui sort du PC.

    python3 controle_remontee.py serveur --port P --dossier D     faux service de pings (127.0.0.1)
    python3 controle_remontee.py corps D [--attendu SIGNAL[-fail][:RAISON]]…
    python3 controle_remontee.py zip FICHIER --env coges.env [--interdit MOT]…

`serveur` répond 200 à tout POST et range chaque corps dans D (`0001-vie.txt`,
`0002-sauvegarde-fail.txt`…) : il joue Healthchecks.io dans le job, sans Internet.
`corps` relit TOUS les corps reçus avec la liste fermée (deploy/onprem/support/champs.txt) :
un champ en plus, en moins, ou une valeur hors de sa règle échoue ; `--attendu` exige qu'un
envoi de ce signal (et de ce résultat, et de cette raison) ait été reçu.
`zip` fouille le diagnostic : aucune valeur de coges.env, aucun mot interdit (noms de la démo).
Bibliothèque standard seulement.
"""

from __future__ import annotations

import argparse
import re
import sys
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

FIELDS_FILE = Path(__file__).resolve().parents[1] / "onprem" / "support" / "champs.txt"
#: Les signaux et leurs adresses dans le faux service : /<signal>-<jeton>[/fail].
SECRET_NAME = re.compile(r"^COGES_[A-Z_]*(PASSWORD|SECRET|_KEY)$")
PATH_RULE = re.compile(
    r"^/(?:[\w.-]+/)*(?P<signal>vie|sauvegarde|mise-a-jour)-[\w-]+(?P<fail>/fail)?$"
)


def load_fields(path: Path = FIELDS_FILE) -> list[tuple[str, re.Pattern[str]]]:
    """Les champs de la liste, dans l'ordre, avec leur règle ancrée (même lecture que le script)."""
    fields = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        parts = line.split(" | ", 2)
        if len(parts) != 3:
            raise ValueError(f"champs.txt : ligne illisible {line!r}")
        fields.append((parts[0].strip(), re.compile(rf"^(?:{parts[1].strip()})$")))
    return fields


def check_body(text: str, fields: list[tuple[str, re.Pattern[str]]]) -> dict[str, str]:
    """Un corps reçu : exactement les champs de la liste, dans l'ordre, valeurs dans leur règle."""
    lines = text.rstrip("\n").split("\n")
    names = [name for name, _ in fields]
    seen = []
    values: dict[str, str] = {}
    for line in lines:
        name, sep, value = line.partition(": ")
        if not sep:
            raise ValueError(f"ligne sans « nom: valeur » : {line!r}")
        if name not in names:
            raise ValueError(f"champ hors de la liste : {name}")
        rule = dict(fields)[name]
        if not rule.match(value):
            raise ValueError(f"valeur hors de sa règle pour {name}")
        seen.append(name)
        values[name] = value
    if seen != names:
        raise ValueError(f"champs reçus {seen} au lieu de {names}")
    if len(text.encode("utf-8")) > 2048:
        raise ValueError("corps de plus de 2 Ko")
    return values


def serve(port: int, folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    counter = {"n": len(list(folder.glob("*.txt")))}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802 (nom imposé par http.server)
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length).decode("utf-8", "replace")
            match = PATH_RULE.match(self.path)
            name = "inconnu"
            if match:
                name = match["signal"] + ("-fail" if match["fail"] else "")
            counter["n"] += 1
            (folder / f"{counter['n']:04d}-{name}.txt").write_text(body, encoding="utf-8")
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"OK")

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            sys.stderr.write("faux pings : " + (format % args) + "\n")

    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


def check_folder(folder: Path, expected: list[str]) -> int:
    fields = load_fields()
    received: list[tuple[str, dict[str, str]]] = []
    for file in sorted(folder.glob("*.txt")):
        kind = file.stem.split("-", 1)[1]
        if kind == "inconnu":
            print(f"ÉCHEC — {file.name} : adresse inattendue")
            return 1
        try:
            values = check_body(file.read_text(encoding="utf-8"), fields)
        except ValueError as error:
            print(f"ÉCHEC — {file.name} : {error}")
            return 1
        received.append((kind, values))
    for wanted in expected:
        signal, _, reason = wanted.partition(":")
        # Le signal du corps doit être le même que celui de l'adresse (un « test » ne compte pas).
        hits = [
            values
            for kind, values in received
            if kind == signal
            and values["signal"] == signal.removesuffix("-fail")
            and values["resultat"] == ("echec" if signal.endswith("-fail") else "ok")
            and (not reason or values["raison"] == reason)
        ]
        if not hits:
            print(f"ÉCHEC — aucun envoi {wanted} parmi {[kind for kind, _ in received]}")
            return 1
    wanted = ", ".join(expected) or "—"
    print(f"OK — {len(received)} envoi(s), tous dans la liste fermée ; attendus : {wanted}")
    return 0


def check_zip(path: Path, env_file: Path, forbidden: list[str]) -> int:
    # Les secrets de coges.env (mots de passe, secret JWT, clé MFA) ; l'adresse, le port, le
    # registre et la version ne sont pas des secrets : Etat les montre exprès.
    secrets = []
    for line in env_file.read_text(encoding="utf-8").splitlines():
        name, sep, value = line.partition("=")
        if sep and SECRET_NAME.search(name) and len(value.strip()) >= 8:
            secrets.append(value.strip())
    words = [w for w in forbidden if w]
    problems = []
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            text = archive.read(info).decode("utf-8", "replace")
            problems += [f"{info.filename} : une valeur de coges.env" for s in secrets if s in text]
            problems += [f"{info.filename} : « {w} »" for w in words if w in text]
        names = archive.namelist()
    size = path.stat().st_size
    if size > 10 * 1024 * 1024:
        problems.append(f"{size} octets (plus de 10 Mo)")
    for wanted in ("etat.txt", "resume.txt", "docker.txt", "reglages.txt", "sauvegardes.txt"):
        if wanted not in names:
            problems.append(f"{wanted} absent")
    if problems:
        print("ÉCHEC — " + " ; ".join(sorted(set(problems))))
        return 1
    print(
        f"OK — {path.name} : {len(names)} fichiers, {size} octets ; "
        f"{len(secrets)} valeurs de coges.env et {len(words)} mots de la démo absents."
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    server = sub.add_parser("serveur")
    server.add_argument("--port", type=int, required=True)
    server.add_argument("--dossier", type=Path, required=True)
    bodies = sub.add_parser("corps")
    bodies.add_argument("dossier", type=Path)
    bodies.add_argument("--attendu", action="append", default=[])
    archive = sub.add_parser("zip")
    archive.add_argument("fichier", type=Path)
    archive.add_argument("--env", type=Path, required=True)
    archive.add_argument("--interdit", action="append", default=[])
    args = parser.parse_args(argv)
    if args.command == "serveur":
        serve(args.port, args.dossier)
        return 0
    if args.command == "corps":
        return check_folder(args.dossier, args.attendu)
    return check_zip(args.fichier, args.env, args.interdit)


if __name__ == "__main__":
    sys.exit(main())
