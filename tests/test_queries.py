import pytest

from housing.db import connect
from housing.db.migrate import migrate
from housing.db.queries import (
    count_listings,
    delete_attributes,
    get_attributes,
    insert_snapshot,
    pending_details,
    replace_attributes,
    restrip_listings,
    set_detail,
    table_counts,
    upsert_listing,
)
from housing.parse.pii import REDACTED

T1 = "2026-10-14T20:00:00Z"
T2 = "2026-10-15T20:00:00Z"


@pytest.fixture
def conn(tmp_path):
    connection = connect(tmp_path / "t.db")
    migrate(connection)
    yield connection
    connection.close()


def test_upsert_inserts_then_refreshes(conn):
    lid, created = upsert_listing(conn, source="kijiji", source_id="1", seen_at=T1, title="A")
    assert created
    lid2, created2 = upsert_listing(conn, source="kijiji", source_id="1", seen_at=T2, title="B")
    assert lid2 == lid and not created2
    row = conn.execute("SELECT title, first_seen, last_seen, status FROM listings").fetchone()
    assert tuple(row) == ("B", T1, T2, "active")
    # A repeat within the same second is still not a creation.
    assert upsert_listing(conn, source="kijiji", source_id="1", seen_at=T2)[1] is False


def test_upsert_never_overwrites_known_values_with_null(conn):
    upsert_listing(
        conn,
        source="kijiji",
        source_id="1",
        seen_at=T1,
        address_text="44 Chapel",
        lat=43.45,
        lon=-80.48,
        posted_at="2026-10-05",
    )
    upsert_listing(conn, source="kijiji", source_id="1", seen_at=T2, posted_at="2026-10-09")
    row = conn.execute("SELECT address_text, lat, lon, posted_at FROM listings").fetchone()
    assert tuple(row) == ("44 Chapel", 43.45, -80.48, "2026-10-05")


def test_upsert_revives_a_gone_listing(conn):
    lid, _ = upsert_listing(conn, source="kijiji", source_id="1", seen_at=T1)
    conn.execute("UPDATE listings SET status = 'gone' WHERE id = ?", (lid,))
    upsert_listing(conn, source="kijiji", source_id="1", seen_at=T2)
    assert conn.execute("SELECT status FROM listings").fetchone()[0] == "active"


def test_same_ad_id_on_another_source_is_a_different_listing(conn):
    a, _ = upsert_listing(conn, source="kijiji", source_id="1", seen_at=T1)
    b, _ = upsert_listing(conn, source="manual", source_id="1", seen_at=T1)
    assert a != b


def test_snapshots_and_counts(conn):
    lid, _ = upsert_listing(conn, source="kijiji", source_id="1", seen_at=T1)
    insert_snapshot(conn, lid, T1, 650.0, "data/raw/kijiji/2026-10-14/index_rooms_p1.html.gz")
    insert_snapshot(conn, lid, T2, None, "data/raw/kijiji/2026-10-15/index_rooms_p1.html.gz")
    counts = table_counts(conn)
    assert counts["listings"] == 1 and counts["snapshots"] == 2 and counts["units"] == 0
    assert count_listings(conn) == 1
    assert count_listings(conn, "active") == 1 and count_listings(conn, "gone") == 0


def test_attributes_roundtrip_and_partial_update(conn):
    from housing.db.queries import get_attributes, replace_attributes

    lid, _ = upsert_listing(conn, source="kijiji", source_id="1", seen_at=T1)
    replace_attributes(conn, lid, {"numberbedrooms": "2", "category": "apartments"})
    replace_attributes(conn, lid, {"numberbedrooms": "3", "image_count": "5"})
    assert get_attributes(conn, lid) == {
        "numberbedrooms": "3",
        "category": "apartments",
        "image_count": "5",
    }


def test_set_detail_only_fills_gaps(conn):
    lid, _ = upsert_listing(
        conn,
        source="kijiji",
        source_id="1",
        seen_at=T1,
        lat=43.1,
        lon=-80.1,
        posted_at="2026-10-01",
    )
    set_detail(
        conn,
        lid,
        description="Full text",
        address_text="44 Chapel",
        lat=43.2,
        lon=-80.2,
        posted_at="2026-10-09",
    )
    row = conn.execute(
        "SELECT description, address_text, lat, lon, posted_at FROM listings"
    ).fetchone()
    assert tuple(row) == ("Full text", "44 Chapel", 43.1, -80.1, "2026-10-01")
    set_detail(conn, lid, description="Full text", address_text="Other St")
    assert conn.execute("SELECT address_text FROM listings").fetchone()[0] == "44 Chapel"


