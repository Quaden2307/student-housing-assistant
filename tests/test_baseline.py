"""Tests for the lookup and ridge baselines against hand-built contract frames.

The CLI tests at the bottom run main() against synthetic tmp_path databases built with
housing.db.connect + migrate; everything else stays on hand-built frames.
"""

import numpy as np
import pandas as pd

from housing.db import connect
from housing.db.migrate import migrate
from housing.model.baseline import (
    FEATURES,
    MedianLookup,
    fit_predict_lookup,
    fit_predict_ridge,
    main,
    make_ridge,
)
from housing.model.evaluate import grouped_cv


def make_frame(n, *, target, bedrooms=None, neighbourhood=None, unit_type=None):
    """A frame with every training-table contract column, two rows per dedup_key."""
    bedrooms = bedrooms if bedrooms is not None else [1 + i % 5 for i in range(n)]
    neighbourhood = (
        neighbourhood
        if neighbourhood is not None
        else [["N2L", "N2J", "N2T"][i % 3] for i in range(n)]
    )
    unit_type = (
        unit_type if unit_type is not None else [["room", "1bed", "2bed"][i % 3] for i in range(n)]
    )
    return pd.DataFrame(
        {
            "listing_id": range(1, n + 1),
            "dedup_key": [f"addr{i // 2}" for i in range(n)],
            "price": [float(t) * b for t, b in zip(target, bedrooms, strict=True)],
            "price_per_bedroom": [float(t) for t in target],
            "unit_type": pd.array(unit_type, dtype="str"),
            "lease_term": pd.array(
                [["12mo", "8mo", "sublet_4mo"][i % 3] for i in range(n)], dtype="str"
            ),
            "building_type": pd.array([["house", "lowrise"][i % 2] for i in range(n)], dtype="str"),
            "neighbourhood": pd.array(neighbourhood, dtype="str"),
            "landlord_type": pd.array(
                [["pro", "owner", None][i % 3] for i in range(n)], dtype="str"
            ),
            "bedrooms": pd.array(bedrooms, dtype="Int64"),
            "bathrooms": [1.0 + (i % 2) for i in range(n)],
            "sqft": [500.0 + 10.0 * i for i in range(n)],
            "walk_uw_min": [5.0 + i % 20 for i in range(n)],
            "walk_laurier_min": [7.0 + i % 20 for i in range(n)],
            "ion_distance_m": [300.0 + 5.0 * i for i in range(n)],
            "move_in_month": pd.array([1 + i % 12 for i in range(n)], dtype="Int64"),
            "listing_month": pd.array([10] * n, dtype="Int64"),
            "utilities_included": pd.array([i % 2 == 0 for i in range(n)], dtype="boolean"),
            "furnished": pd.array([i % 3 == 0 for i in range(n)], dtype="boolean"),
            "laundry_in_unit": pd.array([True] * n, dtype="boolean"),
            "year_built_after_2018": pd.array([False] * n, dtype="boolean"),
            "bathroom_private": pd.array([[True, None][i % 2] for i in range(n)], dtype="boolean"),
            "is_takeover": pd.array([False] * n, dtype="boolean"),
            "internet_included": pd.array(
                [[None, False, True][i % 3] for i in range(n)], dtype="boolean"
            ),
            "first_seen": [f"2026-10-{1 + i % 20:02d}T06:30:00Z" for i in range(n)],
            "last_seen": [f"2026-10-{2 + i % 20:02d}T06:30:00Z" for i in range(n)],
        }
    )


def test_features_exclude_leaky_columns():
    leaky = {"price", "price_per_bedroom", "dedup_key", "listing_id", "first_seen", "last_seen"}
    assert leaky.isdisjoint(FEATURES)


