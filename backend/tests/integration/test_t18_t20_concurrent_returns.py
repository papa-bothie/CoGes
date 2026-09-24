"""T18 et T20 sous concurrence — les deux plafonds tiennent à deux caisses.

Le plafond d'un retour et celui d'un remboursement portent tous deux sur une **somme
de lignes** : « Σ des retours d'une ligne ≤ `sale_items.qty` » (§ 4.7) et
« `refunded_total <= total_refund` » (§ 4.6). Une vérification qui lit puis décide ne
tient jamais ce genre de promesse : deux transactions simultanées lisent le même
cumul périmé, concluent toutes les deux que ça passe, et la ligne ressort retournée
deux fois ou remboursée au double.

C'est la leçon déjà apprise sur le plafond de crédit (ADR 0023, révision 0007), et
qui avait coûté un correctif. Elle vaut ici aussi, à ceci près que le § 8.7 avait
**déjà** posé les verrous : `return_item_check` verrouille la ligne de vente,
`refund_check` verrouille le retour. Ces deux tests ne corrigent donc rien — ils
prouvent que ces verrous font bien ce qu'on leur prête, et rendent la propriété non
régressive.

Comme T28 et T38, ils ne **courent** pas après la fenêtre de concurrence : ils la
**provoquent**. Une troisième connexion s'approprie d'abord la ligne de rendez-vous,
les deux caisses viennent s'y bloquer, et c'est le COMMIT du test qui les relâche.
"""

from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql import text

from app.core.database import create_app_engine
from app.core.errors import sqlstate
from app.core.tenancy import tenant_transaction
from tests.integration.sales_harness import (
    add_line,
    confirm,
    letter_refund,
    make_return,
    make_sale,
    read_return,
    refund_payment,
    return_line,
)
from tests.integration.stock_harness import insert_movement, make_product
from tests.tenancy.harness import Tenant

pytestmark = pytest.mark.integration

#: SQLSTATE applicatifs posés par la révision 0008 (ADR 0026).
RETURN_QTY_CAP = "CG040"
REFUND_EXCEEDS_DUE = "CG041"

#: `deadlock_detected`, celui de PostgreSQL et non du projet.
DEADLOCK_DETECTED = "40P01"


_LOCK_RETURN = text("SELECT total_refund FROM sale_returns WHERE id = :id FOR UPDATE")


@pytest.fixture
def concurrent_session_factory(
    migrated_database: str, database_urls: tuple[str, str]
) -> Iterator[sessionmaker[Any]]:
    """Fabrique de sessions sur un pool de **trois** connexions.

    Le pool de la suite n'en contient qu'une — c'est ce qu'exige T4. Il en faut trois
    ici : une pour le verrou tenu par le test, deux pour les caisses concurrentes.
    """
    _, app_url = database_urls
    engine: Engine = create_app_engine(app_url, pool_size=3, max_overflow=0)
    try:
        yield sessionmaker(bind=engine, expire_on_commit=False, future=True)
    finally:
        engine.dispose()


def _confirmed_line(
    session_factory: sessionmaker[Any], tenant: Tenant, *, qty: str, unit_price: str
) -> tuple[UUID, UUID]:
    """Une vente confirmée d'une seule ligne. Rend `(sale_id, sale_item_id)`."""
    with tenant_transaction(tenant.ctx, session_factory=session_factory) as session:
        product_id = make_product(session, tenant)
        insert_movement(session, tenant, product_id, "initial", "1000", unit_cost="10")
        sale_id = make_sale(session, tenant, customer_id=tenant.customer_id)
        item_id = add_line(session, tenant, sale_id, product_id, qty=qty, unit_price=unit_price)
        confirm(session, tenant, sale_id)
    return sale_id, item_id


