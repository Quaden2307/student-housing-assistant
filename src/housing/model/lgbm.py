"""LightGBM price model, v1 (HANDOFF section 7): expected price plus a fairness verdict.

    uv run python -m housing.model.lgbm [--db data/housing.db] [--splits 5] [--archive]
                                        [--save data/models/lgbm_v1.joblib] [--fix-labels]

An experiment on its own branch, not the agreed model. It trains LightGBM on
``log(price_per_bedroom)`` with the same tier A inputs as the baselines (``FEATURES``), and
turns one prediction into the section 2 output: expected price, the 10th to 90th
percentile range, the asking price's percentile, the band, the gap, the top three drivers
and a confidence block.

The range and percentile come from the empirical distribution of out-of-fold log
residuals from grouped cross-validation (HANDOFF section 7, v1), calibrated separately per
unit-type group (Mondrian conformal prediction): rooms are far less predictable than
apartments, and one shared range was too narrow for rooms and too wide for 2-bedrooms.
Groups are ``RANGE_GROUPS``; a group with fewer than ``MIN_GROUP_RESIDUALS`` held-out rows
falls back to the shared range. ``per_type_ranges=False`` restores the single range.
Section 2's margin rule is applied: a gap no larger than the held-out MAE is ``FAIR`` and
flagged ``within_margin``, whatever its percentile.

On macOS LightGBM needs OpenMP: ``brew install libomp``.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Self

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.model_selection import GroupKFold

from housing.db import connect
from housing.model.baseline import FEATURES, fit_predict_lookup, fit_predict_ridge
from housing.model.dataset import BOOLEANS, CATEGORICALS, NUMERICS, load_training
from housing.model.evaluate import (
    GROUP,
    TARGET,
    Metrics,
    grouped_cv,
    score,
    summarize,
    time_split,
)
from housing.model.labels import attach_titles, fix_labels

# Section 2 thresholds on price_percentile; tuned after calibration.
GOOD_DEAL_MAX = 25.0
OVERPRICED_MIN = 75.0
# Unit types calibrated together. Studios (about 70 archive rows) share the 1-bed range and
# houses share the 3+ bedroom range: each group needs enough held-out rows for a stable 10th
# and 90th percentile.
RANGE_GROUPS: dict[str, str] = {
    "room": "room",
    "studio": "studio_1bed",
    "1bed": "studio_1bed",
    "2bed": "2bed",
    "3plus": "3plus_house",
    "house": "3plus_house",
}
SHARED_GROUP = "all"
MIN_GROUP_RESIDUALS = 100


def range_group(unit_type: object) -> str:
    """The calibration group for a unit type (``SHARED_GROUP`` when unknown)."""
    if unit_type is None or pd.isna(unit_type):
        return SHARED_GROUP
    return RANGE_GROUPS.get(str(unit_type), SHARED_GROUP)


# Section 2 confidence: similar listings within this radius; fewer than OOD_MIN is OOD.
SIMILAR_RADIUS_M = 1500.0
OOD_MIN = 10

DEFAULT_PARAMS: dict[str, Any] = {
    "n_estimators": 400,
    "learning_rate": 0.03,
    "num_leaves": 15,
    "min_child_samples": 20,
    "subsample": 0.8,
    "subsample_freq": 1,
    "colsample_bytree": 0.8,
    "reg_lambda": 1.0,
    "random_state": 0,
    "verbose": -1,
}
"""Small, regularised trees: the table is a few thousand rows. Untuned."""


def to_lgbm_frame(x: pd.DataFrame, categories: dict[str, list[str]]) -> pd.DataFrame:
    """Convert contract columns to what LightGBM reads: category, float, float.

    Categoricals become pandas ``category`` with the training categories fixed, so a
    level unseen in training becomes NA (LightGBM's missing branch) rather than shifting
    the codes. Nullable booleans become 1.0 / 0.0 / NaN; LightGBM learns where NaN goes.

    Args:
        x: Frame holding at least the ``FEATURES`` columns.
        categories: Training levels per categorical column, from :func:`learn_categories`.

    Returns:
        A new frame with exactly the ``FEATURES`` columns, in order.
    """
    out = pd.DataFrame(index=x.index)
    for col in CATEGORICALS:
        known = set(categories[col])
        values = [str(v) if pd.notna(v) and str(v) in known else None for v in x[col]]
        out[col] = pd.Categorical(values, categories=categories[col])
    for col in NUMERICS:
        out[col] = pd.to_numeric(x[col], errors="coerce").astype("float64")
    for col in BOOLEANS:
        out[col] = x[col].astype("Float64").to_numpy(dtype="float64", na_value=np.nan)
    return out[FEATURES]


def learn_categories(train: pd.DataFrame) -> dict[str, list[str]]:
    """The sorted non-null levels of each categorical column in the training frame."""
    return {col: sorted(str(v) for v in train[col].dropna().unique()) for col in CATEGORICALS}


def _fit_booster(train: pd.DataFrame, params: dict[str, Any]) -> tuple[lgb.LGBMRegressor, dict]:
    categories = learn_categories(train)
    model = lgb.LGBMRegressor(**params)
    model.fit(to_lgbm_frame(train, categories), np.log(train[TARGET].to_numpy(dtype=float)))
    return model, categories


def fit_predict_lgbm(train: pd.DataFrame, test: pd.DataFrame) -> np.ndarray:
    """Fit LightGBM on ``train`` and predict dollars for ``test`` (CV callback)."""
    model, categories = _fit_booster(train, DEFAULT_PARAMS)
    return np.exp(model.predict(to_lgbm_frame(test, categories)))


def haversine_m_vec(lat: float, lon: float, lats: np.ndarray, lons: np.ndarray) -> np.ndarray:
    """Great-circle metres from one point to many (vectorised ``geo.distances.haversine_m``)."""
    r = 6_371_000.0
    p1, p2 = np.radians(lat), np.radians(lats)
    dphi, dlmb = p2 - p1, np.radians(lons - lon)
    a = np.sin(dphi / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dlmb / 2) ** 2
    return 2 * r * np.arcsin(np.sqrt(a))


@dataclass(frozen=True)
class Driver:
    """One SHAP contribution, in dollars off the expected price.

    Attributes:
        feature: Input column name.
        value: The listing's value for it (None when missing).
        dollars: Signed effect on ``expected``; the app renders it in words.
    """

    feature: str
    value: Any
    dollars: float


@dataclass(frozen=True)
class Verdict:
    """The section 2 output for one listing. Dollars are per bedroom per month.

    ``similar_within_1_5km`` and ``out_of_distribution`` are None (unknown) when either the
    listing or the training frame has no coordinates. ``load_training`` does not carry
    ``lat``/``lon`` today, so models fit on its frame always report them as unknown.
    """

    expected: float
    range_low: float
    range_high: float
    range_group: str
    asking: float
    price_percentile: float
    band: str
    within_margin: bool
    gap_dollars: float
    gap_percent: float
    drivers: list[Driver]
    similar_within_1_5km: int | None
    model_mae: float
    out_of_distribution: bool | None

    def as_dict(self) -> dict[str, Any]:
        """Plain dict, drivers included, for JSON or the ``predictions`` table later."""
        return asdict(self)


@dataclass
class PriceModel:
    """LightGBM on the log target with grouped-CV residuals for the range and percentile.

    Attributes:
        params: LightGBM parameters (``DEFAULT_PARAMS`` unless overridden).
        n_splits: Grouped CV folds used to collect out-of-fold residuals.
        per_type_ranges: Calibrate the range and percentile per ``RANGE_GROUPS`` group
            (default) instead of one shared distribution.
    """

    params: dict[str, Any] = field(default_factory=lambda: dict(DEFAULT_PARAMS))
    n_splits: int = 5
    per_type_ranges: bool = True
    booster: lgb.LGBMRegressor | None = None
    categories: dict[str, list[str]] = field(default_factory=dict)
    residuals: np.ndarray = field(default_factory=lambda: np.empty(0))
    residuals_by_group: dict[str, np.ndarray] = field(default_factory=dict)
    oof_pred: np.ndarray = field(default_factory=lambda: np.empty(0))
    mae: float = float("nan")
    mape: float = float("nan")
    _train_points: pd.DataFrame = field(default_factory=pd.DataFrame)

    def fit(self, df: pd.DataFrame) -> Self:
        """Collect out-of-fold residuals by grouped CV, then fit on every row.

        Args:
            df: The clean training table from ``load_training``.

        Returns:
            self, fitted.

        Raises:
            ValueError: If the frame has fewer than two distinct ``dedup_key`` values.
        """
        n_groups = int(df[GROUP].nunique())
        if n_groups < 2:
            raise ValueError(f"need at least 2 distinct {GROUP} values, got {n_groups}")
        y = df[TARGET].to_numpy(dtype=float)
        oof = np.full(len(df), np.nan)
        splitter = GroupKFold(n_splits=min(self.n_splits, n_groups))
        for train_idx, test_idx in splitter.split(df, groups=df[GROUP]):
            model, cats = _fit_booster(df.iloc[train_idx], self.params)
            oof[test_idx] = model.predict(to_lgbm_frame(df.iloc[test_idx], cats))
        self.oof_pred = np.exp(oof)
        resid = np.log(y) - oof
        self.residuals = np.sort(resid)
        groups = np.array([range_group(u) for u in df["unit_type"]])
        self.residuals_by_group = {
            g: np.sort(resid[groups == g])
            for g in np.unique(groups)
            if g != SHARED_GROUP and (groups == g).sum() >= MIN_GROUP_RESIDUALS
        }
        held_out = score(y, np.exp(oof))
        self.mae, self.mape = held_out.mae, held_out.mape
        self.booster, self.categories = _fit_booster(df, self.params)
        cols = [c for c in ("lat", "lon", "unit_type") if c in df.columns]
        self._train_points = df[cols].reset_index(drop=True)
        return self

    def _check_fitted(self) -> lgb.LGBMRegressor:
        if self.booster is None:
            raise RuntimeError("PriceModel is not fitted; call fit() first")
        return self.booster

    def predict(self, x: pd.DataFrame) -> np.ndarray:
        """Expected ``price_per_bedroom`` in dollars, one per row of ``x``."""
        booster = self._check_fitted()
        return np.exp(booster.predict(to_lgbm_frame(x, self.categories)))

    def calibration(self, unit_type: object = None) -> tuple[str, np.ndarray]:
        """The calibration group and its sorted held-out log residuals for a unit type.

        Falls back to the shared distribution when per-type ranges are off, the unit type
        is unknown, or its group had fewer than ``MIN_GROUP_RESIDUALS`` held-out rows.
        """
        group = range_group(unit_type)
        by_group = getattr(self, "residuals_by_group", {})  # models saved before v1.1
        if getattr(self, "per_type_ranges", False) and group in by_group:
            return group, by_group[group]
        return SHARED_GROUP, self.residuals

    def interval(self, unit_type: object = None) -> tuple[float, float]:
        """The 10th and 90th percentile log residuals for a unit type's group."""
        _, resid = self.calibration(unit_type)
        lo, hi = np.quantile(resid, [0.10, 0.90])
        return float(lo), float(hi)

    def percentile(self, log_gap: float, unit_type: object = None) -> float:
        """Share of the group's held-out residuals at or below ``log(asking / expected)``."""
        _, resid = self.calibration(unit_type)
        return float(np.searchsorted(resid, log_gap, side="right")) / len(resid) * 100.0

    def similar_count(self, row: pd.Series) -> int | None:
        """Training listings of the same unit type within 1.5 km; None without coordinates."""
        pts = self._train_points
        if (
            not {"lat", "lon"} <= set(pts.columns)
            or pd.isna(row.get("lat"))
            or pd.isna(row.get("lon"))
        ):
            return None
        mask = pts["lat"].notna() & pts["lon"].notna()
        if "unit_type" in pts.columns and pd.notna(row.get("unit_type")):
            mask &= pts["unit_type"] == row["unit_type"]
        near = pts[mask]
        if near.empty:
            return 0
        dist = haversine_m_vec(
            float(row["lat"]),
            float(row["lon"]),
            near["lat"].to_numpy(dtype=float),
            near["lon"].to_numpy(dtype=float),
        )
        return int((dist <= SIMILAR_RADIUS_M).sum())

    def drivers(self, x: pd.DataFrame, top: int = 3) -> list[list[Driver]]:
        """Top SHAP contributions per row, converted from log space to dollars.

        A contribution ``c`` (log dollars) becomes ``expected * (1 - exp(-c))``: how much
        the expected price would move if that feature's effect were removed.
        """
        booster = self._check_fitted()
        frame = to_lgbm_frame(x, self.categories)
        contrib = booster.predict(frame, pred_contrib=True)[:, :-1]  # last column: bias
        expected = np.exp(booster.predict(frame))
        out: list[list[Driver]] = []
        for i in range(len(frame)):
            dollars = expected[i] * (1 - np.exp(-contrib[i]))
            order = np.argsort(-np.abs(dollars))[:top]
            out.append(
                [
                    Driver(
                        feature=FEATURES[j],
                        value=None if pd.isna(x.iloc[i][FEATURES[j]]) else x.iloc[i][FEATURES[j]],
                        dollars=round(float(dollars[j]), 2),
                    )
                    for j in order
                ]
            )
        return out

    def verdict(self, x: pd.DataFrame, asking: np.ndarray | list[float]) -> list[Verdict]:
        """Score asking prices (per bedroom per month) against the model.

        Args:
            x: One row per listing with the ``FEATURES`` columns (plus ``lat``/``lon`` for
                the similar-listings count, if known).
            asking: The asking ``price_per_bedroom`` for each row.

        Returns:
            One ``Verdict`` per row.
        """
        asking = np.asarray(asking, dtype=float)
        expected = self.predict(x)
        all_drivers = self.drivers(x)
        verdicts = []
        for i in range(len(x)):
            unit_type = x.iloc[i].get("unit_type")
            group, _ = self.calibration(unit_type)
            lo, hi = self.interval(unit_type)
            gap = asking[i] - expected[i]
            pct = self.percentile(float(np.log(asking[i] / expected[i])), unit_type)
            within = abs(gap) <= self.mae
            if within or GOOD_DEAL_MAX < pct < OVERPRICED_MIN:
                band = "FAIR"
            elif pct <= GOOD_DEAL_MAX:
                band = "GOOD_DEAL"
            else:
                band = "OVERPRICED"
            similar = self.similar_count(x.iloc[i])
            verdicts.append(
                Verdict(
                    expected=round(float(expected[i]), 2),
                    range_low=round(float(expected[i] * np.exp(lo)), 2),
                    range_high=round(float(expected[i] * np.exp(hi)), 2),
                    range_group=group,
                    asking=float(asking[i]),
                    price_percentile=round(pct, 1),
                    band=band,
                    within_margin=bool(within),
                    gap_dollars=round(float(gap), 2),
                    gap_percent=round(float(gap / expected[i] * 100), 1),
                    drivers=all_drivers[i],
                    similar_within_1_5km=similar,
                    model_mae=round(self.mae, 2),
                    out_of_distribution=None if similar is None else similar < OOD_MIN,
                )
            )
        return verdicts

    def save(self, path: Path) -> None:
        """Pickle the fitted model with joblib (``data/`` and ``*.joblib`` are gitignored)."""
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self, path)

    @staticmethod
    def load(path: Path) -> PriceModel:
        """Load a model written by :meth:`save`."""
        return joblib.load(path)


