"""LightGBM price model, v1 (HANDOFF section 7): expected price plus a fairness verdict.

    uv run python -m housing.model.lgbm [--db data/housing.db] [--splits 5] [--archive]
                                        [--save data/models/lgbm_v1.joblib]

An experiment on its own branch, not the agreed model. It trains LightGBM on
``log(price_per_bedroom)`` with the same tier A inputs as the baselines (``FEATURES``), and
turns one prediction into the section 2 output: expected price, the 10th to 90th
percentile range, the asking price's percentile, the band, the gap, the top three drivers
and a confidence block.

The range and percentile are v1 as HANDOFF describes it: the empirical distribution of
out-of-fold log residuals from grouped cross-validation, the same for every unit. Section
2's margin rule is applied: a gap no larger than the held-out MAE is ``FAIR`` and flagged
``within_margin``, whatever its percentile.

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
from housing.model.evaluate import GROUP, TARGET, grouped_cv, score, summarize, time_split

# Section 2 thresholds on price_percentile; tuned after calibration.
GOOD_DEAL_MAX = 25.0
OVERPRICED_MIN = 75.0
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
    """

    params: dict[str, Any] = field(default_factory=lambda: dict(DEFAULT_PARAMS))
    n_splits: int = 5
    booster: lgb.LGBMRegressor | None = None
    categories: dict[str, list[str]] = field(default_factory=dict)
    residuals: np.ndarray = field(default_factory=lambda: np.empty(0))
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
        self.residuals = np.sort(np.log(y) - oof)
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

    def percentile(self, log_gap: float) -> float:
        """Share of held-out residuals at or below ``log(asking / expected)``, 0 to 100."""
        return (
            float(np.searchsorted(self.residuals, log_gap, side="right"))
            / len(self.residuals)
            * 100.0
        )

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
        lo, hi = np.quantile(self.residuals, [0.10, 0.90])
        all_drivers = self.drivers(x)
        verdicts = []
        for i in range(len(x)):
            gap = asking[i] - expected[i]
            pct = self.percentile(float(np.log(asking[i] / expected[i])))
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


def range_coverage(train: pd.DataFrame, test: pd.DataFrame, n_splits: int = 5) -> float:
    """Share of ``test`` asking prices inside the 10 to 90 range of a model fit on ``train``.

    HANDOFF section 7 wants about 80 percent on held-out data.
    """
    model = PriceModel(n_splits=n_splits).fit(train)
    expected = model.predict(test)
    lo, hi = np.quantile(model.residuals, [0.10, 0.90])
    y = test[TARGET].to_numpy(dtype=float)
    inside = (y >= expected * np.exp(lo)) & (y <= expected * np.exp(hi))
    return float(inside.mean())


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
    args = parser.parse_args(argv)

    conn = connect(args.db)
    try:
        df, report = load_training(conn, include_archive=args.archive)
    finally:
        conn.close()
    print(report)
    if df.empty:
        print("no training rows after cleaning; nothing to evaluate")
        return 1
    df = df.reset_index(drop=True)

    try:
        split: tuple[pd.DataFrame, pd.DataFrame] | None = time_split(df)
    except ValueError as err:
        split = None
        print(f"time split skipped: {err}")

    print(f"\n{f'grouped {args.splits}-fold CV':<44} time split")
    for name, fit_predict in (
        ("lookup", fit_predict_lookup),
        ("ridge", fit_predict_ridge),
        ("lightgbm", fit_predict_lgbm),
    ):
        cv_text = summarize(name, grouped_cv(df, fit_predict, n_splits=args.splits))
        time_text = ""
        if split is not None:
            train, test = split
            preds = np.asarray(fit_predict(train, test), dtype=float)
            time_text = str(score(test[TARGET].to_numpy(dtype=float), preds))
        print(f"{cv_text.removeprefix(f'{name}: '):<44} {time_text}  [{name}]")

    model = PriceModel(n_splits=args.splits).fit(df)
    lo, hi = np.quantile(model.residuals, [0.10, 0.90])
    print(
        f"\nheld-out residual range (10th to 90th): {np.expm1(lo):+.1%} to {np.expm1(hi):+.1%}"
        f" of expected; MAE ${model.mae:,.0f}, MAPE {model.mape:.1f}%"
    )
    if split is not None:
        print(f"10-90 range coverage on the time split: {range_coverage(*split):.1%} (target 80%)")

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