def test_t20_concurrent_refunds(
    concurrent_session_factory: sessionmaker[Any], tenant_a: Tenant
) -> None:
    """Retour de 1 000, deux remboursements de 1 000 en parallèle : un seul passe.

    Le point de rendez-vous est la ligne de `sale_returns`, que `refund_check`
    verrouille **avant** de calculer le reste dû. Sans ce verrou, les deux caisses
    liraient `refunded_total = 0`, concluraient toutes les deux qu'il reste 1 000 à
    payer, et le client repartirait remboursé deux fois — sans qu'aucune contrainte
    déclarative ne puisse le rattraper, puisque `sale_returns_refund_cap` porte sur
    une colonne que le trigger `refund_rollup` écrit *après coup*.

    Avec lui, la seconde reprend la main après le COMMIT de la première et somme, en
    `READ COMMITTED`, un `refunded_total` qui la contient déjà.
    """
    sale_id, item_id = _confirmed_line(
        concurrent_session_factory, tenant_a, qty="10", unit_price="1000"
    )
    with tenant_transaction(tenant_a.ctx, session_factory=concurrent_session_factory) as session:
        return_id = make_return(session, tenant_a, sale_id)
        return_line(session, tenant_a, return_id, item_id, qty="1", refund_amount="1000.00")

    def pay_back(_: int) -> str:
        """Une caisse qui rembourse la totalité du retour, dans l'ordre du § 5.4."""
        try:
            with tenant_transaction(
                tenant_a.ctx, session_factory=concurrent_session_factory
            ) as session:
                # Étape 1 : verrouiller le retour **avant** d'écrire quoi que ce soit.
                # C'est là que la caisse vient se bloquer, et ce n'est pas cosmétique :
                # voir `test_t20_refunding_without_locking_the_return_first_deadlocks`.
                session.execute(_LOCK_RETURN, {"id": return_id})
                # Étapes 2 et 3 : le décaissement, puis son lettrage.
                payment_id = refund_payment(session, tenant_a, return_id, amount="1000.00")
                letter_refund(session, tenant_a, return_id, payment_id, amount="1000.00")
        except DBAPIError as exc:
            assert sqlstate(exc) == REFUND_EXCEEDS_DUE, str(exc)
            return "refus"
        return "succès"

    with ThreadPoolExecutor(max_workers=2) as pool:
        with tenant_transaction(
            tenant_a.ctx, session_factory=concurrent_session_factory
        ) as session:
            # 1. Le test s'approprie le retour : les deux caisses vont s'arrêter
            #    exactement là où le § 5.4 leur demande de prendre ce même verrou.
            session.execute(_LOCK_RETURN, {"id": return_id})
            # 2. Les deux remboursements partent et se bloquent.
            futures = [pool.submit(pay_back, index) for index in range(2)]
        # 3. Le COMMIT relâche le verrou : ils reprennent l'un après l'autre.
        outcomes = sorted(future.result() for future in futures)

    assert outcomes == ["refus", "succès"], (
        f"exactement un remboursement doit passer, obtenu : {outcomes}"
    )

    with tenant_transaction(tenant_a.ctx, session_factory=concurrent_session_factory) as session:
        state = read_return(session, return_id)
        lettered = session.execute(
            text(
                "SELECT count(*), coalesce(sum(amount), 0) FROM sale_return_refunds "
                " WHERE sale_return_id = :id"
            ),
            {"id": return_id},
        ).one()

    assert state.refunded_total == Decimal("1000.00"), "jamais le double du remboursable"
    assert state.refund_status == "settled"
    assert lettered == (1, Decimal("1000.00")), "le remboursement refusé ne laisse aucune trace"


