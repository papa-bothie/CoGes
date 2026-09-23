"""Suite de fuite inter-tenant — vide en phase 00.

Les tests T1 à T5, T36 et T37 (§ 10 du Modèle de données) arrivent en phase 01 et
attaqueront la base directement, connectés en `coges_app`. Ce marqueur évite un
répertoire vide (pytest sortirait en code 5) sans masquer le moindre échec.
"""

import pytest


@pytest.mark.tenancy
@pytest.mark.skip(reason="Tests de fuite T1-T5, T36, T37 : phase 01 (socle tenant + RLS)")
def test_cross_tenant_leak_suite_arrives_in_phase_01() -> None:
    raise AssertionError("ne doit jamais s'exécuter en phase 00")
