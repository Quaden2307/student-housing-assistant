"""Tests for batch scoring into the predictions table."""

import numpy as np
import pytest

from housing.db import connect
from housing.db.migrate import migrate
from housing.model.lgbm import PriceModel
from housing.model.score import (
    active_ids,
    main,
    oof_by_listing,
    score_rows,
    write_predictions,
)
from tests.test_baseline import _seed_listing
from tests.test_lgbm import SMALL, priced_frame

SCORED_AT = "2026-11-21T12:00:00Z"


def fitted(n=120, seed=0):
    """A fitted model and the frame it was fitted on."""
    df = priced_frame(n=n, seed=seed)
    return PriceModel(params=SMALL, n_splits=3).fit(df), df


def seed_db(path, n=30, gone=()):
    """A database of n active clean-table listings, with `gone` ids marked gone."""
    conn = connect(path)
    migrate(conn)
    for i in range(n):
        _seed_listing(
            conn,
            i + 1,
            price=1400.0 + 40 * i,
            dedup_key=f"addr:{i + 1} king st|2bed|2",
            first_seen=f"2026-10-{14 + i % 5:02d}T06:30:00Z",
        )
    for lid in gone:
        conn.execute("UPDATE listings SET status = 'gone' WHERE id = ?", (lid,))
    conn.commit()
    conn.close()


def test_oof_by_listing_covers_every_row_with_positive_dollars():
    model, df = fitted()
    oof = oof_by_listing(df, model)

    assert set(oof) == set(df["listing_id"])
    assert all(v > 0 for v in oof.values())
    # Out-of-fold, so each value is a prediction from a model that never saw that row.
    np.testing.assert_allclose(
        [oof[i] for i in df["listing_id"]], model.oof_pred, rtol=0, atol=1e-9
    )


def test_oof_by_listing_is_empty_for_a_model_without_out_of_fold_predictions():
    _, df = fitted()
    assert oof_by_listing(df, PriceModel(params=SMALL)) == {}


def test_score_rows_uses_the_out_of_fold_expected_price_when_there_is_one():
    # The whole point of the override: a listing the model was fitted on must not be
    # scored against the model's memory of its own asking price.
    model, df = fitted()
    ads = df.iloc[:5].reset_index(drop=True)
    sentinel = {int(i): 999.0 for i in ads["listing_id"]}

    rows, _, n_oof = score_rows(model, ads, sentinel, "v", SCORED_AT)

    assert n_oof == 5
    assert [r["expected"] for r in rows] == [999.0] * 5
    assert all(r["q10"] < 999.0 < r["q90"] for r in rows)


def test_score_rows_falls_back_to_the_fitted_prediction():
    model, df = fitted()
    ads = df.iloc[:5].reset_index(drop=True)

    rows, _, n_oof = score_rows(model, ads, {}, "v", SCORED_AT)

    assert n_oof == 0
    np.testing.assert_allclose([r["expected"] for r in rows], model.predict(ads), rtol=0, atol=0.01)


def test_score_rows_mixes_both_sources_per_listing():
    model, df = fitted()
    ads = df.iloc[:6].reset_index(drop=True)
    partial = {int(ads["listing_id"][0]): 888.0, int(ads["listing_id"][3]): 777.0}

    rows, bands, n_oof = score_rows(model, ads, partial, "v", SCORED_AT)

    assert n_oof == 2
    assert rows[0]["expected"] == 888.0
    assert rows[3]["expected"] == 777.0
    assert sum(bands.values()) == 6
    assert set(bands) <= {"GOOD_DEAL", "FAIR", "OVERPRICED"}


def test_score_rows_on_an_empty_frame_writes_nothing():
    model, df = fitted()
    assert score_rows(model, df.iloc[:0], {}, "v", SCORED_AT) == ([], {}, 0)


def test_write_predictions_upserts_on_rerun(tmp_path):
    db = tmp_path / "upsert.db"
    seed_db(db, n=3)
    conn = connect(db)
    row = {
        "listing_id": 1,
        "model_version": "v1",
        "expected": 900.0,
        "q10": 800.0,
        "q90": 1000.0,
        "percentile": 50.0,
        "scored_at": SCORED_AT,
    }

    assert write_predictions(conn, [row]) == 1
    assert write_predictions(conn, [{**row, "expected": 950.0, "scored_at": "later"}]) == 1

    stored = conn.execute("SELECT expected, scored_at FROM predictions").fetchall()
    assert len(stored) == 1, "same (listing_id, model_version) must update, not duplicate"
    assert stored[0][0] == 950.0 and stored[0][1] == "later"

    # A second model version is a separate row, since it is part of the primary key.
    write_predictions(conn, [{**row, "model_version": "v2"}])
    assert conn.execute("SELECT count(*) FROM predictions").fetchone()[0] == 2
    conn.close()


