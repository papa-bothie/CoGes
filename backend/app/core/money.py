"""Noyau partagé — montants, quantités, coûts et taux en `Decimal`.

Règle absolue du projet : **jamais de flottant sur une donnée financière**
(décision 15). `NUMERIC` en base, `Decimal` en Python, **chaîne** dans le JSON.

Précisions, alignées sur le § 4 du Modèle de données :

| Grandeur   | Type SQL        | Exposant |
|------------|-----------------|----------|
| montant    | numeric(14, 2)  | 0.01     |
| quantité   | numeric(14, 3)  | 0.001    |
| coût unit. | numeric(14, 4)  | 0.0001   |
| taux       | numeric(6, 4)   | 0.0001   |

L'arrondi est `ROUND_HALF_UP`, identique à celui de la fonction `round()` de
PostgreSQL sur `numeric` : le CMP calculé par `cmp_next_avg()` en base et un calcul
Python sur les mêmes entrées donnent donc le même résultat.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Annotated

from pydantic import BeforeValidator, PlainSerializer

AMOUNT_EXPONENT = Decimal("0.01")
QUANTITY_EXPONENT = Decimal("0.001")
UNIT_COST_EXPONENT = Decimal("0.0001")
RATE_EXPONENT = Decimal("0.0001")

type Numeric = Decimal | int | str


class NotANumberError(TypeError, ValueError):
    """Type inapte à porter un montant : flottant, booléen.

    Hérite des **deux** exceptions à dessein. `TypeError` pour l'appelant Python,
    parce qu'un flottant sur un montant est une faute de type. `ValueError` parce
    que Pydantic ne rattrape que `ValueError` et `AssertionError` : sans cela, un
    `{"unit_price": 1500.5}` envoyé par un client sortirait en 500 au lieu du 422
    qui nomme le champ fautif.
    """


def _quantize(value: Numeric, exponent: Decimal, label: str) -> Decimal:
    """Convertit en `Decimal` quantifié, en refusant tout flottant."""
    if isinstance(value, bool):
        raise NotANumberError(f"{label} : un booléen n'est pas une valeur numérique.")
    if isinstance(value, float):
        raise NotANumberError(
            f"{label} : les flottants sont interdits sur une donnée financière. "
            "Passer une chaîne, un entier ou un Decimal."
        )
    try:
        decimal_value = value if isinstance(value, Decimal) else Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{label} : valeur numérique invalide ({value!r}).") from exc

    if not decimal_value.is_finite():
        raise ValueError(f"{label} : valeur non finie ({value!r}).")

    return decimal_value.quantize(exponent, rounding=ROUND_HALF_UP)


def amount(value: Numeric) -> Decimal:
    """Montant monétaire, 2 décimales."""
    return _quantize(value, AMOUNT_EXPONENT, "montant")


def quantity(value: Numeric) -> Decimal:
    """Quantité de stock, 3 décimales."""
    return _quantize(value, QUANTITY_EXPONENT, "quantité")


def unit_cost(value: Numeric) -> Decimal:
    """Coût unitaire, 4 décimales (précision nécessaire au CMP)."""
    return _quantize(value, UNIT_COST_EXPONENT, "coût unitaire")


def rate(value: Numeric) -> Decimal:
    """Taux (TVA, remise), 4 décimales."""
    return _quantize(value, RATE_EXPONENT, "taux")


def serialize(value: Decimal) -> str:
    """Représentation JSON d'une valeur décimale : toujours une chaîne."""
    return format(value, "f")


_as_string = PlainSerializer(serialize, return_type=str, when_used="json")

# Types annotés à utiliser dans les schémas Pydantic des modules.
type Amount = Annotated[Decimal, BeforeValidator(amount), _as_string]
type Quantity = Annotated[Decimal, BeforeValidator(quantity), _as_string]
type UnitCost = Annotated[Decimal, BeforeValidator(unit_cost), _as_string]
type Rate = Annotated[Decimal, BeforeValidator(rate), _as_string]