def test_t18_concurrent_returns_on_the_same_line(
    concurrent_session_factory: sessionmaker[Any], tenant_a: Tenant
) -> None:
    """Ligne de 10 vendus, deux retours de 10 en parallèle : un seul passe.

    Même mécanique, autre ligne de rendez-vous : `return_item_check` verrouille la
    **ligne de vente** avant de sommer ce qui en a déjà été retourné. Sans ce verrou,
    deux comptoirs rendraient 20 articles d'une ligne qui n'en a vendu que 10, et le
    stock se retrouverait crédité de marchandise qui n'existe pas.
    """
    sale_id, item_id = _confirmed_line(
        concurrent_session_factory, tenant_a, qty="10", unit_price="1000"
    )

    def give_back(_: int) -> str:
        """Un comptoir qui enregistre le retour de la ligne entière."""
        try:
            with tenant_transaction(
                tenant_a.ctx, session_factory=concurrent_session_factory
            ) as session:
                # L'en-tête passe : il ne touche pas `sale_items`.
                return_id = make_return(session, tenant_a, sale_id)
                # La ligne, elle, vient buter sur le verrou.
                return_line(
                    session, tenant_a, return_id, item_id, qty="10", refund_amount="10000.00"
                )
        except DBAPIError as exc:
            assert sqlstate(exc) == RETURN_QTY_CAP, str(exc)
            return "refus"
        return "succès"

    with ThreadPoolExecutor(max_workers=2) as pool:
        with tenant_transaction(
            tenant_a.ctx, session_factory=concurrent_session_factory
        ) as session:
            session.execute(
                text("SELECT qty FROM sale_items WHERE id = :id FOR UPDATE"), {"id": item_id}
            )
            futures = [pool.submit(give_back, index) for index in range(2)]
        outcomes = sorted(future.result() for future in futures)

    assert outcomes == ["refus", "succès"], f"exactement un retour doit passer, obtenu : {outcomes}"

    with tenant_transaction(tenant_a.ctx, session_factory=concurrent_session_factory) as session:
        returned = session.execute(
            text("SELECT coalesce(sum(qty), 0) FROM sale_return_items WHERE sale_item_id = :id"),
            {"id": item_id},
        ).scalar_one()
        headers = session.execute(
            text("SELECT count(*) FROM sale_returns WHERE sale_id = :id"), {"id": sale_id}
        ).scalar_one()

    assert returned == Decimal("10.000"), "le cumul retourné ne dépasse jamais la quantité vendue"
    # Le retour refusé ne laisse pas non plus son en-tête : la transaction entière
    # est annulée, numéro de document compris (ADR 0021).
    assert headers == 1


def test_t20_a_second_refund_still_passes_when_something_remains_due(
    concurrent_session_factory: sessionmaker[Any], tenant_a: Tenant
) -> None:
    """Le verrou sérialise, il ne bloque pas : deux règlements partiels passent tous deux.

    Sans ce test, les deux précédents prouveraient seulement qu'on ne peut pas trop
    rembourser — pas que le verrou laisse passer ce qui est légitime.
    """
    sale_id, item_id = _confirmed_line(
        concurrent_session_factory, tenant_a, qty="10", unit_price="1000"
    )
    with tenant_transaction(tenant_a.ctx, session_factory=concurrent_session_factory) as session:
        return_id = make_return(session, tenant_a, sale_id)
        return_line(session, tenant_a, return_id, item_id, qty="1", refund_amount="1000.00")

    def pay_half(_: int) -> str:
        with tenant_transaction(
            tenant_a.ctx, session_factory=concurrent_session_factory
        ) as session:
            session.execute(_LOCK_RETURN, {"id": return_id})
            payment_id = refund_payment(session, tenant_a, return_id, amount="500.00")
            letter_refund(session, tenant_a, return_id, payment_id, amount="500.00")
        return "succès"

    with ThreadPoolExecutor(max_workers=2) as pool:
        with tenant_transaction(
            tenant_a.ctx, session_factory=concurrent_session_factory
        ) as session:
            session.execute(_LOCK_RETURN, {"id": return_id})
            futures = [pool.submit(pay_half, index) for index in range(2)]
        outcomes = [future.result() for future in futures]

    assert outcomes == ["succès", "succès"]

    with tenant_transaction(tenant_a.ctx, session_factory=concurrent_session_factory) as session:
        state = read_return(session, return_id)

    assert state.refunded_total == Decimal("1000.00")
    assert state.refund_status == "settled"


