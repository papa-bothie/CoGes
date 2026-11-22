#!/usr/bin/env bash
# Vérification de bout en bout des mises à jour sur site (ADR 0128), sur Linux, par le vrai
# script Windows sous pwsh : c'est ce que joue le workflow « Sur site » après verifier.sh.
#
#   deploy/onprem-ci/verifier-mises-a-jour.sh
#
# Un registre local (registry:2) reçoit trois versions faites des images construites avant :
#   v0.90.1 (installée), v0.90.2 (une couche LABEL de plus : d'autres digests), et v0.90.3
#   dont l'image worker porte une migration qui échoue exprès. Les canaux sont écrits par
#   deploy/onprem/canal/publier.py, comme chez CoGes. Puis :
#   c. canal faux (étiquette déplacée, empreinte du programme fausse) : refus, rien changé ;
#   a. v0.90.1 → v0.90.2 : données identiques, version lue ;
#   d. vente faite en v0.90.2, RevenirVersionPrecedente : vente annoncée perdue, sauvegardée
#      d'abord, retour à v0.90.1 ;
#   b. v0.90.1 → v0.90.3 (migration cassée) : retour automatique, données identiques,
#      ancienne version qui répond.
#
# Variables : ONPREM_REGISTRY, ONPREM_TAG (images construites avant, défaut coges-ci/…:ci),
# ONPREM_PORT (défaut 80), ONPREM_REGISTRY_PORT (défaut 5000), ONPREM_PWSH, ONPREM_KEEP=1,
# ONPREM_SKIP_BROWSER=1 (sans la vente du scénario d).
set -euo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
onprem="$root/deploy/onprem"
ci="$root/deploy/onprem-ci"
source_registry=${ONPREM_REGISTRY:-coges-ci}
source_tag=${ONPREM_TAG:-ci}
port=${ONPREM_PORT:-80}
if [ "$port" = 80 ]; then url=http://localhost; else url="http://localhost:$port"; fi
registry_port=${ONPREM_REGISTRY_PORT:-5000}
registry="localhost:$registry_port/coges"
registry_name=coges-registre-essai
pwsh_bin=${ONPREM_PWSH:-pwsh}
A=v0.90.1
B=v0.90.2
C=v0.90.3
slug=boutique-maj
email=gerant@maj.example
ONPREM_PASSWORD=$(python3 -c 'import secrets; print(secrets.token_hex(12))')
export ONPREM_PASSWORD

work=$(mktemp -d)
racine="$work/racine"
settings="$racine/reglages"
env_file="$settings/coges.env"
mkdir -p "$settings" "$work/archives" "$work/canal" "$work/canal-faux" "$work/canal-casse" "$work/bureau"

dc() { docker compose --env-file "$env_file" -f "$racine/programme/docker-compose.yml" "$@"; }
title() { printf '\n=== %s ===\n' "$*"; }
fail() { printf 'ÉCHEC — %s\n' "$*" >&2; exit 1; }
# Le vrai script, tel qu'installé sur le PC ; les essais lisent le canal et les archives ici.
coges_ps() {
  COGES_CANAL_ESSAI="${CANAL:-$work/canal}" COGES_ARCHIVE_ESSAI="$work/archives" COGES_BUREAU_ESSAI="$work/bureau" \
    COGES_PLACE_MIN_ESSAI="${ONPREM_PLACE_MIN:-}" \
    "$pwsh_bin" -NoProfile -File "$racine/programme/windows/installer.ps1" -Racine "$racine" -NonInteractif -SansNotification "$@"
}

