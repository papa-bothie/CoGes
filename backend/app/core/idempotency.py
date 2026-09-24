"""Clés d'idempotence des écritures financières — point ouvert P4.

La décision 16 de l'architecture exige des « clés d'idempotence sur les écritures
financières », et le Diagramme 5 en fait la **première** étape d'un paiement. Le
modèle de données ne portait ni table ni colonne pour cela : la révision 0009 crée
`idempotency_keys`, ce module s'en sert.

Ce qui est garanti, et par quoi :

* **un rejeu ne crée rien** — la clé est réservée *dans la transaction du cas
  d'usage*, donc validée par le même COMMIT que le paiement. Un rollback annule les
  deux : jamais de clé qui bloquerait une écriture qui n'a pas eu lieu ;
* **un rejeu rend la réponse initiale** — statut et corps sont enregistrés avant le
  COMMIT, et rejoués tels quels. Le client qui a perdu la réponse la retrouve, au
  lieu d'un conflit qu'il devrait interpréter ;
* **deux requêtes simultanées n'en font qu'une** — la seconde bloque sur
  `idempotency_keys_key_uq` jusqu'au COMMIT de la première, puis lit la réponse déjà
  écrite. Aucun verrou applicatif, aucun Redis ;
* **la même clé sur un corps différent est refusée** — `request_hash` compare les
  demandes. Rendre la première réponse à une seconde demande serait pire qu'un
  doublon : ce serait un mensonge.

Ce module est technique et transversal, donc dans `core/` aux côtés de `audit.py` et
`events/outbox.py` : il ne connaît aucun module métier, et aucun module ne le
contourne.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import timedelta
from typing import Annotated, Any

from fastapi import Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.sql import text

from app.core.errors import BusinessRuleError, ValidationFailedError
from app.core.tenancy import TenantContext

#: En-tête que le client pose sur toute écriture financière.
IDEMPOTENCY_HEADER = "Idempotency-Key"

#: Posé sur une réponse rejouée : le client sait qu'il relit, sans deviner.
REPLAY_HEADER = "Idempotent-Replay"

#: Bornes reprises du `CHECK` de la table : le schéma reste l'autorité, le schéma
#: d'entrée ne fait que donner au client un refus qui nomme le champ.
MIN_KEY_LENGTH = 8
MAX_KEY_LENGTH = 200

#: Durée de conservation. La purge viendra d'un job de la phase 08 ; en V1 rien
#: n'est effacé, et une clé gardée trop longtemps n'a jamais rendu une mauvaise
#: réponse — c'est l'inverse qui serait dangereux.
RETENTION = timedelta(hours=24)


class IdempotencyKeyRequiredError(ValidationFailedError):
    code = "idempotency_key_required"
    default_message = (
        f"L'en-tête {IDEMPOTENCY_HEADER} est obligatoire sur les écritures financières."
    )


class IdempotencyKeyMalformedError(ValidationFailedError):
    code = "idempotency_key_malformed"
    default_message = (
        f"L'en-tête {IDEMPOTENCY_HEADER} doit compter entre "
        f"{MIN_KEY_LENGTH} et {MAX_KEY_LENGTH} caractères."
    )


class IdempotencyKeyReusedError(ValidationFailedError):
    """Même clé, autre demande. 422 : c'est la requête qui se contredit."""

    code = "idempotency_key_reused"
    default_message = (
        "Cette clé d'idempotence a déjà servi pour une demande différente. "
        "Utilisez une nouvelle clé."
    )


class IdempotencyInProgressError(BusinessRuleError):
    """Clé réservée, réponse jamais enregistrée.

    Inatteignable en régime normal : la réservation et l'enregistrement de la
    réponse partagent une transaction, donc un COMMIT ne laisse jamais
    `response_status` nul. Reste pour qu'une anomalie se voie plutôt que de
    ressortir en 500.
    """

    code = "idempotency_key_in_progress"
    default_message = "Une requête portant cette clé est encore en cours de traitement."


@dataclass(frozen=True, slots=True)
class Replay:
    """Réponse déjà rendue à cette clé, à restituer telle quelle."""

    status_code: int
    body: dict[str, Any]


_RESERVE = text(
    """
    INSERT INTO idempotency_keys
        (company_id, key, endpoint, request_hash, expires_at)
    VALUES (:company_id, :key, :endpoint, :request_hash, now() + :retention)
    """
)

_READ = text(
    """
    SELECT request_hash, response_status, response_body
      FROM idempotency_keys
     WHERE company_id = :company_id AND key = :key
    """
)

_RECORD = text(
    """
    UPDATE idempotency_keys
       SET response_status = :status_code,
           response_body   = CAST(:body AS jsonb)
     WHERE company_id = :company_id AND key = :key
    """
)


