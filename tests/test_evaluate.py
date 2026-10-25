"""Tests for the evaluation harness: metrics, grouped CV, the time split and summaries."""

import numpy as np
import pandas as pd
import pytest

from housing.model.evaluate import GROUP, TARGET, Metrics, grouped_cv, score, summarize, time_split


def make_df(groups, targets, first_seen=None):
    """A minimal frame following the training-table contract columns the harness reads."""
    n = len(groups)
    if first_seen is None:
        first_seen = [f"2026-10-{i + 1:02d}T06:30:00Z" for i in range(n)]
    return pd.DataFrame(
        {
            "listing_id": range(1, n + 1),
            GROUP: groups,
            TARGET: [float(t) for t in targets],
            "first_seen": first_seen,
        }
    )


def test_score_exact_mae_and_mape():
    m = score(np.array([100.0, 200.0, 400.0]), np.array([110.0, 190.0, 400.0]))
    assert m.n == 3
    assert m.mae == pytest.approx(20.0 / 3)
    # (10/100 + 10/200 + 0/400) / 3 * 100
    assert m.mape == pytest.approx(5.0)
    assert str(m) == "MAE $7, MAPE 5.0% (n=3)"


def test_score_excludes_zero_targets_from_mape_only():
    m = score(np.array([0.0, 100.0]), np.array([50.0, 110.0]))
    assert m.mae == pytest.approx(30.0)  # the zero-target row still counts for MAE
    assert m.mape == pytest.approx(10.0)
    assert m.n == 2


def test_score_shape_mismatch_raises():
    with pytest.raises(ValueError, match="shape"):
        score(np.array([1.0, 2.0]), np.array([1.0]))


def test_grouped_cv_never_splits_a_group():
    # Each group's rows are deliberately non-contiguous: a group-blind splitter cutting
    # the frame into contiguous halves would put every group on both sides, so this
    # layout fails for plain KFold and passes only for a real grouped split.
    df = make_df(
        groups=["a", "b", "c", "d", "a", "b", "c", "d"],
        targets=[600, 620, 900, 910, 1200, 1180, 700, 720],
    )
    seen = []

    def record(train_df, test_df):
        seen.append((set(train_df[GROUP]), set(test_df[GROUP])))
        return np.full(len(test_df), float(train_df[TARGET].mean()))

    folds = grouped_cv(df, record, n_splits=2)
    assert len(folds) == 2
    for train_groups, test_groups in seen:
        assert train_groups & test_groups == set()
    # every group is held out exactly once across folds
    held_out = [g for _, test_groups in seen for g in test_groups]
    assert sorted(held_out) == ["a", "b", "c", "d"]
    assert all(isinstance(m, Metrics) and m.n == 4 for m in folds)


def test_grouped_cv_rejects_na_groups():
    # load_training fills keyless rows with a sentinel; a frame that still carries NA
    # keys must fail with a message naming the fix, not sklearn's "Input contains NaN".
    df = make_df(groups=["a", "a", "b", None], targets=[600, 620, 900, 910])
    with pytest.raises(ValueError, match="listing:<id>"):
        grouped_cv(df, lambda tr, te: np.full(len(te), 700.0), n_splits=2)


def test_grouped_cv_sentinel_groups_are_their_own_units():
    # The 'listing:<id>' sentinels from load_training: each keyless row is one group,
    # held out exactly once and never lumped with the others.
    df = make_df(
        groups=["a", "a", "b", "b", "listing:7", "listing:9"],
        targets=[600, 620, 900, 910, 700, 1100],
    )
    seen = []

    def record(train_df, test_df):
        seen.append((set(train_df[GROUP]), set(test_df[GROUP])))
        return np.full(len(test_df), float(train_df[TARGET].mean()))

    folds = grouped_cv(df, record, n_splits=4)
    assert len(folds) == 4
    held_out = [g for _, test_groups in seen for g in test_groups]
    assert sorted(held_out) == ["a", "b", "listing:7", "listing:9"]
    for train_groups, test_groups in seen:
        assert train_groups & test_groups == set()


def test_grouped_cv_lowers_splits_to_group_count():
    df = make_df(groups=["a", "a", "b", "b"], targets=[600, 620, 900, 910])
    folds = grouped_cv(df, lambda tr, te: np.full(len(te), 700.0), n_splits=5)
    assert len(folds) == 2


