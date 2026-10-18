"""Imports : fichiers piégés, nombres ambigus, en-têtes doublés, recherche (P2.22, P2.23).

* Un .xlsx est un zip : quelques Ko qui se décompressent en Go (« bombe ») épuisaient la
  mémoire avant même la lecture des cellules. Taille décompressée et rapport bornés
  avant `load_workbook` ; colonnes et longueur de cellule bornées ensuite.
* « 1.500 » et « 1,500 » devenaient 1,5 en silence : mille cinq cents en français, un
  et demi en anglais. Un seul séparateur suivi d'exactement trois chiffres est ambigu,
  la ligne est rejetée avec un message clair.
* Deux colonnes du même nom : la seconde écrasait la première sans rien dire.
* Repli Windows-1252 : les octets que ce codage ne connaît pas devenaient « � ».
* `?search=%00` : le caractère NUL partait jusqu'à PostgreSQL, qui le refuse (500).
"""

from __future__ import annotations

import io
import zipfile

import pytest

from app.core.search import normalise_term
from app.modules.importexport import importers, tabular


def _zip(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def test_a_zip_bomb_is_refused_before_it_is_opened(monkeypatch: pytest.MonkeyPatch) -> None:
    """40 Mo de zéros tiennent en quelques dizaines de Ko : refusé sans les décompresser."""
    bomb = _zip({"xl/worksheets/sheet1.xml": b"\0" * (40 * 1024 * 1024)})
    assert len(bomb) < 200_000

    opened: list[int] = []
    monkeypatch.setattr(
        "openpyxl.load_workbook",
        lambda *a, **k: opened.append(1) or (_ for _ in ()).throw(AssertionError()),
    )
    with pytest.raises(tabular.UnreadableFileError, match="décompress"):
        tabular.read_table(bomb, max_rows=10)
    assert opened == [], "le zip a été ouvert par openpyxl"


def test_an_absurd_compression_ratio_is_refused() -> None:
    small_but_dense = _zip({"xl/worksheets/sheet1.xml": b"a" * (5 * 1024 * 1024)})
    with pytest.raises(tabular.UnreadableFileError):
        tabular.read_table(small_but_dense, max_rows=10)


def test_a_huge_cell_is_refused() -> None:
    content = ("Nom;Prix de vente\n" + "x" * 5000 + ";1000\n").encode()
    with pytest.raises(tabular.UnreadableFileError, match="caractères"):
        tabular.read_table(content, max_rows=10)


def test_too_many_columns_are_refused() -> None:
    header = ";".join(f"c{i}" for i in range(300))
    with pytest.raises(tabular.UnreadableFileError, match="colonnes"):
        tabular.read_table(f"{header}\n".encode(), max_rows=10)


@pytest.mark.parametrize("value", ["1.500", "1,500", "12.500", "999,000"])
def test_one_separator_and_three_digits_is_ambiguous(value: str) -> None:
    with pytest.raises(ValueError, match="Écrivez 1500"):
        importers.number_text(value)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("1500", "1500"),
        ("1 500", "1500"),
        ("1,5", "1.5"),
        ("1.234,50", "1234.50"),
        ("12.50", "12.50"),
    ],
)
def test_unambiguous_numbers_still_read(value: str, expected: str) -> None:
    assert importers.number_text(value) == expected


def test_duplicate_headers_are_an_error() -> None:
    content = b"Nom;Prix de vente;Nom\nRiz;1000;Huile\n"
    with pytest.raises(tabular.UnreadableFileError, match="deux fois"):
        tabular.read_table(content, max_rows=10)


def test_a_file_that_is_neither_utf8_nor_cp1252_is_reported() -> None:
    """0x81 n'existe pas en Windows-1252 : on le dit au lieu d'écrire « � »."""
    content = b"Nom;Prix de vente\nRiz \x81;1000\n"
    with pytest.raises(tabular.UnreadableFileError, match="Windows-1252"):
        tabular.read_table(content, max_rows=10)


def test_a_cp1252_file_still_reads() -> None:
    table = tabular.read_table("Nom;Prix de vente\nCafé;1000\n".encode("cp1252"), max_rows=10)
    assert table.rows[0].cells["nom"] == "Café"


@pytest.mark.parametrize("raw", ["\x00", "ri\x00z", "\x07\x1b[2J"])
def test_control_characters_never_reach_the_search(raw: str) -> None:
    term = normalise_term(raw)
    assert term is None or not any(ord(char) < 32 for char in term)