def digest(endpoint: str, payload: BaseModel | None) -> str:
    """Empreinte stable d'une demande : endpoint + corps en JSON canonique.

    Le corps **validé** est haché, pas les octets reçus : deux requêtes qui ne
    diffèrent que par l'ordre des clés ou l'indentation sont la même demande, et
    doivent se rejouer l'une l'autre.
    """
    body = payload.model_dump(mode="json") if payload is not None else {}
    canonical = json.dumps(body, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(f"{endpoint}\n{canonical}".encode()).hexdigest()


def reserve(
    session: Session,
    ctx: TenantContext,
    *,
    key: str,
    endpoint: str,
    payload: BaseModel | None = None,
) -> Replay | None:
    """Réserve la clé, ou rend la réponse déjà enregistrée pour elle.

    `None` signifie « clé neuve » : à l'appelant d'exécuter l'écriture, puis
    d'appeler `record`.

    L'INSERT est tenté sous un **SAVEPOINT**. Sans lui, la violation d'unicité
    tuerait la transaction du cas d'usage et il n'y aurait plus personne pour lire
    la réponse à rejouer — c'est la leçon de l'ADR 0010, appliquée à un conflit
    qu'on sait à l'avance possible.
    """
    request_hash = digest(endpoint, payload)
    try:
        with session.begin_nested():
            session.execute(
                _RESERVE,
                {
                    "company_id": ctx.company_id,
                    "key": key,
                    "endpoint": endpoint,
                    "request_hash": request_hash,
                    "retention": RETENTION,
                },
            )
    except IntegrityError:
        # Le SAVEPOINT est annulé, la transaction reste vivante. Si une requête
        # concurrente tenait la clé, l'INSERT a attendu son COMMIT : la ligne lue
        # ici porte donc déjà sa réponse.
        return _replay_of(session, ctx, key=key, request_hash=request_hash)
    return None


def _replay_of(session: Session, ctx: TenantContext, *, key: str, request_hash: str) -> Replay:
    row = session.execute(_READ, {"company_id": ctx.company_id, "key": key}).one_or_none()
    if row is None:
        # PostgreSQL ne lève la violation d'unicité que si la transaction
        # concurrente a **commité** — si elle avait échoué, notre INSERT aurait
        # abouti. Une ligne absente ici ne peut donc venir que d'une purge
        # survenue entre les deux, ce que la V1 ne fait pas. Réclamer une clé
        # neuve est la seule réponse qui ne risque pas un doublon.
        raise IdempotencyKeyReusedError()
    if row.request_hash != request_hash:
        raise IdempotencyKeyReusedError(details={"endpoint_key": key})
    if row.response_status is None:
        raise IdempotencyInProgressError()
    return Replay(status_code=int(row.response_status), body=dict(row.response_body or {}))


def record(
    session: Session,
    ctx: TenantContext,
    *,
    key: str,
    status_code: int,
    body: dict[str, Any],
) -> None:
    """Enregistre la réponse rendue, **avant** le COMMIT du cas d'usage."""
    session.execute(
        _RECORD,
        {
            "company_id": ctx.company_id,
            "key": key,
            "status_code": status_code,
            "body": json.dumps(body, ensure_ascii=False, default=str),
        },
    )


def replay_response(replay: Replay) -> JSONResponse:
    """Rend la réponse initiale, à l'octet près, avec un en-tête qui le dit."""
    return JSONResponse(
        status_code=replay.status_code,
        content=replay.body,
        headers={REPLAY_HEADER: "true"},
    )


def completed(
    session: Session,
    ctx: TenantContext,
    *,
    key: str,
    status_code: int,
    model: BaseModel,
) -> JSONResponse:
    """Enregistre la réponse et la rend.

    La réponse fraîche est construite **par le même chemin** que le rejeu : les deux
    sortent du même `JSONResponse` sur le même dictionnaire. Sans cela, « la même
    réponse » resterait une intention, et un test ne pourrait comparer que des
    formes voisines.
    """
    body = model.model_dump(mode="json")
    record(session, ctx, key=key, status_code=status_code, body=body)
    return JSONResponse(status_code=status_code, content=body)


def idempotency_key(request: Request) -> str:
    """Dépendance FastAPI : exige et valide l'en-tête, sans toucher à la base.

    À déclarer **après** la dépendance de permission dans la signature d'une route :
    FastAPI résout les dépendances dans l'ordre des paramètres, et une requête sans
    jeton doit ressortir en 401, jamais en 422 sur un en-tête manquant.
    """
    raw = request.headers.get(IDEMPOTENCY_HEADER)
    if raw is None:
        raise IdempotencyKeyRequiredError()
    key = raw.strip()
    if not MIN_KEY_LENGTH <= len(key) <= MAX_KEY_LENGTH:
        raise IdempotencyKeyMalformedError()
    return key


#: À poser sur toute route qui écrit de l'argent.
IdempotencyKey = Annotated[str, Depends(idempotency_key)]
