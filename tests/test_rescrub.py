"""The re-scrub pass over stored raw pages (housing.scrape.rescrub)."""

import gzip
import json

from housing.parse.pii import scrub_page
from housing.scrape.rescrub import main, rescrub_file, rescrub_tree


def _poster_page(name: str) -> str:
    state = {
        "StandardListing:2": {"id": "2", "title": "Room near UW", "description": "Big room"},
        "StandardProfileV2:1": {"id": "1", "name": name},
    }
    return (
        '<html><script id="__NEXT_DATA__" type="application/json">'
        + json.dumps({"props": {"pageProps": {"__APOLLO_STATE__": state}}})
        + f'</script><a href="/o-profile/1/1">{name}</a></html>'
    )


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        fh.write(text)


def test_rescrub_removes_a_leaked_name_and_leaves_clean_pages_alone(tmp_path):
    leaked = tmp_path / "kijiji" / "2026-10-20" / "detail_1.html.gz"
    _write(leaked, _poster_page("Jane Poster"))
    clean = tmp_path / "kijiji" / "2026-10-20" / "detail_2.html.gz"
    _write(clean, scrub_page(_poster_page("Jane Poster")))
    meta = tmp_path / "kijiji" / "2026-10-20" / "detail_1.meta.json"
    meta.write_text('{"scrubbed": true}')
    clean_bytes = clean.read_bytes()

    assert rescrub_tree(tmp_path) == (2, 1, 0)
    with gzip.open(leaked, "rt", encoding="utf-8") as fh:
        assert "Jane Poster" not in fh.read()
    assert clean.read_bytes() == clean_bytes
    assert meta.read_text() == '{"scrubbed": true}'
    # A second pass is a no-op: the rules are idempotent.
    assert rescrub_tree(tmp_path) == (2, 0, 0)


def test_rescrub_backs_up_originals_before_rewriting(tmp_path):
    page = tmp_path / "raw" / "kijiji" / "detail_1.html.gz"
    _write(page, _poster_page("Jane Poster"))
    original = page.read_bytes()
    backup_root = tmp_path / "backup"
    assert rescrub_tree(tmp_path / "raw", backup_root=backup_root) == (1, 1, 0)
    assert (backup_root / "kijiji" / "detail_1.html.gz").read_bytes() == original
    assert page.read_bytes() != original


def test_rescrub_dry_run_reports_without_writing(tmp_path):
    page = tmp_path / "detail_1.html.gz"
    _write(page, _poster_page("Jane Poster"))
    before = page.read_bytes()
    assert rescrub_file(page, dry_run=True) is True
    assert page.read_bytes() == before


def test_rescrub_skips_unreadable_files(tmp_path):
    bad = tmp_path / "broken.html.gz"
    bad.write_bytes(b"not gzip at all")
    assert rescrub_tree(tmp_path) == (1, 0, 1)


def test_rescrub_leaves_pages_without_next_data_alone(tmp_path):
    page = tmp_path / "wayback" / "cap.html.gz"
    _write(page, "<!-- archive-format: unknown; body not stored -->\n")
    assert rescrub_tree(tmp_path) == (1, 0, 0)


def test_cli_prints_a_summary(tmp_path, capsys):
    _write(tmp_path / "detail_1.html.gz", _poster_page("Jane Poster"))
    assert main(["--root", str(tmp_path), "--dry-run"]) == 0
    assert "1 pages seen, would change 1, skipped 0" in capsys.readouterr().out
