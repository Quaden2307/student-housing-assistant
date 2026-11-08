"""The two baselines the model must beat (HANDOFF section 7), in order.

    uv run python -m housing.model.baseline [--db data/housing.db] [--splits 5]

(1) ``MedianLookup``: the median ``price_per_bedroom`` by (neighbourhood, unit_type) — the
lookup table from HANDOFF section 1 that the real model has to beat to count as ML. (2)
``make_ridge``: ridge regression on one-hot categoricals plus imputed numerics, trained on
the log target. The CLI prints grouped-CV and time-split errors for both. It only reads the
database; predictions are never stored (the ``predictions`` table is for the real model).
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Self

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer, TransformedTargetRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import FunctionTransformer, OneHotEncoder

from housing.db import connect
from housing.model.dataset import BOOLEANS, CATEGORICALS, NUMERICS, load_training
from housing.model.evaluate import GROUP, TARGET, grouped_cv, score, summarize, time_split

# The only columns a baseline may read at predict time. Never the asking price, the target,
# ids, dedup keys or timestamps: the app cannot supply those for a pasted listing, and the
# price columns would be leakage (docs/pipeline.md section 4, tier A only).
FEATURES: list[str] = [*CATEGORICALS, *NUMERICS, *BOOLEANS]


def _key(value: object) -> str:
    """Normalize one categorical value to a dict key, mapping NA to ``"missing"``."""
    return "missing" if pd.isna(value) else str(value)


@dataclass
class MedianLookup:
    """Median ``price_per_bedroom`` by (neighbourhood, unit_type), with fallbacks.

    Prediction for a row tries, in order: the (neighbourhood, unit_type) median, the
    unit_type median, the global median. Missing values group under the key ``"missing"``,
    so a row with no neighbourhood still gets that group's own median when one was learned.

    Attributes:
        by_pair: Median target by (neighbourhood, unit_type), keys normalized by ``_key``.
        by_unit_type: Median target by unit_type alone.
        global_median: Median target over the whole training frame.
    """

    by_pair: dict[tuple[str, str], float] = field(default_factory=dict)
    by_unit_type: dict[str, float] = field(default_factory=dict)
    global_median: float = float("nan")

    def fit(self, train_df: pd.DataFrame) -> Self:
        """Learn the three median tables from a training frame.

        Args:
            train_df: Frame with ``neighbourhood``, ``unit_type`` and the target column.

        Returns:
            Self, fitted.
        """
        work = pd.DataFrame(
            {
                "neigh": train_df["neighbourhood"].map(_key),
                "ut": train_df["unit_type"].map(_key),
                "y": train_df[TARGET].astype(float),
            }
        )
        self.by_pair = work.groupby(["neigh", "ut"])["y"].median().to_dict()
        self.by_unit_type = work.groupby("ut")["y"].median().to_dict()
        self.global_median = float(work["y"].median())
        return self

    def predict(self, test_df: pd.DataFrame) -> np.ndarray:
        """Predict dollars per bedroom for each row, falling back per row as needed.

        Args:
            test_df: Frame with ``neighbourhood`` and ``unit_type`` columns.

        Returns:
            One prediction per row, in row order.
        """
        neighs = test_df["neighbourhood"].map(_key).to_numpy()
        uts = test_df["unit_type"].map(_key).to_numpy()
        out = np.empty(len(test_df), dtype=float)
        for i, (neigh, ut) in enumerate(zip(neighs, uts, strict=True)):
            out[i] = self.by_pair.get((neigh, ut), self.by_unit_type.get(ut, self.global_median))
        return out


def _booleans_to_float(x: pd.DataFrame) -> np.ndarray:
    """Cast nullable-boolean columns to float64: True 1.0, False 0.0, NA NaN.

    Simplest correct handling of missing booleans: the cast keeps NA as NaN and the median
    imputer after it fills in the column's majority value. The hop through ``Float64`` is
    needed because a nullable ``boolean`` column cannot become a float ndarray while it
    still holds NA.
    """
    return pd.DataFrame(x).astype("Float64").to_numpy(dtype="float64", na_value=np.nan)


def make_ridge() -> TransformedTargetRegressor:
    """Build the ridge baseline: one-hot categoricals, imputed numerics, log target.

    Categorical NA is filled with the literal category ``"missing"`` before one-hot
    encoding, and a category unseen in training encodes as all zeros
    (``handle_unknown="ignore"``). Numerics (nullable Int64 included) are median-imputed.
    Booleans are cast to float with NaN for NA, then median-imputed. HANDOFF section 7:
    the target is ``log(price_per_bedroom)``, so the pipeline is wrapped in a
    ``TransformedTargetRegressor`` fitting on ``np.log(y)`` and exponentiating predictions
    back — callers pass dollars in and get dollars out.

    Returns:
        An unfitted estimator: ``fit(X, y_dollars)``, ``predict(X) -> dollars``.
    """
    preprocess = ColumnTransformer(
        transformers=[
            (
                "cat",
                Pipeline(
                    [
                        ("fill", SimpleImputer(strategy="constant", fill_value="missing")),
                        ("onehot", OneHotEncoder(handle_unknown="ignore")),
                    ]
                ),
                CATEGORICALS,
            ),
            ("num", SimpleImputer(strategy="median"), NUMERICS),
            (
                "bool",
                Pipeline(
                    [
                        ("to_float", FunctionTransformer(_booleans_to_float)),
                        ("fill", SimpleImputer(strategy="median")),
                    ]
                ),
                BOOLEANS,
            ),
        ]
    )
    return TransformedTargetRegressor(
        regressor=Pipeline([("prep", preprocess), ("ridge", Ridge(alpha=1.0))]),
        func=np.log,
        inverse_func=np.exp,
    )


def fit_predict_lookup(train: pd.DataFrame, test: pd.DataFrame) -> np.ndarray:
    """Fit the median lookup on ``train`` and predict dollars for ``test`` (CV callback)."""
    return MedianLookup().fit(train).predict(test)


def fit_predict_ridge(train: pd.DataFrame, test: pd.DataFrame) -> np.ndarray:
    """Fit the ridge pipeline on ``train`` and predict dollars for ``test`` (CV callback)."""
    model = make_ridge()
    model.fit(train[FEATURES], train[TARGET].astype(float))
    return np.asarray(model.predict(test[FEATURES]), dtype=float)


def main(argv: list[str] | None = None) -> int:
    """Run both baselines against the clean training table and print their errors.

    Reads the database only; nothing is written back. Predictions are not stored — the
    ``predictions`` table is for the real model's batch scores later (HANDOFF section 8).

    Args:
        argv: CLI arguments, or None for ``sys.argv``.

    Returns:
        0 on success, 1 when the clean table holds no rows to evaluate.
    """
    parser = argparse.ArgumentParser(
        description="Grouped-CV and time-split errors for the lookup and ridge baselines."
    )
    parser.add_argument(
        "--db", type=Path, default=None, help="database file (default: data/housing.db)"
    )
    parser.add_argument("--splits", type=int, default=5, help="grouped CV folds (default 5)")
    parser.add_argument(
        "--archive",
        action="store_true",
        help="also train on the Wayback archive rows (docs/decisions.md 2026-11-06)",
    )
    args = parser.parse_args(argv)

    # housing.db.connect applies the per-connection conventions (foreign keys, WAL,
    # busy_timeout) and the housing.paths default; the schema is expected to exist
    # already because this CLI reads and never migrates.
    conn = connect(args.db)
    try:
        df, report = load_training(conn, include_archive=args.archive)
    finally:
        conn.close()
    print(report)
    if df.empty:
        print("no training rows after cleaning; nothing to evaluate")
        return 1
    # Keyless rows carry the per-row sentinel, which groups honestly but can't link a
    # repost to its other ads; stale keys mean the dedup CLI has not run since the sweep.
    sentinels = int(df[GROUP].str.startswith("listing:").sum())
    if sentinels:
        print(
            f"note: {sentinels} rows have no dedup_key and group as their own units;"
            " run `uv run python -m housing.features.dedup` first for honest grouping"
        )

    try:
        split = time_split(df)
        time_header = f"time split (newest {len(split[1]) / len(df):.0%})"
    except ValueError as err:
        # One sweep's rows all share a first_seen; CV still stands on its own.
        split = None
        time_header = "time split"
        time_note = f"skipped: {err}"

    rows = []
    for name, fit_predict in (("lookup", fit_predict_lookup), ("ridge", fit_predict_ridge)):
        folds = grouped_cv(df, fit_predict, n_splits=args.splits)
        cv_text = summarize(name, folds).removeprefix(f"{name}: ")
        if split is None:
            time_text = time_note
        else:
            train, test = split
            held_out = test[TARGET].to_numpy(dtype=float)
            time_text = str(score(held_out, np.asarray(fit_predict(train, test), dtype=float)))
        rows.append((name, cv_text, time_text))

    n_folds = min(args.splits, int(df[GROUP].nunique()))
    width = max(len(cv_text) for _, cv_text, _ in rows)
    print(f"{'baseline':<10} {f'grouped {n_folds}-fold CV':<{width}} {time_header}")
    for name, cv_text, time_text in rows:
        print(f"{name:<10} {cv_text:<{width}} {time_text}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
