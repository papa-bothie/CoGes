"""Les défauts de développement refusés hors `local` et `ci` (prompt 21, P1.5 ; ADR 0087).

Le secret JWT par défaut (« change-me-000… ») est public : il est dans le dépôt. Il
passait le contrôle de longueur, donc un environnement oublié — préproduction, démo —
aurait signé ses jetons avec une clé que tout le monde connaît. Seul le VPS était
protégé, par `check_runtime_env`.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import SecretStr, ValidationError

from app.core.config import Settings

DEFAULT_SECRET = "change-me-" + "0" * 32
REAL_SECRET = "secret-de-test-tire-au-hasard-" + "x" * 32


@pytest.fixture(autouse=True)
def _no_inherited_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """La CI pose `COGES_JWT_SECRET` : le défaut ne serait jamais lu."""
    for name in ("COGES_JWT_SECRET", "COGES_FROZEN_NOW"):
        monkeypatch.delenv(name, raising=False)


def _settings(**values: Any) -> Settings:
    # `_env_file=None` : le `.env` du poste ne doit pas décider du résultat du test.
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


@pytest.mark.parametrize("env", ["staging", "production"])
def test_the_default_jwt_secret_is_refused_outside_local_and_ci(env: str) -> None:
    with pytest.raises(ValidationError, match="COGES_JWT_SECRET"):
        _settings(env=env)


@pytest.mark.parametrize("env", ["staging", "production"])
@pytest.mark.parametrize(
    "secret",
    [
        "change-me-" + "1" * 32,
        "CHANGE-ME-openssl-rand-hex-32-xxxxxxxxxxxxxxxx",  # le modèle de préproduction
    ],
)
def test_any_change_me_secret_is_refused_outside_local_and_ci(env: str, secret: str) -> None:
    with pytest.raises(ValidationError, match="COGES_JWT_SECRET"):
        _settings(env=env, jwt_secret=SecretStr(secret))


@pytest.mark.parametrize("env", ["local", "ci"])
def test_local_and_ci_keep_the_default(env: str) -> None:
    assert _settings(env=env).jwt_secret.get_secret_value() == DEFAULT_SECRET


@pytest.mark.parametrize("env", ["local", "ci", "staging", "production"])
def test_a_real_secret_passes_everywhere(env: str) -> None:
    settings = _settings(env=env, jwt_secret=SecretStr(REAL_SECRET))
    assert settings.jwt_secret.get_secret_value() == REAL_SECRET
