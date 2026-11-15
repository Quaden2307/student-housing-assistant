"""Tests for the LightGBM v1 price model on hand-built contract frames."""

import numpy as np
import pandas as pd
import pytest

from housing.model.baseline import FEATURES
from housing.model.lgbm import (
    OOD_MIN,
    PriceModel,
    fit_predict_lgbm,
    haversine_m_vec,
    learn_categories,
    to_lgbm_frame,
)
from tests.test_baseline import make_frame

SMALL = {"n_estimators": 60, "learning_rate": 0.1, "min_child_samples": 5, "verbose": -1}


def priced_frame(n=240, seed=0):
    """Rooms cheaper than 1beds cheaper than 2beds, furnished +$80, plus noise."""
    rng = np.random.default_rng(seed)
    base = {"room": 800.0, "1bed": 1600.0, "2bed": 1100.0}
    unit_type = [["room", "1bed", "2bed"][i % 3] for i in range(n)]
    furnished = [i % 3 == 0 for i in range(n)]
    target = [
        base[u] + (80.0 if f else 0.0) + rng.normal(0, 30)
        for u, f in zip(unit_type, furnished, strict=True)
    ]
    df = make_frame(n, target=target, unit_type=unit_type)
    df["furnished"] = pd.array(furnished, dtype="boolean")
    df["lat"] = 43.47 + rng.normal(0, 0.005, n)
    df["lon"] = -80.54 + rng.normal(0, 0.005, n)
    return df


def test_to_lgbm_frame_types_and_unseen_levels():
    df = priced_frame(30)
    cats = learn_categories(df)
    test = df.head(2).copy()
    test["neighbourhood"] = pd.array(["ZZZ", None], dtype="str")
    out = to_lgbm_frame(test, cats)
    assert list(out.columns) == FEATURES
    assert out["neighbourhood"].isna().all()  # unseen level and NA both go missing
    assert str(out["unit_type"].dtype) == "category"
    assert out["furnished"].dtype == "float64"
    assert np.isnan(to_lgbm_frame(df, cats)["internet_included"].iloc[0])


def test_fit_predict_learns_the_unit_type_effect():
    df = priced_frame()
    preds = fit_predict_lgbm(df.iloc[:180], df.iloc[180:])
    actual = df["price_per_bedroom"].to_numpy()[180:]
    assert np.mean(np.abs(preds - actual)) < 100


def test_fit_collects_out_of_fold_residuals():
    df = priced_frame()
    model = PriceModel(params=SMALL).fit(df)
    assert len(model.residuals) == len(df)
    assert np.all(np.diff(model.residuals) >= 0)
    assert 0 < model.mae < 150
    assert len(model.oof_pred) == len(df)


def test_verdict_bands_and_margin_rule():
    df = priced_frame()
    model = PriceModel(params=SMALL).fit(df)
    row = df.iloc[[0]]
    expected = float(model.predict(row)[0])
    cheap, fair, dear = model.verdict(
        pd.concat([row] * 3), [expected * 0.6, expected, expected * 1.6]
    )
    assert cheap.band == "GOOD_DEAL" and cheap.price_percentile <= 25
    assert dear.band == "OVERPRICED" and dear.price_percentile >= 75
    assert fair.band == "FAIR" and fair.within_margin
    assert fair.range_low < fair.expected < fair.range_high
    assert dear.gap_dollars > 0 and dear.gap_percent == pytest.approx(60, abs=0.2)
    assert len(dear.drivers) == 3
    assert dear.drivers[0].feature == "unit_type"


def test_gap_inside_mae_is_fair_even_at_an_extreme_percentile():
    df = priced_frame()
    model = PriceModel(params=SMALL).fit(df)
    model.residuals = np.zeros(100)  # every held-out residual exactly 0
    row = df.iloc[[0]]
    expected = float(model.predict(row)[0])
    (v,) = model.verdict(row, [expected + model.mae / 2])
    assert v.price_percentile == 100.0
    assert v.band == "FAIR" and v.within_margin


def test_similar_count_and_ood_flag():
    df = priced_frame()
    model = PriceModel(params=SMALL).fit(df)
    near = df.iloc[[0]]
    (v,) = model.verdict(near, [float(near["price_per_bedroom"].iloc[0])])
    assert v.similar_within_1_5km >= OOD_MIN and not v.out_of_distribution
    far = near.copy()
    far["lat"], far["lon"] = 43.25, -79.87  # Hamilton
    (v,) = model.verdict(far, [1000.0])
    assert v.similar_within_1_5km == 0 and v.out_of_distribution
    nowhere = near.copy()
    nowhere["lat"] = np.nan
    (v,) = model.verdict(nowhere, [1000.0])
    assert v.similar_within_1_5km is None and v.out_of_distribution is None


def test_confidence_unknown_when_training_frame_has_no_coordinates():
    df = priced_frame().drop(columns=["lat", "lon"])
    model = PriceModel(params=SMALL).fit(df)
    row = priced_frame().iloc[[0]]  # the listing itself has coordinates
    (v,) = model.verdict(row, [1000.0])
    assert v.similar_within_1_5km is None and v.out_of_distribution is None


def test_save_and_load_round_trip(tmp_path):
    df = priced_frame()
    model = PriceModel(params=SMALL).fit(df)
    path = tmp_path / "m.joblib"
    model.save(path)
    loaded = PriceModel.load(path)
    np.testing.assert_allclose(loaded.predict(df.head(5)), model.predict(df.head(5)))


def test_unfitted_model_raises():
    with pytest.raises(RuntimeError):
        PriceModel().predict(priced_frame(3))


def test_haversine_matches_one_degree_of_latitude():
    d = haversine_m_vec(43.0, -80.0, np.array([44.0]), np.array([-80.0]))
    assert d[0] == pytest.approx(111_195, rel=1e-3)
