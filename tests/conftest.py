"""Shared test setup."""

import pytest


@pytest.fixture(autouse=True)
def _test_salt(monkeypatch):
    # hash_id refuses to run without a salt (a known salt makes poster hashes reversible).
    monkeypatch.setenv("HOUSING_HASH_SALT", "test-salt")


@pytest.fixture(autouse=True)
def _instant_network(monkeypatch):
    # The daily CLI waits for DNS before running; tests never do real lookups.
    monkeypatch.setattr("housing.scrape.daily.wait_for_network", lambda *a, **k: True)
