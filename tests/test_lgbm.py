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
    range_coverage,
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


def mixed_noise_frame(n=600, seed=1):
    """Rooms with wide noise (sd 0.25 in log), 2-beds with narrow noise (sd 0.05)."""
    rng = np.random.default_rng(seed)
    unit_type = [["room", "2bed"][i % 2] for i in range(n)]
    base = {"room": 800.0, "2bed": 1100.0}
    sd = {"room": 0.25, "2bed": 0.05}
    target = [base[u] * float(np.exp(rng.normal(0, sd[u]))) for u in unit_type]
    return make_frame(n, target=target, unit_type=unit_type)


def test_per_type_ranges_are_wider_for_noisier_groups():
    model = PriceModel(params=SMALL).fit(mixed_noise_frame())
    room_lo, room_hi = model.interval("room")
    bed_lo, bed_hi = model.interval("2bed")
    assert room_hi - room_lo > 2 * (bed_hi - bed_lo)
    assert model.calibration("room")[0] == "room"
    assert model.calibration("2bed")[0] == "2bed"


def test_small_groups_and_unknown_types_fall_back_to_the_shared_range():
    df = mixed_noise_frame()
    df.loc[df.index[:20], "unit_type"] = "studio"  # 20 rows: under MIN_GROUP_RESIDUALS
    model = PriceModel(params=SMALL).fit(df)
    assert model.calibration("studio")[0] == "all"
    assert model.calibration(None)[0] == "all"
    assert model.calibration("castle")[0] == "all"


def test_same_gap_reads_differently_for_a_room_and_a_2bed():
    df = mixed_noise_frame()
    model = PriceModel(params=SMALL).fit(df)
    room = df[df.unit_type == "room"].iloc[[0]]
    bed = df[df.unit_type == "2bed"].iloc[[0]]
    (r,) = model.verdict(room, [float(model.predict(room)[0]) * 1.15])
    (b,) = model.verdict(bed, [float(model.predict(bed)[0]) * 1.15])
    assert b.price_percentile > 95 and r.price_percentile < 80
    assert r.range_group == "room" and b.range_group == "2bed"
    assert (r.range_high / r.expected) > (b.range_high / b.expected)


def test_shared_range_mode_matches_v1():
    model = PriceModel(params=SMALL, per_type_ranges=False).fit(mixed_noise_frame())
    assert model.calibration("room")[0] == "all"
    assert model.interval("room") == model.interval("2bed")


def test_range_coverage_reports_every_group_and_overall():
    df = mixed_noise_frame()
    table = range_coverage(df.iloc[:400], df.iloc[400:])
    assert set(table.index) == {"room", "2bed", "overall"}
    assert table.loc["overall", "n"] == 200
    assert 0.6 < table.loc["overall", "coverage"] < 0.95