cleanup() {
  status=$?
  if [ -n "${pings_pid:-}" ]; then kill "$pings_pid" 2>/dev/null || true; fi
  if [ "$status" -ne 0 ]; then
    title "État au moment de l'échec"
    dc ps -a || true
    dc logs --tail 30 api worker migrate 2>&1 | tail -80 || true
    find "$racine/journaux" -name 'mise-a-jour-*.log' -exec tail -40 {} + 2>/dev/null || true
  fi
  if [ "${ONPREM_KEEP:-}" != 1 ]; then
    dc --profile tools down -v --remove-orphans >/dev/null 2>&1 || true
    docker rm -f "$registry_name" >/dev/null 2>&1 || true
    docker volume rm coges-registre-essai >/dev/null 2>&1 || true
    docker image ls --format '{{.Repository}}:{{.Tag}}' | grep "^$registry/" | xargs -r docker image rm >/dev/null 2>&1 || true
    rm -rf "$work"
  else
    echo "Pile gardée. Racine : $racine"
  fi
  exit "$status"
}
trap cleanup EXIT

http_code() { curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$1" || true; }
wait_for_code() {
  local deadline=$((SECONDS + $3)) code=
  while [ "$SECONDS" -lt "$deadline" ]; do
    code=$(http_code "$1")
    [ "$code" = "$2" ] && return 0
    sleep 3
  done
  fail "$1 répond $code, $2 attendu"
}
table_counts() {
  dc exec -T postgres psql -U postgres -d coges -XAt -c "
    SELECT 'companies', count(*) FROM companies UNION ALL SELECT 'users', count(*) FROM users
    UNION ALL SELECT 'sales', count(*) FROM sales UNION ALL SELECT 'payments', count(*) FROM payments
    UNION ALL SELECT 'products', count(*) FROM products UNION ALL SELECT 'subscriptions', count(*) FROM subscriptions"
}
running_tag() { docker inspect -f '{{.Config.Image}}' "$(dc ps -q api)" | sed 's/.*://'; }
env_tag() { sed -n 's/^COGES_IMAGE_TAG=//p' "$env_file"; }

command -v "$pwsh_bin" >/dev/null || fail "PowerShell 7 introuvable ($pwsh_bin)"
free_gb=$(df -Pk "$work" | awk 'NR == 2 { print int($4 / 1048576) }')
[ "$free_gb" -ge 3 ] || fail "moins de 3 Go libres ($free_gb) : l'essai remplirait le disque"

# ------------------------------------------------------------------------------------
title "Registre local et trois versions ($A, $B, $C cassée)"
docker rm -f "$registry_name" >/dev/null 2>&1 || true
docker run -d --name "$registry_name" -p "127.0.0.1:$registry_port:5000" -v coges-registre-essai:/var/lib/registry registry:2.8.3 >/dev/null
for _ in $(seq 1 30); do [ "$(http_code "http://localhost:$registry_port/v2/")" = 200 ] && break; sleep 1; done
for image in front api worker; do
  docker tag "$source_registry/$image:$source_tag" "$registry/$image:$A"
  docker push --quiet "$registry/$image:$A" >/dev/null
  # B : même code, une étiquette de plus dans la configuration, donc d'autres digests.
  printf 'FROM %s\nLABEL coges.essai="%s"\n' "$registry/$image:$A" "$B" | docker build --quiet -t "$registry/$image:$B" - >/dev/null
  docker push --quiet "$registry/$image:$B" >/dev/null
done
# C : front et api de B ; worker avec une migration qui échoue exprès, en tête de la chaîne.
head=$(docker run --rm --network none -v "$onprem/sauvegarde:/srv/onprem/sauvegarde:ro" --entrypoint python \
  "$registry/worker:$A" -I /srv/onprem/sauvegarde/base.py revisions | python3 -c 'import json,sys; print(json.load(sys.stdin)["tete"])')
mkdir -p "$work/casse"
cat > "$work/casse/9999_casse.py" <<PY
"""Migration qui échoue exprès (essai du retour arrière automatique, ADR 0128)."""

revision = "9999_casse"
down_revision = "$head"
branch_labels = None
depends_on = None


def upgrade() -> None:
    raise RuntimeError("migration cassée exprès (essai du retour arrière)")


def downgrade() -> None:
    pass
PY
printf 'FROM %s\nCOPY 9999_casse.py /srv/coges/migrations/versions/9999_casse.py\n' "$registry/worker:$B" \
  | docker build --quiet -t "$registry/worker:$C" -f - "$work/casse" >/dev/null
for image in front api; do docker tag "$registry/$image:$B" "$registry/$image:$C"; done
for image in front api worker; do docker push --quiet "$registry/$image:$C" >/dev/null; done
# Le PC n'a que A : B et C se tireront du registre, par digest.
for image in front api worker; do docker image rm "$registry/$image:$B" "$registry/$image:$C" >/dev/null; done
echo "OK — tête des migrations : $head ; $C ajoute 9999_casse."

title "Archives des étiquettes (format de GitHub) et canaux écrits par publier.py"
python3 - "$onprem" "$work/archives" "$A" "$B" "$C" <<'PY'
import sys, zipfile
from pathlib import Path
onprem, folder, *versions = sys.argv[1:]
for version in versions:
    with zipfile.ZipFile(Path(folder) / f"{version}.zip", "w", zipfile.ZIP_DEFLATED) as zipped:
        for file in sorted(Path(onprem).rglob("*")):
            relative = file.relative_to(onprem).as_posix()
            if file.is_file() and "__pycache__" not in relative:
                # Droits d'une archive de GitHub (0644, 0755 pour un exécutable) : writestr
                # mettrait 0600, illisible par le conteneur de PostgreSQL.
                info = zipfile.ZipInfo(f"CoGes-{version[1:]}/deploy/onprem/{relative}", (2026, 11, 21, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = ((0o100755 if file.stat().st_mode & 0o111 else 0o100644) << 16)
                zipped.writestr(info, file.read_bytes())
PY
publish() { # version, canal, dossier, version minimale
  python3 "$onprem/canal/publier.py" --version "$1" --canal "$2" --depuis-minimum "$4" --note "Essai de $1." \
    --registre "$registry" --archive "$work/archives/$1.zip" --sortie "$3/$2.json"
}
publish "$B" test "$work/canal" "$A"
publish "$C" test "$work/canal-casse" "$A"
cat "$work/canal/test.json"

title "Installation de $A (programme posé par le script, réglages, base, société, licence)"
"$pwsh_bin" -NoProfile -Command ". '$onprem/windows/CoGes.Install.ps1'; [void](Install-Programme -Archive '$work/archives/$A.zip' -Racine '$racine' -Version '$A')"
python3 - "$racine/programme/coges.env.example" "$env_file" "$registry" "$A" "$port" "$url" <<'PY'
import base64, re, secrets, sys
model, target, registry, tag, port, url = sys.argv[1:]
values = {"COGES_IMAGE_TAG": tag, "COGES_IMAGE_REGISTRY": registry, "COGES_HTTP_PORT": port, "COGES_PUBLIC_URL": url,
          "COGES_MFA_ENCRYPTION_KEY": base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")}
lines = []
for line in open(model, encoding="utf-8").read().splitlines():
    match = re.fullmatch(r"([A-Z_]+)=(.*)", line)
    if match:
        line = f"{match.group(1)}={values.get(match.group(1)) or match.group(2) or secrets.token_hex(32)}"
    lines.append(line)
open(target, "w", encoding="utf-8", newline="\n").write("\n".join(lines) + "\n")
PY
printf '{ "canal": "test", "automatique": true, "heure": "21:30" }\n' > "$settings/mise-a-jour.json"
python3 "$onprem/check_onprem_env.py" --env-file "$env_file"
dc --profile tools run --rm migrate > "$work/migrate-a.log" 2>&1 || { tail -25 "$work/migrate-a.log"; fail "migrations de $A"; }
dc up -d --wait --wait-timeout 300
dc --profile tools run --rm -T cli create-company --name "Boutique Maj" --slug "$slug" \
  --manager-email "$email" --manager-name "Awa Maj" --password "$ONPREM_PASSWORD" >/dev/null
dc --profile tools run --rm -T cli activate-license --slug "$slug" --plan business --note "Essai des mises à jour" >/dev/null
# Clé publique de sauvegarde (la mise à jour sauvegarde d'abord).
mkdir -p "$work/cles"
docker run --rm --network none --user "$(id -u):$(id -g)" -v "$onprem/sauvegarde:/srv/onprem/sauvegarde:ro" \
  -v "$work/cles:/cles" --entrypoint python "$registry/worker:$A" -I \
  /srv/onprem/sauvegarde/coffre.py paire --prive /cles/maj.cle --publique /cles/maj.pub
"$pwsh_bin" -NoProfile -Command ". '$onprem/windows/CoGes.Install.ps1'; \$script:CogesState.NonInteractif = \$true;
  Set-CogesBackupKey -Paths (Get-CogesPath '$racine') -Options @{ ClePublique = '$work/cles/maj.pub' } -Slug '$slug'" >/dev/null
# Support à distance (lot 6, ADR 0129) : un faux service de pings reçoit les signaux « mise-a-jour ».
pings="$work/pings"
pings_port=$(python3 -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()')
python3 "$ci/controle_remontee.py" serveur --port "$pings_port" --dossier "$pings" 2>"$work/pings.log" &
pings_pid=$!
python3 - "$work/support.json" "http://127.0.0.1:$pings_port/ping" <<'PY'
import json, secrets, sys
json.dump({"adresses": {s: f"{sys.argv[2]}/{s}-{secrets.token_hex(12)}" for s in ("vie", "sauvegarde", "mise-a-jour")}},
          open(sys.argv[1], "w", encoding="utf-8"))
PY
coges_ps -Action ConfigurerSupport -Support "$work/support.json" >/dev/null
wait_for_code "$url/" 200 60
if [ "${ONPREM_SKIP_BROWSER:-}" != 1 ]; then
  ONPREM_URL="$url" ONPREM_SLUG="$slug" ONPREM_EMAIL="$email" ONPREM_SCREENSHOT="$work/echec-a.png" node "$ci/parcours.mjs" >/dev/null
fi
[ "$(running_tag)" = "$A" ] || fail "version en cours : $(running_tag)"
echo "OK — $A en marche, $(table_counts | tr '\n' ' ')"

# ------------------------------------------------------------------------------------
title "c. Canal faux : étiquette déplacée, puis empreinte du programme fausse : refus, rien changé"
before=$(table_counts)
python3 - "$work/canal/test.json" "$work/canal-faux/test.json" <<'PY'
import json, sys
data = json.load(open(sys.argv[1], encoding="utf-8"))
# Le digest de l'API annoncé n'est plus celui de l'étiquette sur le registre.
data["images"]["api"] = "sha256:" + "0" * 64
json.dump(data, open(sys.argv[2], "w", encoding="utf-8"), indent=2)
PY
if CANAL="$work/canal-faux" coges_ps -Action VerifierMiseAJour > "$work/faux-1.txt" 2>&1; then fail "canal à digest faux accepté"; fi
grep -q "ne pointe plus vers le digest du canal" "$work/faux-1.txt" || fail "message : $(cat "$work/faux-1.txt")"
python3 - "$work/canal/test.json" "$work/canal-faux/test.json" <<'PY'
import json, sys
data = json.load(open(sys.argv[1], encoding="utf-8"))
data["programme"]["sha256"] = "f" * 64
json.dump(data, open(sys.argv[2], "w", encoding="utf-8"), indent=2)
PY
if CANAL="$work/canal-faux" coges_ps -Action VerifierMiseAJour > "$work/faux-2.txt" 2>&1; then fail "canal à empreinte fausse accepté"; fi
grep -q "empreinte du programme" "$work/faux-2.txt" || fail "message : $(cat "$work/faux-2.txt")"
printf '{"format": "COGES-CANAL-1"}' > "$work/canal-faux/test.json"
if CANAL="$work/canal-faux" coges_ps -Action VerifierMiseAJour > "$work/faux-3.txt" 2>&1; then fail "canal incomplet accepté"; fi
grep -q "Canal illisible" "$work/faux-3.txt" || fail "message : $(cat "$work/faux-3.txt")"
[ "$(env_tag)" = "$A" ] && [ "$(running_tag)" = "$A" ] || fail "la version a changé"
[ "$(table_counts)" = "$before" ] || fail "données changées"
for image in front api worker; do
  if docker image inspect "$registry/$image:$B" >/dev/null 2>&1; then fail "l'image $image de $B a été tirée malgré le refus"; fi
done
echo "OK — trois refus clairs, $A toujours en marche, rien tiré."

title "a. $A → $B : téléchargé pendant que CoGes tourne, puis appliqué"
start=$SECONDS
coges_ps -Action VerifierMiseAJour | tee "$work/verif-b.txt"
download_seconds=$((SECONDS - start))
grep -q "$B prête à appliquer" "$work/verif-b.txt" || fail "$B pas prête"
[ "$(running_tag)" = "$A" ] || fail "le téléchargement a changé la version en cours"
wait_for_code "$url/api/v1/health/ready" 200 10
before=$(table_counts)
start=$SECONDS
coges_ps -Action MettreAJour -Maintenant | tee "$work/maj-b.txt"
update_seconds=$((SECONDS - start))
[ "$(env_tag)" = "$B" ] || fail "COGES_IMAGE_TAG vaut $(env_tag)"
[ "$(running_tag)" = "$B" ] || fail "version en cours : $(running_tag)"
[ "$(cat "$racine/programme/.version")" = "$B" ] || fail "programme : $(cat "$racine/programme/.version")"
[ "$(cat "$racine/programme.precedent/.version")" = "$A" ] || fail "ancien programme non gardé"
[ "$(table_counts)" = "$before" ] || fail "données différentes : $before / $(table_counts)"
copy=$(dc exec -T postgres psql -U postgres -XAt -c "SELECT datname FROM pg_database WHERE datname LIKE 'coges_avant_maj_%'")
[ -n "$copy" ] || fail "copie de la base absente"
ls "$racine/sauvegardes/"*-avant-maj.coges >/dev/null || fail "sauvegarde -avant-maj absente"
wait_for_code "$url/api/v1/health/ready" 200 60
wait_for_code "$url/api/v1/platform/" 404 10
coges_ps -Action Etat -CodeBoutique "$slug" | tee "$work/etat-b.txt"
grep -q "$A → $B.*réussie" "$work/etat-b.txt" || fail "Etat ne dit pas la mise à jour réussie"
grep -q "Copie gardée" "$work/etat-b.txt" || fail "Etat ne dit pas la copie gardée"
python3 "$ci/controle_remontee.py" corps "$pings" --attendu mise-a-jour:aucune
echo "OK — $B en marche, données identiques ; téléchargement ${download_seconds} s, application ${update_seconds} s."

title "d. Une vente en $B, puis RevenirVersionPrecedente : vente annoncée perdue, sauvegardée d'abord"
if [ "${ONPREM_SKIP_BROWSER:-}" != 1 ]; then
  ONPREM_URL="$url" ONPREM_SLUG="$slug" ONPREM_EMAIL="$email" ONPREM_SCREENSHOT="$work/echec-d.png" node "$ci/parcours.mjs" >/dev/null
  lost=1
else
  lost=0
fi
if coges_ps -Action RevenirVersionPrecedente -CodeBoutique "$slug" > "$work/retour-1.txt" 2>&1; then fail "retour sans REVENIR accepté"; fi
if [ "$lost" = 1 ]; then grep -q "1 VENTE(S) FAITE(S) DEPUIS SERAIENT PERDUES" "$work/retour-1.txt" || fail "vente perdue non annoncée : $(cat "$work/retour-1.txt")"; fi
grep -q "REVENIR" "$work/retour-1.txt" || fail "REVENIR non demandé"
ls "$racine/sauvegardes/"*-avant-retour.coges >/dev/null || fail "pas de sauvegarde avant le retour"
[ "$(running_tag)" = "$B" ] || fail "le refus a changé la version"
start=$SECONDS
coges_ps -Action RevenirVersionPrecedente -ConfirmerRetour -CodeBoutique "$slug" | tee "$work/retour-2.txt"
back_seconds=$((SECONDS - start))
[ "$(env_tag)" = "$A" ] && [ "$(running_tag)" = "$A" ] || fail "pas revenu à $A"
[ "$(table_counts)" = "$before" ] || fail "la base n'est pas celle d'avant la mise à jour"
wait_for_code "$url/api/v1/health/ready" 200 60
grep -q '"etat": *"annulee"' "$racine/mises-a-jour/etat.json" || fail "$B pas marquée annulée"
echo "OK — revenu à $A en ${back_seconds} s ; $lost vente(s) perdue(s), gardée(s) dans la sauvegarde -avant-retour."

title "b. $A → $C (migration cassée) : retour automatique, données identiques"
CANAL="$work/canal-casse" coges_ps -Action VerifierMiseAJour | tee "$work/verif-c.txt"
grep -q "$C prête à appliquer" "$work/verif-c.txt" || fail "$C pas prête"
before=$(table_counts)
start=$SECONDS
if CANAL="$work/canal-casse" coges_ps -Action MettreAJour -Maintenant > "$work/maj-c.txt" 2>&1; then fail "la mise à jour cassée a réussi"; fi
rollback_seconds=$((SECONDS - start))
cat "$work/maj-c.txt"
grep -q "La mise à jour vers $C a échoué ; CoGes est revenu à $A. Rien n'est perdu." "$work/maj-c.txt" || fail "message du retour"
[ "$(env_tag)" = "$A" ] && [ "$(running_tag)" = "$A" ] || fail "version après le retour : $(env_tag) / $(running_tag)"
[ "$(cat "$racine/programme/.version")" = "$A" ] || fail "programme après le retour"
[ "$(table_counts)" = "$before" ] || fail "données différentes après le retour"
wait_for_code "$url/" 200 60
wait_for_code "$url/api/v1/health/ready" 200 60
python3 "$ci/controle_donnees.py" --url "$url" --slug "$slug" --email "$email" --min-sales 0
failed=$(dc exec -T postgres psql -U postgres -XAt -c "SELECT datname FROM pg_database WHERE datname LIKE 'coges_echec_maj_%'")
[ -n "$failed" ] || fail "base en échec non gardée"
grep -q '"etat": *"echec"' "$racine/mises-a-jour/etat.json" || fail "$C pas marquée en échec"
python3 "$ci/controle_remontee.py" corps "$pings" --attendu mise-a-jour:aucune --attendu mise-a-jour-fail:retour-arriere
echo "Corps reçu pour le retour arrière :"
cat "$(find "$pings" -name '*-mise-a-jour-fail.txt' | sort | tail -1)"
# Une version en échec ne se reprend pas seule.
CANAL="$work/canal-casse" coges_ps -Action VerifierMiseAJour | tee "$work/verif-c2.txt"
grep -q "ne s'applique plus seule" "$work/verif-c2.txt" || fail "$C serait reprise seule"
[ -z "$(find "$racine/journaux" -type f -exec grep -lF -- "$(sed -n 's/^COGES_APP_PASSWORD=//p' "$env_file")" {} +)" ] || fail "un mot de passe est dans un journal"
echo "OK — retour automatique en ${rollback_seconds} s ; base en échec gardée ($failed)."

title "Mises à jour sur site vérifiées"
echo "téléchargement ${download_seconds} s, application ${update_seconds} s, retour à la main ${back_seconds} s, retour automatique ${rollback_seconds} s"