def range_coverage(
    train: pd.DataFrame, test: pd.DataFrame, n_splits: int = 5, *, per_type_ranges: bool = True
) -> pd.DataFrame:
    """Coverage of the 10 to 90 range on ``test`` for a model fit on ``train``, by group.

    HANDOFF section 7 wants about 80 percent on held-out data; with per-type ranges that
    should hold in every group, not just on average.

    Returns:
        One row per calibration group plus ``"overall"``: ``n``, ``coverage`` (share inside
        the range), ``below`` and ``above`` (shares under and over it), and
        ``non_fair`` (share a verdict would band GOOD_DEAL or OVERPRICED).
    """
    model = PriceModel(n_splits=n_splits, per_type_ranges=per_type_ranges).fit(train)
    expected = model.predict(test)
    y = test[TARGET].to_numpy(dtype=float)
    rows = []
    for i, unit_type in enumerate(test["unit_type"]):
        lo, hi = model.interval(unit_type)
        log_gap = float(np.log(y[i] / expected[i]))
        pct = model.percentile(log_gap, unit_type)
        flagged = abs(y[i] - expected[i]) > model.mae and not (GOOD_DEAL_MAX < pct < OVERPRICED_MIN)
        rows.append(
            {
                # Report by unit-type group either way, so both modes compare like for like.
                "group": range_group(unit_type),
                "below": log_gap < lo,
                "above": log_gap > hi,
                "non_fair": flagged,
            }
        )
    frame = pd.DataFrame(rows)
    frame["inside"] = ~(frame["below"] | frame["above"])

    def summary(part: pd.DataFrame) -> dict[str, float]:
        return {
            "n": len(part),
            "coverage": part["inside"].mean(),
            "below": part["below"].mean(),
            "above": part["above"].mean(),
            "non_fair": part["non_fair"].mean(),
        }

    table = {g: summary(part) for g, part in frame.groupby("group")}
    table["overall"] = summary(frame)
    return pd.DataFrame(table).T