def test_grouped_cv_single_group_raises():
    df = make_df(groups=["a", "a"], targets=[600, 620])
    with pytest.raises(ValueError, match="distinct"):
        grouped_cv(df, lambda tr, te: np.full(len(te), 700.0), n_splits=5)


def test_time_split_newest_rows_in_test():
    days = [7, 3, 8, 1, 5, 2, 6, 4]  # deliberately unsorted
    df = make_df(
        groups=list("abcdefgh"),
        targets=[600] * 8,
        first_seen=[f"2026-10-{d:02d}T06:30:00Z" for d in days],
    )
    train, test = time_split(df, test_fraction=0.25)
    assert len(test) == 2
    assert len(train) == 6
    assert sorted(test["first_seen"]) == ["2026-10-07T06:30:00Z", "2026-10-08T06:30:00Z"]
    assert train["first_seen"].max() <= test["first_seen"].min()
    # nothing lost or duplicated
    assert sorted(list(train["listing_id"]) + list(test["listing_id"])) == list(range(1, 9))


def test_time_split_tie_block_stays_on_one_side():
    # 6 of 8 rows share one sweep's timestamp around the 25% cut: the cut must fall
    # between distinct timestamps, so the whole tie block lands in train and the test
    # set is strictly newer (a row-count cut would split the block by insert order).
    sweep = "2026-10-14T06:30:00Z"
    df = make_df(
        groups=list("abcdefgh"),
        targets=[600] * 8,
        first_seen=[sweep] * 6 + ["2026-10-15T06:30:00Z", "2026-10-16T06:30:00Z"],
    )
    train, test = time_split(df, test_fraction=0.25)
    assert len(test) == 2  # 2/8 is exactly the asked fraction here
    assert train["first_seen"].max() < test["first_seen"].min()
    assert set(train["first_seen"]) == {sweep}


def test_time_split_takes_the_closest_distinct_cut():
    # The dominant tie block sits just above the cut: the nearest achievable test share
    # is 1/8, never a slice through the block (which would give a non-ordered 2/8).
    df = make_df(
        groups=list("abcdefgh"),
        targets=[600] * 8,
        first_seen=["2026-10-13T06:30:00Z"]
        + ["2026-10-14T06:30:00Z"] * 6
        + ["2026-10-16T06:30:00Z"],
    )
    train, test = time_split(df, test_fraction=0.25)
    assert len(test) == 1
    assert train["first_seen"].max() < test["first_seen"].min()
    # equally distant candidates go to the older cutoff: 3/8 and 1/8 straddle 0.25
    tied = make_df(
        groups=list("abcdefgh"),
        targets=[600] * 8,
        first_seen=["2026-10-13T06:30:00Z"] * 5
        + ["2026-10-14T06:30:00Z"] * 2
        + ["2026-10-16T06:30:00Z"],
    )
    train, test = time_split(tied, test_fraction=0.25)
    assert len(test) == 3
    assert train["first_seen"].max() < test["first_seen"].min()


def test_time_split_all_rows_tied_raises():
    df = make_df(groups=["a", "b", "c"], targets=[600, 700, 800], first_seen=["2026-10-14T06:30:00Z"] * 3)
    with pytest.raises(ValueError, match="distinct first_seen"):
        time_split(df)


def test_time_split_bad_fraction_or_tiny_frame_raises():
    df = make_df(groups=["a", "b"], targets=[600, 700])
    with pytest.raises(ValueError, match="test_fraction"):
        time_split(df, test_fraction=1.5)
    with pytest.raises(ValueError, match="rows"):
        time_split(df.iloc[:1])


def test_summarize_averages_folds():
    folds = [Metrics(n=10, mae=100.0, mape=10.0), Metrics(n=10, mae=120.0, mape=12.0)]
    line = summarize("lookup", folds)
    assert line == "lookup: MAE $110 ± 14, MAPE 11.0% (n=20)"


def test_summarize_single_fold_has_zero_spread():
    assert summarize("m", [Metrics(n=5, mae=90.0, mape=9.0)]) == "m: MAE $90 ± 0, MAPE 9.0% (n=5)"


def test_summarize_empty_raises():
    with pytest.raises(ValueError, match="fold"):
        summarize("m", [])
