# Plan to early January

Re-based on 2026-10-14 from HANDOFF section 9 and Mark's milestones in `context.md`.
Done for term 1 means a live URL where a real listing goes in and a verdict comes out, plus a
report showing the model beats the lookup baseline on held-out listings with a calibration
result.

## Calendar anchors

| | UW | Laurier |
|---|---|---|
| Fall classes end | Dec 8 | Dec 9 |
| Exams | Dec 10 to 23 | Dec 12 to 23 |
| Winter classes begin | Jan 11 | Jan 11 |

Model work must land by Dec 9. The exam window is light work only. The app and report finish
between Dec 24 and Jan 10.

## Sprints

| Sprint | Dates | Goal | Checkpoint | Owner |
|---|---|---|---|---|
| 0 | Oct 14 to 18 | Index sweep, details, extraction, features, daily job | First sweep in the DB (done Oct 14, 1,852 listings); pipeline reviewed and launchd job installed (done Oct 16); Discord webhook still to set in `.env` | Caden |
| 1 | Oct 19 to Nov 1 | Sweep unattended; detail backlog cleared; full field audit (20 pages); parser fixtures; `sample.csv`; Wayback backfill started; manual form live | Daily Discord report for a week without a hand run; about 2,500 raw listings; `docs/field_audit.md` complete | Caden (lane 1), Mark (lane 2), anyone (form) |
| 2 | Nov 2 to 15 | Dedup, cleaning rules, clean training view; EDA notebook; lookup and ridge baselines; evaluation harness (grouped and time splits, MAE and MAPE) | Clean table with its row count; baseline MAE recorded | analysis pair, Caden |
| 3 | Nov 16 to 29 | LightGBM, error analysis, residual percentiles, SHAP drivers, batch scoring into `predictions`, comparables, confidence and out-of-distribution flag | Beats the baseline on held-out listings | analysis pair |
| 4 | Nov 30 to Dec 9 | Calibration, quantile range, Streamlit check and methodology pages, deployment target decided | Live URL with a real listing scored | app pair |
| 5 | Dec 10 to Jan 10 | Exams; then report, polish, optional description-embedding experiment | Report with the calibration result; showcase | all |

## Data volume expected

| Date | Raw unique listings | Clean rows after dedup and filters |
|---|---|---|
| Oct 14 | 1,852 | about 1,000 |
| Nov 15 | 3,300 to 6,200 | 1,700 to 2,500 |
| Dec 1 | 4,000 to 8,500 | 2,300 to 3,000 |

New listings arrive at roughly 50 to 150 a day; rooms volume should rise through October
and November as January sublets are posted.

## Risks

| Risk | Mitigation |
|---|---|
| Kijiji blocks or changes layout | Hard stop and Discord ALERT; raw pages saved so parsers can be fixed offline; fixture tests fail first |
| Kijiji's Terms clause on automated access | Caden's call, recorded in `docs/sources.md`; footprint kept to one worker, about 50 index requests a day |
| The laptop is asleep at 06:30 | launchd runs the job on wake; the report shows the gap; GitHub Actions trial on Mark's Wayback lane as the fallback path |
| Rooms data thin or mostly text | Rooms detail pages fetched first; rules re-run with `--all` as they improve; rooms and units modelled together with `unit_type` |
| Team attrition by midterms | Everything runs from the repo with tests and `docs/decisions.md`; no step depends on one machine |
| Model trains on features the app cannot supply | Tier A and B split in `docs/pipeline.md` section 4 |

## Decisions still open for Caden

Mark's proposals from `context.md` that change the contracts: `sqft`, `bathroom_private` and a
takeover flag as schema fields (today they live in `listing_attributes`, so nothing is lost
either way), the `archive_listings` table, and whether archived ad pages may be used as
deflated training rows (recommended: as an experiment only). The deployment target for the
app and whether a slim export of listings and predictions may be committed are Sprint 4
questions.

## Working agreements

Decisions go in `docs/decisions.md` the day they are made. Every parser has a fixture test.
Nothing under `data/` is committed except `sample.csv`. Scripts stay cross-platform: launchd
is Caden's machine only, Mark is on Windows.