def grouped_cv_on(
    df: pd.DataFrame, fit_predict: Any, mask: pd.Series, n_splits: int = 5
) -> list[Metrics]:
    """Grouped CV that trains on every row but scores only the held-out rows in ``mask``.

    The product checks Waterloo listings, while the training table also holds other cities
    (docs/decisions.md 2026-11-06): those rows help train, and this scores the product.

    Args:
        df: Training table with ``dedup_key`` and the target.
        fit_predict: CV callback, as for ``evaluate.grouped_cv``.
        mask: Boolean series aligned with ``df``; True rows are scored.
        n_splits: Requested fold count, lowered to the number of distinct keys.

    Returns:
        One ``Metrics`` per fold that held out at least one masked row.
    """
    n_groups = int(df[GROUP].nunique())
    folds: list[Metrics] = []
    for train_idx, test_idx in GroupKFold(n_splits=min(n_splits, n_groups)).split(
        df, groups=df[GROUP]
    ):
        test = df.iloc[test_idx]
        test = test[mask.iloc[test_idx].to_numpy()]
        if test.empty:
            continue
        preds = np.asarray(fit_predict(df.iloc[train_idx], test), dtype=float)
        folds.append(score(test[TARGET].to_numpy(dtype=float), preds))
    return folds


def _report_models(
    df: pd.DataFrame,
    split: tuple[pd.DataFrame, pd.DataFrame] | None,
    n_splits: int,
    mask: pd.Series | None = None,
) -> None:
    """Print grouped-CV and time-split errors for the three models, optionally on a subset."""
    print(f"{f'grouped {n_splits}-fold CV':<44} time split")
    for name, fit_predict in (
        ("lookup", fit_predict_lookup),
        ("ridge", fit_predict_ridge),
        ("lightgbm", fit_predict_lgbm),
    ):
        folds = (
            grouped_cv(df, fit_predict, n_splits=n_splits)
            if mask is None
            else grouped_cv_on(df, fit_predict, mask, n_splits=n_splits)
        )
        cv_text = summarize(name, folds)
        time_text = ""
        if split is not None:
            train, test = split
            if mask is not None:
                test = test[mask.loc[test.index].to_numpy()]
            if not test.empty:
                preds = np.asarray(fit_predict(train, test), dtype=float)
                time_text = str(score(test[TARGET].to_numpy(dtype=float), preds))
        print(f"{cv_text.removeprefix(f'{name}: '):<44} {time_text}  [{name}]")


