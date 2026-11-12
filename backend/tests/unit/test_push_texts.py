"""Notifications sur le téléphone : textes sans montant, chemins sûrs, chiffrement (ADR 0120)."""

from __future__ import annotations

import json
import os
from uuid import uuid4

import http_ece  # type: ignore[import-untyped]
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from app.core import webpush
from app.modules.notifications import push
from tests.unit.test_plain_words import FORBIDDEN

ID = uuid4()


def _every_type() -> list[push.PushMessage]:
    """Un texte par type d'alerte, avec des noms réalistes."""
    return [
        push.stock_low("Riz 25 kg", "3 sacs", ID),
        push.stock_low("Huile Dinor 5 L", "12,5 L", ID),
        push.stock_out("Riz 25 kg", ID),
        push.debt_due("Moussa Diop", "customer", ID),
        push.debt_due(None, "customer", None),
        push.debt_due("Sénégal Distribution", "supplier", ID),
        push.sale_cancelled("42", "Awa Ndiaye", corrected=False, sale_id=ID),
        push.sale_cancelled("1044", "Awa Ndiaye", corrected=True, sale_id=ID),
        push.sale_cancelled("7", None, corrected=False, sale_id=ID),
        push.insight_critical("stockout_risk"),
        push.login_failures("Fatou Sall"),
        push.trial_ending(7),
        push.trial_ending(3),
        push.trial_ending(1),
        push.trial_ending(0),
        push.support_access(),
        push.burst(4),
    ]


@pytest.mark.parametrize("message", _every_type(), ids=lambda message: message.title)
def test_no_type_shows_an_amount_or_a_phone_number(message: push.PushMessage) -> None:
    """Décision du propriétaire : le détail utile, sans aucun montant (ni téléphone)."""
    assert not push.shows_money_or_phone(message.title), message.title
    assert not push.shows_money_or_phone(message.body), message.body
    assert push.is_app_path(message.url), message.url
    assert push.safe_message(message.title, message.body, message.url) == message
    for term, pattern in FORBIDDEN.items():
        assert not pattern.search(f"{message.title} {message.body}"), term


def test_the_examples_of_the_owner() -> None:
    assert push.stock_low("Riz 25 kg", "3 sacs", ID).title == "Riz 25 kg : stock bas (3 sacs)"
    assert push.stock_out("Riz 25 kg", ID).title == "Riz 25 kg est épuisé"
    # « échéance » est hors du lexique (ADR 0069) : les mots de la cloche (ADR 0074).
    assert push.debt_due("Moussa Diop", "customer", ID).title == "Moussa D. n'a pas payé à temps"
    assert (
        push.sale_cancelled("42", "Awa Ndiaye", corrected=False, sale_id=ID).title
        == "Vente n° 42 annulée par Awa"
    )
    assert push.trial_ending(3).title == "Fin de l'essai dans 3 jours"
    assert push.support_access().title == "Accès support ouvert par l'équipe CoGes"


@pytest.mark.parametrize(
    "text",
    [
        "Vente n° 42 annulée (87 500 F)",
        "12000 FCFA attendus",
        "5 000 F",
        "3 XOF",
        "Appelez le 77 123 45 67",
        "+221771234567",
        "deux mille francs : 2000 francs",
    ],
)
def test_the_detector_finds_amounts_and_phone_numbers(text: str) -> None:
    assert push.shows_money_or_phone(text)


@pytest.mark.parametrize("text", ["Lot 4f0a", "Pile 9V", "Riz 25 kg 3e4f", "Ampoule 60W", "2 fois"])
def test_ordinary_names_are_not_taken_for_amounts(text: str) -> None:
    assert not push.shows_money_or_phone(text)


def test_an_article_named_with_a_price_falls_back_to_the_generic_text() -> None:
    """Le nom vient du client : « Sac 5 000 F » ne s'affiche pas sur l'écran verrouillé."""
    message = push.safe_message(*push.stock_out("Sac 5 000 F", ID).as_data().values())
    assert (message.title, message.body) == (push.FALLBACK_TITLE, push.FALLBACK_BODY)