def test_median_lookup_learns_medians_and_falls_back():
    train = make_frame(
        5,
        target=[600, 700, 1400, 900, 1100],
        neighbourhood=["N2L", "N2L", "N2L", "N2J", "N2J"],
        unit_type=["room", "room", "1bed", "room", "room"],
    )
    test = make_frame(
        5,
        target=[0, 0, 0, 0, 0],  # never read by predict
        neighbourhood=["N2L", "N2J", "N2Z", "N2Z", None],
        unit_type=["room", "room", "room", "loft", "room"],
    )
    preds = MedianLookup().fit(train).predict(test)
    assert preds.shape == (len(test),)
    # (N2L, room) -> 650; (N2J, room) -> 1000; unseen neighbourhood -> room median 800;
    # unseen both -> global median 900; NA neighbourhood -> room median 800.
    np.testing.assert_allclose(preds, [650.0, 1000.0, 800.0, 900.0, 800.0])


def _synthetic(n=60, seed=42):
    rng = np.random.default_rng(seed)
    bedrooms = rng.integers(1, 6, n)
    target = 400.0 * bedrooms + rng.normal(0.0, 30.0, n)
    return make_frame(
        n,
        target=target,
        bedrooms=list(int(b) for b in bedrooms),
        neighbourhood=["N2L"] * n,  # constant, so the lookup cannot see the bedroom signal
        unit_type=["room"] * n,
    )


def test_ridge_beats_lookup_on_bedroom_driven_prices():
    df = _synthetic()
    lookup_mae = np.mean([m.mae for m in grouped_cv(df, fit_predict_lookup, n_splits=5)])
    ridge_mae = np.mean([m.mae for m in grouped_cv(df, fit_predict_ridge, n_splits=5)])
    assert ridge_mae < 0.5 * lookup_mae, (ridge_mae, lookup_mae)


def test_ridge_predictions_are_positive_dollars():
    df = _synthetic()
    preds = fit_predict_ridge(df.iloc[:48], df.iloc[48:])
    assert preds.shape == (12,)
    assert np.isfinite(preds).all()
    assert (preds > 0).all()


def test_ridge_handles_na_everywhere_and_unseen_categories():
    train = _synthetic()
    # sprinkle NA into every column type the pipeline consumes
    train.loc[::7, "neighbourhood"] = None
    train.loc[::6, "sqft"] = np.nan
    train.loc[::5, "bathrooms"] = np.nan
    train.loc[::4, "furnished"] = pd.NA
    train.loc[::3, "move_in_month"] = pd.NA
    test = make_frame(
        4,
        target=[800, 800, 800, 800],
        neighbourhood=["N9Z", None, "N2L", None],  # N9Z unseen in training
        unit_type=["loft", "room", None, "room"],  # loft unseen in training
    )
    test.loc[0, "bedrooms"] = pd.NA
    test.loc[1, "sqft"] = np.nan
    test.loc[2, "furnished"] = pd.NA
    test.loc[3, "ion_distance_m"] = np.nan
    preds = fit_predict_ridge(train, test)
    assert preds.shape == (4,)
    assert np.isfinite(preds).all()
    assert (preds > 0).all()


def test_make_ridge_trains_on_log_target():
    # On exactly exponential data a log-target linear model is exact; dollars come back.
    n = 30
    bedrooms = [1 + i % 5 for i in range(n)]
    target = [1000.0 * (2.0**b) for b in bedrooms]
    df = make_frame(
        n, target=target, bedrooms=bedrooms, neighbourhood=["N2L"] * n, unit_type=["room"] * n
    )
    model = make_ridge()
    model.fit(df[FEATURES], df["price_per_bedroom"])
    preds = model.predict(df[FEATURES])
    # multiplicative structure recovered well: within 15% everywhere
    ratio = preds / np.asarray(target)
    assert ratio.min() > 0.85 and ratio.max() < 1.15


