"""Concurrence sur le rafraîchissement : un jeton ne se consomme qu'une fois.

Sans verrou, deux requêtes simultanées porteuses du même refresh token peuvent le
tourner toutes les deux et obtenir chacune une session valide — un jeton volé
resterait alors utilisable en parallèle du jeton légitime, sans jamais déclencher
la détection de réutilisation. Mesuré : sur huit appels lancés ensemble, deux lisent
la ligne avant que le premier ne la révoque.

Le test ne **court** pas après cette fenêtre, il la **provoque** : il prend lui-même
le verrou de ligne, laisse le rafraîchissement s'y heurter, puis révoque la session
avant de relâcher. Aucun `sleep` de complaisance, aucun résultat dépendant de
l'ordonnancement.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
from _pytest.monkeypatch import MonkeyPatch
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql import text

from app.core.database import create_app_engine
from app.core.errors import AuthenticationRequiredError
from app.core.security import hash_refresh_token
from app.core.tenancy import TenantContext, tenant_transaction
from app.modules.auth import service as auth_service
from app.modules.auth.schemas import LoginRequest
from tests.conftest import TEST_PASSWORD, DemoCompany

pytestmark = pytest.mark.integration

#: Laps laissé au rafraîchissement concurrent pour atteindre sa lecture verrouillée.
#: Sans verrou, il a largement le temps de terminer (mesuré : ~150 ms).
OVERLAP_SECONDS = 1.0


@pytest.fixture
def concurrent_session_factory(
    migrated_database: str, database_urls: tuple[str, str]
) -> Iterator[sessionmaker[Any]]:
    """Fabrique de sessions sur un pool de **deux** connexions.

    Le pool de la suite n'en contient qu'une — c'est ce qu'exige T4 pour prouver
    qu'aucun contexte ne survit au retour au pool. Il en faut deux ici : une pour
    le verrou tenu par le test, une pour le rafraîchissement concurrent.
    """
    _, app_url = database_urls
    engine: Engine = create_app_engine(app_url, pool_size=2, max_overflow=0)
    try:
        yield sessionmaker(bind=engine, expire_on_commit=False, future=True)
    finally:
        engine.dispose()


def test_refresh_serialises_behind_a_concurrent_consumer(
    concurrent_session_factory: sessionmaker[Any], company_alpha: DemoCompany
) -> None:
    """Un rafraîchissement concurrent attend son tour, puis constate la révocation.

    Déroulé : le test verrouille la ligne de session ; un fil appelle `refresh` et
    se bloque sur ce verrou ; le test révoque la session — c'est ce qu'aurait fait
    le concurrent gagnant — puis relâche. Le fil repart, relit la ligne révoquée et
    refuse.

    Sans `FOR UPDATE`, le fil lirait la ligne **avant** la révocation, la trouverait
    vierge et émettrait une seconde session valide : le test échouerait.
    """
    patcher = MonkeyPatch()
    patcher.setattr("app.core.tenancy.get_session_factory", lambda: concurrent_session_factory)
    patcher.setattr(
        "app.modules.auth.repository.get_session_factory", lambda: concurrent_session_factory
    )
    try:
        tokens = auth_service.login(
            LoginRequest(
                company_slug=company_alpha.slug,
                email=company_alpha.email,
                password=TEST_PASSWORD,
            )
        )
        token_hash = hash_refresh_token(tokens.refresh_token)
        ctx = TenantContext.bootstrap(company_alpha.company_id)

        def competing_refresh() -> str:
            try:
                auth_service.refresh(tokens.refresh_token)
            except AuthenticationRequiredError as exc:
                return f"refus: {exc.message}"
            return "succès"

        with ThreadPoolExecutor(max_workers=1) as pool:
            with tenant_transaction(ctx, session_factory=concurrent_session_factory) as session:
                # 1. Le test s'approprie la ligne.
                session.execute(
                    text("SELECT id FROM auth_sessions WHERE token_hash = :h FOR UPDATE"),
                    {"h": token_hash},
                )

                # 2. Le rafraîchissement concurrent démarre. Avec `FOR UPDATE`, il se
                #    bloque sur la lecture ; sans, il lit une ligne encore vierge.
                pending = pool.submit(competing_refresh)
                time.sleep(OVERLAP_SECONDS)

                # 3. Le concurrent « gagnant » consomme le jeton.
                session.execute(
                    text("UPDATE auth_sessions SET revoked_at = now() WHERE token_hash = :h"),
                    {"h": token_hash},
                )
            # 4. COMMIT : le verrou tombe, le fil repart.

            outcome = pending.result(timeout=30)
    finally:
        patcher.undo()

    assert outcome == "refus: Session révoquée."

    # La détection de réutilisation a fait tomber toute la famille.
    with tenant_transaction(ctx, session_factory=concurrent_session_factory) as session:
        still_live = session.execute(
            text(
                "SELECT count(*) FROM auth_sessions WHERE family_id = ("
                "  SELECT family_id FROM auth_sessions WHERE token_hash = :h"
                ") AND revoked_at IS NULL"
            ),
            {"h": token_hash},
        ).scalar_one()

    assert still_live == 0, "une session de la famille est restée active après la course"