def test_write_predictions_on_no_rows_is_a_no_op(tmp_path):
    db = tmp_path / "empty.db"
    seed_db(db, n=1)
    conn = connect(db)
    assert write_predictions(conn, []) == 0
    conn.close()


def test_active_ids_excludes_gone_listings(tmp_path):
    db = tmp_path / "active.db"
    seed_db(db, n=5, gone=(2, 4))
    conn = connect(db)
    assert active_ids(conn) == {1, 3, 5}
    conn.close()


def test_cli_scores_only_active_listings(tmp_path, capsys):
    db = tmp_path / "cli.db"
    seed_db(db, n=30, gone=(3, 7, 11))

    assert main(["--db", str(db)]) == 0
    out = capsys.readouterr().out
    assert "wrote 27 rows to predictions (model_version=lgbm_v1)" in out

    conn = connect(db)
    scored = {r[0] for r in conn.execute("SELECT listing_id FROM predictions")}
    assert scored == set(range(1, 31)) - {3, 7, 11}
    versions = {r[0] for r in conn.execute("SELECT DISTINCT model_version FROM predictions")}
    assert versions == {"lgbm_v1"}
    ranges = conn.execute("SELECT expected, q10, q90, percentile FROM predictions").fetchall()
    assert all(q10 < exp < q90 for exp, q10, q90, _ in ranges)
    assert all(0.0 <= pct <= 100.0 for *_, pct in ranges)
    conn.close()


def test_cli_rerun_refreshes_rather_than_duplicates(tmp_path, capsys):
    db = tmp_path / "rerun.db"
    seed_db(db, n=30)

    assert main(["--db", str(db)]) == 0
    assert main(["--db", str(db)]) == 0
    capsys.readouterr()

    conn = connect(db)
    assert conn.execute("SELECT count(*) FROM predictions").fetchone()[0] == 30
    conn.close()


def test_cli_dry_run_writes_nothing(tmp_path, capsys):
    db = tmp_path / "dry.db"
    seed_db(db, n=30)

    assert main(["--db", str(db), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "dry run: nothing written" in out

    conn = connect(db)
    assert conn.execute("SELECT count(*) FROM predictions").fetchone()[0] == 0
    conn.close()


def test_cli_save_and_load_round_trip(tmp_path, capsys):
    db = tmp_path / "saved.db"
    seed_db(db, n=30)
    model_path = tmp_path / "m.joblib"

    assert main(["--db", str(db), "--save", str(model_path)]) == 0
    assert model_path.exists()

    # Loading skips fitting, so there are no out-of-fold predictions for these rows.
    assert main(["--db", str(db), "--load", str(model_path), "--model-version", "v2"]) == 0
    out = capsys.readouterr().out
    assert "no out-of-fold predictions" in out
    assert "(0 with out-of-fold expected prices, 30 fitted)" in out

    conn = connect(db)
    versions = {r[0] for r in conn.execute("SELECT DISTINCT model_version FROM predictions")}
    assert versions == {"lgbm_v1", "v2"}
    conn.close()


def test_cli_reports_nothing_to_score_when_every_listing_is_gone(tmp_path, capsys):
    db = tmp_path / "allgone.db"
    seed_db(db, n=30, gone=tuple(range(1, 31)))

    assert main(["--db", str(db)]) == 1
    assert "no active listings pass cleaning" in capsys.readouterr().out


def test_cli_reports_an_empty_training_table(tmp_path, capsys):
    db = tmp_path / "bare.db"
    conn = connect(db)
    migrate(conn)
    conn.commit()
    conn.close()

    assert main(["--db", str(db)]) == 1
    assert "nothing to fit" in capsys.readouterr().out


@pytest.mark.parametrize("flag", ["--dry-run", None])
def test_cli_prints_the_band_tally(tmp_path, capsys, flag):
    db = tmp_path / f"bands{flag}.db"
    seed_db(db, n=30)

    assert main([a for a in ["--db", str(db), flag] if a]) == 0
    out = capsys.readouterr().out
    assert any(b in out for b in ("good_deal", "fair", "overpriced"))