def test_t20_refunding_without_locking_the_return_first_deadlocks(
    concurrent_session_factory: sessionmaker[Any], tenant_a: Tenant
) -> None:
    """L'ordre du § 5.4 n'est pas cosmétique : l'ignorer produit un interblocage.

    `payments.sale_return_id` porte une clé étrangère vers `sale_returns`. Insérer le
    décaissement prend donc un verrou **`FOR KEY SHARE`** sur la ligne du retour —
    partagé, donc accordé aux deux caisses à la fois. Chacune demande ensuite le
    `FOR UPDATE` de `refund_check`, qui attend que l'autre ait lâché son verrou
    partagé. Les deux s'attendent : PostgreSQL en abat une en `40P01`.

    La règle est générale : **prendre le verrou fort d'abord**, jamais un verrou
    partagé qu'il faudra ensuite élever. C'est pourquoi le § 5.4 fait du
    « verrouiller `sale_returns` FOR UPDATE » son étape 1, et pourquoi
    `sales.refund_return` appelle `SaleReturnRepository.get_for_update` avant de
    passer la main à Finance.

    Le résultat reste **sûr** — aucun double remboursement, la transaction perdante
    est annulée entière — mais il est opaque : un `40P01` n'est pas un
    `refund_exceeds_due`, il ne dit rien au caissier et désigne une victime au
    hasard. Ce test fige la raison d'être de l'ordre, pour que personne ne l'inverse
    en croyant simplifier.

    `sale_return_items` n'a pas ce problème, et c'est instructif :
    `return_item_check` est un trigger **BEFORE INSERT**, il prend son `FOR UPDATE`
    sur la ligne de vente *avant* que la clé étrangère ne demande son `KEY SHARE`.
    L'ordre y est déjà le bon, sans que personne ait à y penser.
    """
    sale_id, item_id = _confirmed_line(
        concurrent_session_factory, tenant_a, qty="10", unit_price="1000"
    )
    with tenant_transaction(tenant_a.ctx, session_factory=concurrent_session_factory) as session:
        return_id = make_return(session, tenant_a, sale_id)
        return_line(session, tenant_a, return_id, item_id, qty="1", refund_amount="1000.00")

    def pay_back_out_of_order(_: int) -> str:
        """Le même remboursement, mais sans l'étape 1 du § 5.4."""
        try:
            with tenant_transaction(
                tenant_a.ctx, session_factory=concurrent_session_factory
            ) as session:
                payment_id = refund_payment(session, tenant_a, return_id, amount="1000.00")
                letter_refund(session, tenant_a, return_id, payment_id, amount="1000.00")
        except DBAPIError as exc:
            return sqlstate(exc) or "inconnu"
        return "succès"

    with ThreadPoolExecutor(max_workers=2) as pool:
        with tenant_transaction(
            tenant_a.ctx, session_factory=concurrent_session_factory
        ) as session:
            session.execute(_LOCK_RETURN, {"id": return_id})
            futures = [pool.submit(pay_back_out_of_order, index) for index in range(2)]
        outcomes = sorted(future.result() for future in futures)

    # L'une réussit, l'autre est abattue — soit par l'interblocage, soit, si elle a
    # eu le temps de dépasser la clé étrangère, par le plafond lui-même.
    assert outcomes[1] == "succès", f"une caisse doit passer, obtenu : {outcomes}"
    assert outcomes[0] in {DEADLOCK_DETECTED, REFUND_EXCEEDS_DUE}, (
        f"l'autre doit être refusée, obtenu : {outcomes[0]}"
    )

    with tenant_transaction(tenant_a.ctx, session_factory=concurrent_session_factory) as session:
        state = read_return(session, return_id)

    # Le point qui compte : quel que soit le refus, jamais de double remboursement.
    assert state.refunded_total == Decimal("1000.00")
    assert state.refund_status == "settled"
