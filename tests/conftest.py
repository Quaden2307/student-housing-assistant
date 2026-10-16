"""Shared test setup."""

import pytest


@pytest.fixture(autouse=True)
def _test_salt(monkeypatch):
    # hash_id refuses to run without a salt (a known salt makes poster hashes reversible).
    monkeypatch.setenv("HOUSING_HASH_SALT", "test-salt")
