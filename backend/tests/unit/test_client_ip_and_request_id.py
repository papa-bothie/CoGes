"""Adresse du client et identifiant de requête (P2.5, P2.6 ; ADR 0088).

* `X-Forwarded-For` terminé par une virgule donnait une adresse vide, et le middleware
  sautait la limite par IP : n'importe qui la contournait d'un caractère.
* IPv6 : un client dispose d'au moins un /64 ; compter par adresse lui donnait 2⁶⁴
  compteurs neufs.
* `re.match` sur `^…$` accepte un saut de ligne final : l'identifiant de requête
  renvoyé dans un en-tête et dans les journaux pouvait en porter un.
"""

from __future__ import annotations

from typing import Any

import pytest
from starlette.requests import Request

from app.core import deps, middleware, rate_limit
from app.core.config import get_settings


class _Peer:
    host = "203.0.113.9"


@pytest.fixture
def behind_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings().model_copy(update={"trust_proxy_headers": True})
    monkeypatch.setattr(deps, "get_settings", lambda: settings)


@pytest.mark.usefixtures("behind_proxy")
@pytest.mark.parametrize("header", ["198.51.100.1,", "198.51.100.1, ", "pas-une-ip", ",", " "])
def test_an_empty_or_invalid_last_hop_falls_back_to_the_tcp_peer(header: str) -> None:
    assert deps.raw_client_ip(header, _Peer()) == "203.0.113.9"


@pytest.mark.usefixtures("behind_proxy")
def test_the_rightmost_valid_hop_is_still_used() -> None:
    assert deps.raw_client_ip("10.0.0.1, 198.51.100.7", _Peer()) == "198.51.100.7"


def test_ipv6_clients_share_one_counter_per_64(monkeypatch: pytest.MonkeyPatch) -> None:
    buckets: list[str] = []
    monkeypatch.setattr(rate_limit, "_hit", lambda bucket, *a, **k: buckets.append(bucket))
    rate_limit.hit_ip("2001:db8:1:2:aaaa::1")
    rate_limit.hit_ip("2001:db8:1:2:bbbb::2")
    rate_limit.hit_ip("2001:db8:1:3::1")
    rate_limit.hit_ip("198.51.100.4")
    assert buckets[0] == buckets[1], "deux adresses du même /64 ont deux compteurs"
    assert buckets[0] != buckets[2]
    assert buckets[3] == "ip:198.51.100.4"


def _request(request_id: str) -> Request:
    scope: dict[str, Any] = {
        "type": "http",
        "headers": [(b"x-request-id", request_id.encode())],
    }
    return Request(scope)


def test_a_request_id_with_a_trailing_newline_is_replaced() -> None:
    supplied = "abcdef12-3456\n"
    assert middleware._request_id(_request(supplied)) != supplied


def test_a_clean_request_id_is_kept() -> None:
    assert middleware._request_id(_request("abcdef12-3456")) == "abcdef12-3456"