def main(argv: list[str] | None = None) -> int:
    """Compare LightGBM with both baselines, report calibration and errors, optionally save.

    Args:
        argv: CLI arguments, or None for ``sys.argv``.

    Returns:
        0 on success, 1 when the clean table holds no rows.
    """
    parser = argparse.ArgumentParser(description="LightGBM v1 vs the baselines.")
    parser.add_argument(
        "--db", type=Path, default=None, help="database file (default: data/housing.db)"
    )
    parser.add_argument("--splits", type=int, default=5, help="grouped CV folds (default 5)")
    parser.add_argument(
        "--archive", action="store_true", help="also train on the Wayback archive rows"
    )
    parser.add_argument("--save", type=Path, default=None, help="write the fitted model here")
    parser.add_argument(
        "--fix-labels",
        action="store_true",
        help="relabel room / whole-unit mistakes from the title (housing.model.labels)",
    )
    parser.add_argument(
        "--eval-city",
        default="kitchener-waterloo",
        help="also score only this city's rows when the table holds several (default: KW)",
    )
    args = parser.parse_args(argv)

    conn = connect(args.db)
    label_report = None
    try:
        df, report = load_training(conn, include_archive=args.archive)
        if args.fix_labels and not df.empty:
            df, label_report = fix_labels(attach_titles(conn, df))
            df = df.drop(columns="title")
    finally:
        conn.close()
    print(report)
    if label_report is not None:
        print(label_report)
    if df.empty:
        print("no training rows after cleaning; nothing to evaluate")
        return 1
    df = df.reset_index(drop=True)

    try:
        split: tuple[pd.DataFrame, pd.DataFrame] | None = time_split(df)
    except ValueError as err:
        split = None
        print(f"time split skipped: {err}")

    print("\nall rows:")
    _report_models(df, split, args.splits)
    city_mask = df["city"] == args.eval_city
    scored_city = bool(city_mask.any()) and not bool(city_mask.all())
    if scored_city:
        print(f"\nscored on {args.eval_city} only ({int(city_mask.sum())} rows; trained on all):")
        _report_models(df, split, args.splits, city_mask)

    model = PriceModel(n_splits=args.splits).fit(df)
    print(f"\nheld-out MAE ${model.mae:,.0f}, MAPE {model.mape:.1f}%; 10th to 90th range by group:")
    for group in [*sorted(model.residuals_by_group), SHARED_GROUP]:
        resid = model.residuals_by_group.get(group, model.residuals)
        lo, hi = np.quantile(resid, [0.10, 0.90])
        print(f"  {group:<12} {np.expm1(lo):+.1%} to {np.expm1(hi):+.1%}  (n={len(resid)})")
    if split is not None:
        for label, per_type in (("one shared range", False), ("per-type ranges", True)):
            table = range_coverage(*split, per_type_ranges=per_type)
            print(f"\ntime-split range check, {label} (target: coverage 80% in every group):")
            print(table.to_string(float_format=lambda v: f"{v:.2f}"))
        train, test = split
        city_test = test[city_mask.loc[test.index].to_numpy()]
        if scored_city and not city_test.empty:
            table = range_coverage(train, city_test)
            print(f"\ntime-split range check on {args.eval_city} only, per-type ranges:")
            print(table.to_string(float_format=lambda v: f"{v:.2f}"))

    # Out-of-fold error by segment, from the predictions fit() collected.
    oof_pred = model.oof_pred
    err = pd.DataFrame(
        {
            "unit_type": df["unit_type"].astype("object").fillna("missing"),
            "lease_term": df["lease_term"].astype("object").fillna("missing"),
            "abs_err": np.abs(oof_pred - df[TARGET].to_numpy(dtype=float)),
            "pct_err": np.abs(oof_pred / df[TARGET].to_numpy(dtype=float) - 1) * 100,
        }
    )
    for col in ("unit_type", "lease_term"):
        table = err.groupby(col).agg(
            n=("abs_err", "size"), mae=("abs_err", "mean"), mape=("pct_err", "mean")
        )
        print(f"\nLightGBM out-of-fold error by {col}:")
        print(table.round(1).sort_values("n", ascending=False).to_string())

    importance = pd.Series(model.booster.booster_.feature_importance("gain"), index=FEATURES)
    print("\ntop features by gain:")
    print((importance / importance.sum() * 100).sort_values(ascending=False).head(10).round(1))

    if args.save is not None:
        model.save(args.save)
        print(f"\nsaved model to {args.save}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