def _seed_listing(conn, lid, *, price, dedup_key, first_seen, bedrooms=2, unit_type="2bed"):
    """One clean-table survivor: in-region listing + snapshot price + units + features."""
    conn.execute(
        "INSERT INTO listings (id, source, source_id, title, address_text, lat, lon,"
        " first_seen, last_seen, status, dedup_key)"
        " VALUES (?, 'kijiji', ?, '2 bed unit', '44 Chapel St', 43.47, -80.52, ?,"
        " '2026-10-22T06:30:00Z', 'active', ?)",
        (lid, str(lid), first_seen, dedup_key),
    )
    conn.execute(
        "INSERT INTO snapshots (listing_id, scraped_at, price) VALUES (?, '2026-10-22T06:30:00Z', ?)",
        (lid, price),
    )
    conn.execute(
        "INSERT INTO units (listing_id, unit_type, bedrooms, bathrooms, lease_term,"
        " move_in_month, utilities_included, furnished, laundry_in_unit, building_type,"
        " year_built_after_2018) VALUES (?, ?, ?, 1.0, '12mo', 9, 1, 0, ?, 'lowrise', 0)",
        (lid, unit_type, bedrooms, lid % 2),
    )
    conn.execute(
        "INSERT INTO features (listing_id, walk_uw_min, walk_laurier_min, ion_distance_m,"
        " neighbourhood) VALUES (?, 10.0, 12.0, 350.0, ?)",
        (lid, ["N2L", "N2J"][lid % 2]),
    )
    for name, value in (
        ("areainfeet", str(600 + 25 * lid)),
        ("forrentbyhousing", "ownr"),
        ("text_internet_included", str(lid % 2)),
    ):
        conn.execute(
            "INSERT INTO listing_attributes (listing_id, name, value) VALUES (?, ?, ?)",
            (lid, name, value),
        )


def test_cli_end_to_end(tmp_path, capsys):
    db = tmp_path / "cli.db"
    conn = connect(db)
    migrate(conn)
    # 8 keyed listings over 4 sweeps, one repost pair sharing a key, one keyless listing
    for i in range(8):
        _seed_listing(
            conn,
            i + 1,
            price=1400.0 + 120 * i,
            dedup_key=f"addr:{i + 1} king st|2bed|2",
            first_seen=f"2026-10-{14 + i % 4:02d}T06:30:00Z",
        )
    _seed_listing(
        conn, 9, price=1410.0, dedup_key="addr:1 king st|2bed|2", first_seen="2026-10-15T06:30:00Z"
    )
    _seed_listing(conn, 10, price=2000.0, dedup_key=None, first_seen="2026-10-16T06:30:00Z")
    conn.commit()
    conn.close()

    assert main(["--db", str(db)]) == 0
    out = capsys.readouterr().out
    assert "clean table: kept 9 rows" in out  # the repost pair collapsed
    assert "duplicates=1" in out
    assert "note: 1 rows have no dedup_key" in out  # listing 10, grouped as its own unit
    assert "grouped 5-fold CV" in out
    assert "time split (newest" in out  # the achieved share, from the distinct-stamp cut
    for name in ("lookup", "ridge"):
        (line,) = [ln for ln in out.splitlines() if ln.startswith(name)]
        assert "MAE $" in line and "MAPE" in line


def test_cli_skips_time_split_when_one_sweep_dominates(tmp_path, capsys):
    # Every row shares one first_seen (the day-one state): the CLI still reports CV and
    # says why the drift check is off, instead of slicing the tie block arbitrarily.
    db = tmp_path / "tied.db"
    conn = connect(db)
    migrate(conn)
    for i in range(6):
        _seed_listing(
            conn,
            i + 1,
            price=1400.0 + 150 * i,
            dedup_key=f"addr:{i + 1} weber st|2bed|2",
            first_seen="2026-10-14T06:30:00Z",
        )
    conn.commit()
    conn.close()

    assert main(["--db", str(db)]) == 0
    out = capsys.readouterr().out
    assert "skipped: time split needs at least 2 distinct first_seen values" in out
    assert "grouped 5-fold CV" in out


def test_leakage_canary_price_columns_ignored():
    train = _synthetic(n=40, seed=7)
    test = _synthetic(n=60, seed=8).iloc[:10].reset_index(drop=True)
    base_ridge = fit_predict_ridge(train, test)
    base_lookup = fit_predict_lookup(train, test)

    mutated = test.copy()
    mutated["price"] = 9_999_999.0
    mutated["price_per_bedroom"] = -123456.0
    mutated["listing_id"] = mutated["listing_id"] + 10_000
    np.testing.assert_allclose(fit_predict_ridge(train, mutated), base_ridge, rtol=0, atol=1e-9)
    np.testing.assert_allclose(fit_predict_lookup(train, mutated), base_lookup, rtol=0, atol=1e-9)