def test_pending_details_rooms_first_then_newest(conn):
    upsert_listing(
        conn,
        source="kijiji",
        source_id="a",
        seen_at=T1,
        url="https://www.kijiji.ca/v-apartments-condos/kitchener-waterloo/x/1",
    )
    upsert_listing(
        conn,
        source="kijiji",
        source_id="b",
        seen_at=T2,
        url="https://www.kijiji.ca/v-apartments-condos/kitchener-waterloo/x/2",
    )
    room, _ = upsert_listing(
        conn,
        source="kijiji",
        source_id="c",
        seen_at=T1,
        url="https://www.kijiji.ca/v-room-rental-roommate/kitchener-waterloo/x/3",
    )
    done, _ = upsert_listing(
        conn,
        source="kijiji",
        source_id="d",
        seen_at=T2,
        url="https://www.kijiji.ca/v-room-rental-roommate/kitchener-waterloo/x/4",
    )
    replace_attributes(conn, done, {"detail_fetched_at": T2})
    gone, _ = upsert_listing(
        conn,
        source="kijiji",
        source_id="e",
        seen_at=T2,
        url="https://www.kijiji.ca/v-room-rental-roommate/kitchener-waterloo/x/5",
    )
    conn.execute("UPDATE listings SET status = 'gone' WHERE id = ?", (gone,))
    assert [r["source_id"] for r in pending_details(conn, "kijiji", 10)] == ["c", "b", "a"]
    assert [r["source_id"] for r in pending_details(conn, "kijiji", 1)] == ["c"]


def test_pending_details_retries_a_failed_page_only_after_the_cutoff(conn):
    upsert_listing(
        conn, source="kijiji", source_id="a", seen_at=T1, url="https://www.kijiji.ca/v-x/kw/x/1"
    )
    lid, _ = upsert_listing(
        conn, source="kijiji", source_id="f", seen_at=T1, url="https://www.kijiji.ca/v-x/kw/x/2"
    )
    replace_attributes(conn, lid, {"detail_error": "HTTP 503", "detail_failed_at": T1})
    assert [r["source_id"] for r in pending_details(conn, "kijiji", 10)] == ["a"]
    assert [
        r["source_id"] for r in pending_details(conn, "kijiji", 10, retry_failed_before=T1)
    ] == ["a"]
    assert [
        r["source_id"] for r in pending_details(conn, "kijiji", 10, retry_failed_before=T2)
    ] == ["a", "f"]


def test_delete_attributes_by_name_and_prefix(conn):
    lid, _ = upsert_listing(conn, source="kijiji", source_id="1", seen_at=T1)
    replace_attributes(
        conn, lid, {"text_a": "1", "text_b": "1", "detail_error": "x", "category": "rooms"}
    )
    delete_attributes(conn, lid, names=("detail_error", "missing"))
    delete_attributes(conn, lid, prefix="text_")
    assert get_attributes(conn, lid) == {"category": "rooms"}


def test_restrip_listings_applies_the_current_rules_to_stored_rows(conn):
    base = "https://www.kijiji.ca/v-room-rental-roommate/kitchener-waterloo"
    upsert_listing(conn, source="kijiji", source_id="1", seen_at=T1, title="Call 519 - 555 - 0199",
                   url=f"{base}/call-519-555-0199/1")  # fmt: skip
    lid, _ = upsert_listing(
        conn, source="kijiji", source_id="2", seen_at=T1, title="Clean", url=f"{base}/clean/2"
    )
    set_detail(conn, lid, description=f"Already {REDACTED}. Ask for Candice.")
    assert restrip_listings(conn) == 2
    rows = conn.execute("SELECT title, url, description FROM listings ORDER BY id").fetchall()
    assert tuple(rows[0]) == (f"Call {REDACTED}", f"{base}/call/1", None)
    assert tuple(rows[1]) == (
        "Clean",
        f"{base}/clean/2",
        f"Already {REDACTED}. Ask for {REDACTED}.",
    )
    assert restrip_listings(conn) == 0


def test_mark_gone_uses_last_seen_cutoff(conn):
    from housing.db.queries import mark_gone

    upsert_listing(conn, source="kijiji", source_id="old", seen_at=T1)
    upsert_listing(conn, source="kijiji", source_id="new", seen_at=T2)
    upsert_listing(conn, source="manual", source_id="old", seen_at=T1)
    assert mark_gone(conn, "kijiji", "2026-10-15T00:00:00Z") == 1
    assert count_listings(conn, "gone") == 1 and count_listings(conn, "active") == 2


def test_upsert_units_and_extraction_selection(conn):
    from housing.db.queries import listings_for_extraction, upsert_units
    from housing.parse.units import UnitFields

    a, _ = upsert_listing(conn, source="kijiji", source_id="a", seen_at=T1)
    b, _ = upsert_listing(conn, source="kijiji", source_id="b", seen_at=T1)
    upsert_units(
        conn,
        a,
        UnitFields(unit_type="room", bedrooms=5, utilities_included=True, lease_term="8mo"),
        T1,
    )
    row = conn.execute(
        "SELECT unit_type, bedrooms, utilities_included, lease_term, extracted_at FROM units"
    ).fetchone()
    assert tuple(row) == ("room", 5, 1, "8mo", T1)
    assert [r["id"] for r in listings_for_extraction(conn, only_missing=True)] == [b]
    assert [r["id"] for r in listings_for_extraction(conn, only_missing=False)] == [a, b]
    upsert_units(conn, a, UnitFields(unit_type="2bed", bedrooms=2), T2)
    assert conn.execute("SELECT unit_type, utilities_included FROM units").fetchone()[:] == (
        "2bed",
        None,
    )
