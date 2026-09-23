"""Fixtures partagées par toutes les suites de tests."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client() -> Iterator[TestClient]:
    """Client HTTP sur l'application FastAPI, sans base de données."""
    with TestClient(app) as test_client:
        yield test_client
