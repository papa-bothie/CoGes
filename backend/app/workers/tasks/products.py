"""Photos des articles chez Cloudinary (ADR 0121) : suppression et balayage de nuit.

L'API dépose l'image dans la requête ; tout ce qui **supprime** passe par ici, après le
COMMIT : une image retirée, remplacée, ou celle d'un article supprimé. Avec nouvelles
tentatives : Cloudinary injoignable un moment ne laisse pas d'image derrière. Ce qui
échappe malgré tout (Redis absent à l'enfilement, worker tué) est retrouvé chaque nuit
par le balayage : toute image du dossier de l'entreprise qu'aucun article ne nomme.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.core import cloudinary
from app.core.tenancy import TenantContext, tenant_transaction
from app.modules.products import service as products_service
from app.workers.beat import SWEEP_PHOTOS
from app.workers.celery_app import celery_app
from app.workers.jobs import tracked_job
from app.workers.tenants import each_company

logger = logging.getLogger(__name__)


@celery_app.task(
    name=products_service.DELETE_PHOTO_TASK, bind=True, max_retries=5, default_retry_delay=60
)
def delete_photo(self: Any, company_id: str, public_id: str) -> bool:
    """Supprime une image chez Cloudinary, si elle est bien du dossier de l'entreprise."""
    if not public_id.startswith(products_service.photo_folder(UUID(company_id)) + "/"):
        # Jamais l'image d'une autre entreprise, quel que soit le message reçu.
        logger.warning("Image hors du dossier de l'entreprise", extra={"company_id": company_id})
        return False
    try:
        products_service.delete_stored_photo(public_id)
    except cloudinary.CloudinaryError as exc:
        raise self.retry(exc=exc) from exc
    return True


@celery_app.task(name="products.sweep_photos")
@tracked_job("products.sweep_photos", ping_as=SWEEP_PHOTOS)
def sweep_photos(company_id: str) -> int:
    """Supprime les images orphelines du dossier d'une entreprise. Rend leur nombre."""
    account = products_service.cloudinary_account()
    if account is None:
        return 0
    ctx = TenantContext.bootstrap(UUID(company_id))
    folder = products_service.photo_folder(ctx.company_id) + "/"
    with products_service.http_client() as client:
        stored = cloudinary.list_folder(account, folder, client=client)
        with tenant_transaction(ctx) as session:
            referenced = products_service.referenced_photos(session, ctx)
        orphans = products_service.orphan_photos(stored, referenced, now=datetime.now(UTC))
        for public_id in orphans:
            if public_id.startswith(folder):
                cloudinary.destroy(account, public_id, client=client)
    if orphans:
        logger.info("Photos orphelines supprimées", extra={"company_id": company_id})
    return len(orphans)


@celery_app.task(name=SWEEP_PHOTOS)
@tracked_job(SWEEP_PHOTOS)
def sweep_photos_all() -> int:
    """Éventail : un balayage par entreprise, seulement si les photos sont configurées."""
    if products_service.cloudinary_account() is None:
        return 0
    count = 0
    for company_id in each_company():
        sweep_photos.delay(str(company_id))
        count += 1
    return count
