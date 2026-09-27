"""T40 et le relais de l'outbox — publication au moins une fois, après COMMIT.

**T40** : « crash simulé après COMMIT, avant publication ⇒ événement toujours présent
avec `published_at IS NULL`, rejouable ». C'est la propriété qui justifie l'ordre en
trois temps du relais : réclamer et commiter, publier, puis marquer. Marquer avant de
publier donnerait « au plus une fois », donc une perte silencieuse — ce que la
décision 04 refuse.

Le relais tourne sous `coges_relay`, qui n'a **aucun** privilège de table : les
assertions sur l'état de l'outbox se font donc en `coges_app`, sous RLS, comme le
ferait l'endpoint d'administration.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.orm import sessionmaker

from app.workers.relay import OutboxRelay
from tests.integration.relay_harness import RecordingBus, read_state, write_event
from tests.tenancy.harness import Tenant

pytestmark = pytest.mark.integration

#: Assez large pour que le lot emporte les événements du test : l'outbox est vidée
#: avant chaque test (`_empty_outbox`), quels que soient les événements que les autres
#: suites ont laissés derrière elles.
BATCH = 500


def _relay(factory: sessionmaker[Any], bus: RecordingBus) -> OutboxRelay:
    return OutboxRelay(bus, session_factory=factory, batch_size=BATCH, poll_interval=0.0)


@pytest.fixture(autouse=True)
def _empty_outbox(relay_session_factory: sessionmaker[Any]) -> None:
    """Publie ce que les suites précédentes ont laissé en attente : sans cela, un arriéré
    plus grand que `BATCH` repousserait l'événement du test hors du lot réclamé."""
    while not _relay(relay_session_factory, RecordingBus()).run_once().idle:
        pass


def test_t40_an_event_survives_a_crash_before_publication(
    session_factory: sessionmaker[Any],
    relay_session_factory: sessionmaker[Any],
    tenant_a: Tenant,
) -> None:
    """T40 — la publication échoue, l'événement reste en base et repart au passage suivant.

    Le premier passage simule Redis injoignable : `attempts` est consommé, mais
    `published_at` reste NULL. Le second passage, transport rétabli, le publie. Rien
    n'a été perdu, et rien n'a été publié deux fois **en effet** — les consommateurs
    s'en chargent (`processed_events`).
    """
    event_id, _ = write_event(session_factory, tenant_a.ctx)

    broken = RecordingBus(fail_all=True)
    first = _relay(relay_session_factory, broken).run_once()

    assert event_id not in broken.published_ids
    assert first.failed >= 1, "la panne de transport n'a pas été comptée"
    after_crash = read_state(session_factory, tenant_a.ctx, event_id)
    assert after_crash.published_at is None, (
        "événement marqué publié alors que le transport a échoué : « au plus une fois »"
    )
    assert after_crash.attempts == 1, "la tentative consommée n'est pas tracée"

    working = RecordingBus()
    second = _relay(relay_session_factory, working).run_once()

    assert event_id in working.published_ids, "l'événement n'est pas rejoué à la reprise"
    assert second.published >= 1
    after_recovery = read_state(session_factory, tenant_a.ctx, event_id)
    assert after_recovery.published_at is not None
    assert after_recovery.attempts == 2


def test_the_relay_marks_only_what_it_really_published(
    session_factory: sessionmaker[Any],
    relay_session_factory: sessionmaker[Any],
    tenant_a: Tenant,
) -> None:
    """Un échec sur un événement n'emporte pas les autres du même lot.

    Le lot est traité événement par événement : une charge utile qu'un abonné refuse
    ne doit pas empêcher les autres de partir.
    """
    doomed, _ = write_event(session_factory, tenant_a.ctx)
    healthy, _ = write_event(session_factory, tenant_a.ctx)

    bus = RecordingBus(fail_for={doomed})
    result = _relay(relay_session_factory, bus).run_once()

    assert healthy in bus.published_ids
    assert doomed not in bus.published_ids
    assert result.failed >= 1

    assert read_state(session_factory, tenant_a.ctx, healthy).published_at is not None
    assert read_state(session_factory, tenant_a.ctx, doomed).published_at is None


def test_an_idle_relay_does_nothing(relay_session_factory: sessionmaker[Any]) -> None:
    """File vide : aucun appel au transport, et le passage se déclare inactif."""
    bus = RecordingBus()
    relay = _relay(relay_session_factory, bus)
    relay.run_once()  # vide ce qui traîne des autres suites

    result = relay.run_once()

    assert result.idle is True
    assert result.claimed == 0
    assert result.published == 0


def test_an_exhausted_event_is_no_longer_claimed(
    session_factory: sessionmaker[Any],
    relay_session_factory: sessionmaker[Any],
    tenant_a: Tenant,
) -> None:
    """Après dix tentatives, l'événement devient un rebut : plus aucune reprise.

    Il **reste en base**, rejouable à la main après correction (ADR 0032) : la file de
    rebut n'est pas un support jetable. Ce qui s'arrête, c'est la boucle automatique —
    sans quoi un événement définitivement invalide occuperait chaque lot, pour rien.

    La dixième tentative est aussi la borne du `CHECK attempts <= 10` : sans le filtre
    `attempts < 10` dans `outbox_claim`, la onzième lèverait 23514 et casserait le
    relais pour tous les autres.
    """
    event_id, _ = write_event(session_factory, tenant_a.ctx)

    broken = RecordingBus(fail_all=True)
    relay = _relay(relay_session_factory, broken)
    for _ in range(10):
        relay.run_once()

    exhausted = read_state(session_factory, tenant_a.ctx, event_id)
    assert exhausted.attempts == 10
    assert exhausted.published_at is None

    # Onzième passage : l'événement n'est plus réclamé, et rien ne lève.
    working = RecordingBus()
    result = _relay(relay_session_factory, working).run_once()

    assert event_id not in working.published_ids, "un rebut continue d'être réclamé"
    assert result.dead_lettered == 0, "le rebut est recompté alors qu'il n'est plus réclamé"
    assert read_state(session_factory, tenant_a.ctx, event_id).attempts == 10
