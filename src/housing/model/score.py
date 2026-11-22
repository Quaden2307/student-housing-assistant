"""Batch scoring: one row per active listing in the ``predictions`` table.

    uv run python -m housing.model.score [--db data/housing.db]
                                         [--load data/models/lgbm_v1.joblib]
                                         [--model-version lgbm_v1] [--dry-run]

HANDOFF section 8: "Batch score all active listings after every sweep and write to
``predictions``. The comparables query and the drift check both read from it."

The model is fitted on the deduped clean table, exactly as ``housing.model.lgbm`` reports
it, but the rows scored are every *individual* active ad that passes cleaning: dedup keeps
one ad per unit for training, while the app needs a verdict for the ad a user is looking at.

A listing that was in the model's own training frame is scored against its out-of-fold
prediction rather than the fitted one, so a stored expected price is never the model
recalling the asking price it trained on. A model restored with ``--load`` carries no
out-of-fold predictions for this database's rows, so that run falls back to fitted
predictions for every listing and says so.
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

from housing.db import connect
from housing.model.dataset import TARGET, load_training
from housing.model.lgbm import PriceModel
from housing.scrape.fetch import utc_now_iso

DEFAULT_MODEL_VERSION = "lgbm_v1"
"""Stored in ``predictions.model_version``; part of that table's primary key."""

_UPSERT = """
INSERT INTO predictions
    (listing_id, model_version, expected, q10, q90, percentile, scored_at)
VALUES
    (:listing_id, :model_version, :expected, :q10, :q90, :percentile, :scored_at)
ON CONFLICT(listing_id, model_version) DO UPDATE SET
    expected = excluded.expected,
    q10 = excluded.q10,
    q90 = excluded.q90,
    percentile = excluded.percentile,
    scored_at = excluded.scored_at
"""


def active_ids(conn: sqlite3.Connection) -> set[int]:
    """Ids of listings the sweep still sees.

    Args:
        conn: An open database connection.

    Returns:
        The ``listings.id`` values whose status is ``active``.
    """
    rows = conn.execute("SELECT id FROM listings WHERE status = 'active'")
    return {int(r[0]) for r in rows}


def oof_by_listing(train: pd.DataFrame, model: PriceModel) -> dict[int, float]:
    """Map listing id to the model's out-of-fold prediction for that row.

    Args:
        train: The frame passed to ``PriceModel.fit``, in its original row order.
        model: The fitted model, whose ``oof_pred`` aligns with ``train``.

    Returns:
        ``{listing_id: expected_dollars}``, empty when the model carries no out-of-fold
        predictions (a model restored from disk) or they do not match the frame.
    """
    if len(model.oof_pred) != len(train) or "listing_id" not in train:
        return {}
    ids = train["listing_id"].to_numpy()
    return {
        int(i): float(p)
        for i, p in zip(ids, model.oof_pred, strict=True)
        if not pd.isna(i) and np.isfinite(p)
    }


def score_rows(
    model: PriceModel,
    ads: pd.DataFrame,
    oof: dict[int, float],
    model_version: str,
    scored_at: str,
) -> tuple[list[dict[str, object]], dict[str, int], int]:
    """Score every ad and build the ``predictions`` rows.

    Args:
        model: A fitted model.
        ads: One row per ad to score, carrying ``listing_id``, the ``FEATURES`` columns and
            ``price_per_bedroom`` as the asking price.
        oof: Out-of-fold expected prices by listing id, from ``oof_by_listing``.
        model_version: Value for ``predictions.model_version``.
        scored_at: ISO 8601 timestamp for the whole batch.

    Returns:
        The rows to upsert, a tally of verdict bands, and how many rows used an out-of-fold
        expected price rather than a fitted one.
    """
    if ads.empty:
        return [], {}, 0
    expected = np.array([oof.get(int(i), np.nan) for i in ads["listing_id"]], dtype=float)
    fitted = ~np.isfinite(expected)
    if fitted.any():
        expected[fitted] = model.predict(ads[fitted])

    asking = ads[TARGET].to_numpy(dtype=float)
    verdicts = model.verdict(ads, asking, expected=expected)

    rows: list[dict[str, object]] = []
    bands: dict[str, int] = {}
    for listing_id, v in zip(ads["listing_id"], verdicts, strict=True):
        bands[v.band] = bands.get(v.band, 0) + 1
        rows.append(
            {
                "listing_id": int(listing_id),
                "model_version": model_version,
                "expected": v.expected,
                "q10": v.range_low,
                "q90": v.range_high,
                "percentile": v.price_percentile,
                "scored_at": scored_at,
            }
        )
    return rows, bands, int((~fitted).sum())


def write_predictions(conn: sqlite3.Connection, rows: list[dict[str, object]]) -> int:
    """Upsert scored rows into ``predictions``, replacing this model version's earlier run.

    Args:
        conn: An open database connection.
        rows: Rows from ``score_rows``.

    Returns:
        The number of rows written.
    """
    if not rows:
        return 0
    conn.executemany(_UPSERT, rows)
    conn.commit()
    return len(rows)


def main(argv: list[str] | None = None) -> int:
    """Fit or load the model, score every active listing, and write ``predictions``.

    Args:
        argv: Command-line arguments, or None to read ``sys.argv``.

    Returns:
        0 on success, 1 when there is nothing to train on or nothing active to score.
    """
    parser = argparse.ArgumentParser(description="Batch score active listings.")
    parser.add_argument(
        "--db", type=Path, default=None, help="database file (default: data/housing.db)"
    )
    parser.add_argument(
        "--load", type=Path, default=None, help="score with this saved model instead of fitting"
    )
    parser.add_argument(
        "--save", type=Path, default=None, help="write the freshly fitted model here"
    )
    parser.add_argument(
        "--model-version",
        default=DEFAULT_MODEL_VERSION,
        help=f"value stored in predictions.model_version (default: {DEFAULT_MODEL_VERSION})",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="report what would be written, write nothing"
    )
    args = parser.parse_args(argv)

    conn = connect(args.db)
    train, report = load_training(conn)
    if train.empty:
        print("clean training table is empty; nothing to fit")
        return 1

    if args.load:
        model = PriceModel.load(args.load)
        print(f"loaded {args.load} (no out-of-fold predictions for this database)")
    else:
        print(report)
        model = PriceModel().fit(train)
        print(f"fitted on {len(train)} rows; held-out MAE ${model.mae:,.0f} ({model.mape:.1f}%)")
        if args.save:
            model.save(args.save)
            print(f"saved {args.save}")

    ads, _ = load_training(conn, dedup=False)
    active = active_ids(conn)
    ads = ads[ads["listing_id"].isin(active)].reset_index(drop=True)
    if ads.empty:
        print("no active listings pass cleaning; nothing to score")
        return 1

    oof = {} if args.load else oof_by_listing(train, model)
    rows, bands, n_oof = score_rows(model, ads, oof, args.model_version, utc_now_iso())
    print(
        f"scoring {len(rows)} active listings "
        f"({n_oof} with out-of-fold expected prices, {len(rows) - n_oof} fitted)"
    )

    if args.dry_run:
        print("dry run: nothing written")
    else:
        written = write_predictions(conn, rows)
        print(f"wrote {written} rows to predictions (model_version={args.model_version})")
    for band in ("GOOD_DEAL", "FAIR", "OVERPRICED"):
        if band in bands:
            print(f"  {band.lower():11s} {bands[band]:6d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
