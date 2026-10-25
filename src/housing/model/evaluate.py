"""Evaluation harness for the price model (HANDOFF section 7).

Cross-validation groups by ``dedup_key`` with ``GroupKFold`` so the model cannot memorise a
house that reposted under several ad ids, and a time split by ``first_seen`` checks drift.
Errors are reported in dollars (MAE) and percent (MAPE), because a $100 miss on a $600 room
and on a $2,500 unit are not the same error.

Used by ``housing.model.baseline`` (the lookup and ridge baselines) and later by the real
model's training and error-analysis notebooks.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.model_selection import GroupKFold

# The training-table contract has one home, housing.model.dataset; re-exported here so
# harness callers can keep importing GROUP and TARGET from the module they already use.
from housing.model.dataset import GROUP, TARGET

# A fold callback: fit on the first frame, return dollar predictions for the second.
FitPredict = Callable[[pd.DataFrame, pd.DataFrame], np.ndarray]


@dataclass(frozen=True)
class Metrics:
    """Held-out error on one evaluation fold.

    Attributes:
        n: Number of held-out rows scored.
        mae: Mean absolute error in dollars per bedroom per month.
        mape: Mean absolute percentage error, in percent (12.5 means 12.5%).
    """

    n: int
    mae: float
    mape: float

    def __str__(self) -> str:
        return f"MAE ${self.mae:,.0f}, MAPE {self.mape:.1f}% (n={self.n})"


def score(y_true: np.ndarray, y_pred: np.ndarray) -> Metrics:
    """Score dollar predictions against dollar targets.

    Rows whose target is exactly zero are excluded from the MAPE (division by zero); the
    cleaning rules in docs/pipeline.md section 4 keep ``price_per_bedroom`` at $300 or more,
    so after cleaning no such row exists and the guard is belt-and-braces only.

    Args:
        y_true: Actual ``price_per_bedroom`` values in dollars.
        y_pred: Predicted values in dollars, same length.

    Returns:
        A ``Metrics`` with MAE in dollars and MAPE in percent over all rows.

    Raises:
        ValueError: If the two arrays differ in shape.
    """
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    if y_true.shape != y_pred.shape:
        raise ValueError(f"shape mismatch: y_true {y_true.shape} vs y_pred {y_pred.shape}")
    err = np.abs(y_true - y_pred)
    nonzero = y_true != 0
    mape = (
        float(np.mean(err[nonzero] / np.abs(y_true[nonzero])) * 100)
        if nonzero.any()
        else float("nan")
    )
    return Metrics(n=int(y_true.size), mae=float(err.mean()), mape=mape)


def grouped_cv(df: pd.DataFrame, fit_predict: FitPredict, n_splits: int = 5) -> list[Metrics]:
    """Cross-validate a model with ``GroupKFold`` over ``dedup_key``.

    Grouping by ``dedup_key`` keeps every repost of one unit on the same side of a fold, so
    the model is always scored on addresses it never saw (HANDOFF section 7). When the frame
    holds fewer distinct keys than ``n_splits``, the split count is lowered to the key count,
    since ``GroupKFold`` cannot make more folds than groups.

    Args:
        df: Training table with ``dedup_key``, ``price_per_bedroom`` and feature columns.
        fit_predict: Callback fitting on the train frame and returning dollar predictions
            for the test frame, one per row.
        n_splits: Requested fold count; lowered to the number of distinct keys if needed.

    Returns:
        One ``Metrics`` per fold, in fold order.

    Raises:
        ValueError: If any row's ``dedup_key`` is missing (``GroupKFold`` cannot place
            it), or the frame holds fewer than two distinct ``dedup_key`` values, so
            nothing can be held out.
    """
    if df[GROUP].isna().any():
        # Fail with a message that names the fix; sklearn would only say "Input contains NaN".
        raise ValueError(
            f"grouped CV needs a non-null {GROUP} on every row; load_training gives"
            " keyless rows a 'listing:<id>' sentinel, so pass its frame or fill the"
            " keys first (uv run python -m housing.features.dedup)"
        )
    n_groups = int(df[GROUP].nunique())
    if n_groups < 2:
        raise ValueError(f"grouped CV needs at least 2 distinct {GROUP} values, got {n_groups}")
    folds: list[Metrics] = []
    for train_idx, test_idx in GroupKFold(n_splits=min(n_splits, n_groups)).split(
        df, groups=df[GROUP]
    ):
        train_df, test_df = df.iloc[train_idx], df.iloc[test_idx]
        preds = np.asarray(fit_predict(train_df, test_df), dtype=float)
        folds.append(score(test_df[TARGET].to_numpy(dtype=float), preds))
    return folds


def time_split(df: pd.DataFrame, test_fraction: float = 0.25) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split between distinct ``first_seen`` values so the newest rows form the test set.

    This is the drift check from HANDOFF section 7 — train on listings seen first, score on
    the ones that arrived later — not a second cross-validation: it is a single ordered split
    reported beside the grouped CV. ``first_seen`` is ISO 8601 text, so lexicographic order
    is chronological.

    The cut falls between distinct ``first_seen`` values, never through one: every listing
    in one sweep shares that sweep's timestamp, so a row-count cut would slice such a tie
    block by insert order and the "newest" test set would partly be an arbitrary
    within-sweep split. The cutoff is the distinct timestamp whose test share lands closest
    to ``test_fraction`` (a tie between candidates goes to the older cutoff, the larger
    test set), and every row carrying the cutoff timestamp lands in test.

    Args:
        df: Training table with a ``first_seen`` column.
        test_fraction: Target share of rows (newest first) to hold out; strictly between
            0 and 1. The achieved share is ``len(test) / len(df)`` and can sit far from
            the target when one sweep dominates the frame.

    Returns:
        ``(train, test)`` frames; every row lands in exactly one of them, each side holds
        at least one row, and every train row is strictly older than every test row.

    Raises:
        ValueError: If ``test_fraction`` is not strictly between 0 and 1, the frame has
            fewer than two rows, or every row shares one ``first_seen`` value, which
            makes a time split meaningless.
    """
    if not 0 < test_fraction < 1:
        raise ValueError(f"test_fraction must be in (0, 1), got {test_fraction}")
    if len(df) < 2:
        raise ValueError(f"time split needs at least 2 rows, got {len(df)}")
    ordered = df.sort_values("first_seen", kind="stable")
    stamps = ordered["first_seen"].to_numpy()
    distinct = np.unique(stamps)  # ascending
    if len(distinct) < 2:
        raise ValueError("time split needs at least 2 distinct first_seen values, got 1")
    # Candidate cutoffs: every distinct timestamp but the oldest, so train keeps >= 1 row.
    candidates = distinct[1:]
    test_sizes = np.array([int((stamps >= cutoff).sum()) for cutoff in candidates])
    gaps = np.abs(test_sizes / len(ordered) - test_fraction)
    # argmin takes the first minimum, i.e. the oldest tied cutoff and the larger test set.
    n_test = int(test_sizes[int(np.argmin(gaps))])
    return ordered.iloc[:-n_test], ordered.iloc[-n_test:]


def summarize(name: str, folds: list[Metrics]) -> str:
    """One report line for a model: ``name: MAE $X ± Y, MAPE Z% (n=...)``.

    Args:
        name: Model name to prefix the line with.
        folds: Per-fold metrics, e.g. from :func:`grouped_cv`.

    Returns:
        The line, with X and Z the means over folds, Y the sample standard deviation of the
        fold MAEs (0 for a single fold) and n the total held-out rows across folds.

    Raises:
        ValueError: If ``folds`` is empty.
    """
    if not folds:
        raise ValueError("summarize needs at least one fold")
    maes = np.array([m.mae for m in folds], dtype=float)
    mapes = np.array([m.mape for m in folds], dtype=float)
    spread = float(maes.std(ddof=1)) if len(folds) > 1 else 0.0
    n = sum(m.n for m in folds)
    return f"{name}: MAE ${maes.mean():,.0f} ± {spread:,.0f}, MAPE {mapes.mean():.1f}% (n={n})"
