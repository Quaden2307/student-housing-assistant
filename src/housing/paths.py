"""Repo-anchored file locations.

Everything that reads or writes under the repository (the unit schema, ``data/``,
the SQLite database) goes through this module so notebooks, scripts and tests
agree on where things live no matter which directory they run from.

The data locations can be overridden with environment variables, which is how
tests point at a temporary directory:

- ``HOUSING_DATA_DIR``: replaces ``<repo>/data``.
- ``HOUSING_DB_PATH``: replaces ``<data dir>/housing.db``.
"""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT: Path = Path(__file__).resolve().parents[2]
"""The repository root: the directory that holds ``pyproject.toml`` and ``HANDOFF.md``."""

SCHEMA_PATH: Path = REPO_ROOT / "schema" / "unit_schema.yaml"
"""The unit schema contract (HANDOFF section 3)."""


def data_dir() -> Path:
    """Return the data directory (``<repo>/data`` unless ``HOUSING_DATA_DIR`` is set)."""
    override = os.environ.get("HOUSING_DATA_DIR")
    return Path(override) if override else REPO_ROOT / "data"


def raw_dir() -> Path:
    """Return the directory for gzipped raw responses, ``<data dir>/raw``."""
    return data_dir() / "raw"


def db_path() -> Path:
    """Return the SQLite database path.

    ``<data dir>/housing.db`` unless ``HOUSING_DB_PATH`` is set.
    """
    override = os.environ.get("HOUSING_DB_PATH")
    return Path(override) if override else data_dir() / "housing.db"