@pytest.mark.parametrize(
    "url",
    ["//evil.example.com", "https://evil.example.com", "javascript:alert(1)", "/\\evil", "x/y", ""],
)
def test_a_notification_never_leads_out_of_coges(url: str) -> None:
    assert not push.is_app_path(url)
    assert push.safe_message("Titre", "Texte", url).url == push.ALERTS_PATH


def test_a_stored_message_is_checked_again() -> None:
    stored = {"push": {"title": "Payé 5 000 F", "body": "", "url": "//evil"}}
    message = push.message_of(stored)
    assert message.title == push.FALLBACK_TITLE
    assert message.url == push.ALERTS_PATH
    assert push.message_of({}).title == push.FALLBACK_TITLE


@pytest.mark.parametrize(
    ("endpoint", "allowed"),
    [
        ("https://fcm.googleapis.com/fcm/send/abc", True),
        ("https://updates.push.services.mozilla.com/wpush/v2/abc", True),
        ("https://web.push.apple.com/abc", True),
        ("https://wns2-par02p.notify.windows.com/w/?token=abc", True),
        ("http://fcm.googleapis.com/fcm/send/abc", False),
        ("https://fcm.googleapis.com.evil.example.com/abc", False),
        ("https://evilfcm.googleapis.com.example/abc", False),
        ("https://user:pw@fcm.googleapis.com/abc", False),
        ("https://fcm.googleapis.com:8443/abc", False),
        ("https://169.254.169.254/latest", False),
        ("https://localhost/abc", False),
    ],
)
def test_only_known_push_services(endpoint: str, allowed: bool) -> None:
    """Le worker ne poste jamais vers une adresse quelconque fournie par un client."""
    assert webpush.push_host_allowed(endpoint) is allowed


def _receiver() -> tuple[ec.EllipticCurvePrivateKey, str, bytes, str]:
    key = ec.generate_private_key(ec.SECP256R1())
    public = key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    auth = os.urandom(16)
    return key, webpush.b64url_encode(public), auth, webpush.b64url_encode(auth)


def test_only_the_device_can_read_the_message() -> None:
    key, p256dh, auth, auth_text = _receiver()
    assert webpush.subscription_keys_valid(p256dh, auth_text)
    target = webpush.PushTarget("https://fcm.googleapis.com/fcm/send/x", p256dh, auth_text)

    body = webpush.encrypt(b'{"title": "Riz 25 kg est \\u00e9puis\\u00e9"}', target)
    clear = http_ece.decrypt(body, private_key=key, auth_secret=auth, version="aes128gcm")
    assert json.loads(clear)["title"] == "Riz 25 kg est épuisé"
    assert webpush.encrypt(b"x", target) != webpush.encrypt(b"x", target), "sel neuf"


def test_vapid_signs_for_the_push_service_only() -> None:
    public_key, private_key = webpush.generate_vapid_keys()
    assert webpush.vapid_problem(public_key, private_key, "mailto:equipe@coges.example") is None
    headers = webpush.vapid_headers(
        "https://fcm.googleapis.com/fcm/send/abc",
        private_key=private_key,
        subject="mailto:equipe@coges.example",
    )
    scheme, params = headers["Authorization"].split(" ", 1)
    fields = dict(part.split("=", 1) for part in params.split(","))
    assert scheme == "vapid"
    assert fields["k"] == public_key
    point = webpush.b64url_decode(public_key)
    assert point is not None
    verifier = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), point)
    claims = jwt.decode(
        fields["t"], verifier, algorithms=["ES256"], audience="https://fcm.googleapis.com"
    )
    assert claims["sub"] == "mailto:equipe@coges.example"


def test_a_wrong_vapid_pair_is_named() -> None:
    public_key, private_key = webpush.generate_vapid_keys()
    other, _ = webpush.generate_vapid_keys()
    assert "ne correspond pas" in str(webpush.vapid_problem(other, private_key, "mailto:a@b.c"))
    assert "32 octets" in str(webpush.vapid_problem(public_key, "court", "mailto:a@b.c"))
    assert "mailto" in str(webpush.vapid_problem(public_key, private_key, "equipe@b.c"))
