import pytest
import yaml

from housing.paths import SCHEMA_PATH
from housing.schema import load_schema

# HANDOFF section 3, hardcoded so that drift in the YAML fails here.
REQUIRED = ("unit_type", "bedrooms", "lat", "lon", "lease_term", "move_in_month")
OPTIONAL = (
    "utilities_included",
    "furnished",
    "bathrooms",
    "laundry_in_unit",
    "building_type",
    "year_built_after_2018",
)
DERIVED = (
    "price_per_bedroom",
    "walk_uw_min",
    "walk_laurier_min",
    "ion_distance_m",
    "neighbourhood",
    "days_on_market",
)
UNIT_TYPES = ("room", "studio", "1bed", "2bed", "3plus", "house")
LEASE_TERMS = ("sublet_4mo", "8mo", "12mo", "month_to_month", "unknown")
BUILDING_TYPES = ("house", "lowrise", "purpose_built_student", "unknown")

REQUIRED_ONLY = {
    "unit_type": "room",
    "bedrooms": 5,
    "lat": 43.4723,
    "lon": -80.5449,
    "lease_term": "8mo",
    "move_in_month": 1,
}
COMPLETE = {
    **REQUIRED_ONLY,
    "utilities_included": True,
    "furnished": False,
    "bathrooms": 2.5,
    "laundry_in_unit": True,
    "building_type": "house",
    "year_built_after_2018": False,
}
DROP = object()  # marks a key to leave out of a record


@pytest.fixture(scope="module")
def schema():
    return load_schema()


def test_field_names_per_group_match_section_3(schema):
    assert schema.names("required") == REQUIRED
    assert schema.names("optional") == OPTIONAL
    assert schema.names("derived") == DERIVED
    assert schema.names() == REQUIRED + OPTIONAL + DERIVED
    assert tuple(f.name for f in schema.required) == REQUIRED
    assert tuple(f.name for f in schema.optional) == OPTIONAL
    assert tuple(f.name for f in schema.derived) == DERIVED


def test_enum_values_match_section_3(schema):
    assert schema.enum_values("unit_type") == UNIT_TYPES
    assert schema.enum_values("lease_term") == LEASE_TERMS
    assert schema.enum_values("building_type") == BUILDING_TYPES


def test_version_target_and_bounds(schema):
    assert schema.version == 1
    assert [f.name for f in schema.fields if f.target] == ["price_per_bedroom"]
    assert all(f.how for f in schema.derived)
    assert all(f.how is None for f in schema.required + schema.optional)
    assert (schema["bedrooms"].min, schema["bedrooms"].max) == (1, None)
    assert (schema["move_in_month"].min, schema["move_in_month"].max) == (1, 12)


def test_lookup_helpers(schema):
    assert schema["lat"].type == "float"
    assert schema.get("asking_price") is None
    with pytest.raises(KeyError):
        schema["asking_price"]
    with pytest.raises(ValueError):
        schema.enum_values("bedrooms")
    with pytest.raises(ValueError):
        schema.names("features")


def test_complete_record_is_valid(schema):
    assert schema.validate(COMPLETE) == []


def test_required_only_record_is_valid(schema):
    assert schema.validate(REQUIRED_ONLY) == []


def test_optional_fields_may_be_none(schema):
    assert schema.validate({**COMPLETE, "bathrooms": None, "building_type": None}) == []


INVALID = [
    pytest.param({"lease_term": DROP}, "lease_term", id="missing-required"),
    pytest.param({"move_in_month": None}, "move_in_month", id="none-required"),
    pytest.param({"unit_type": "condo"}, "unit_type", id="bad-enum"),
    pytest.param({"move_in_month": 0}, "move_in_month", id="month-0"),
    pytest.param({"move_in_month": 13}, "move_in_month", id="month-13"),
    pytest.param({"bedrooms": 0}, "bedrooms", id="bedrooms-0"),
    pytest.param({"bedrooms": True}, "bedrooms", id="bool-for-int"),
    pytest.param({"bedrooms": 2.0}, "bedrooms", id="float-for-int"),
    pytest.param({"lat": True}, "lat", id="bool-for-float"),
    pytest.param({"lat": float("nan")}, "lat", id="nan-for-float"),
    pytest.param({"lon": -181}, "lon", id="lon-out-of-range"),
    pytest.param({"furnished": "yes"}, "furnished", id="str-for-bool"),
    pytest.param({"price_per_bedroom": 650.0}, "price_per_bedroom", id="derived-supplied"),
    pytest.param({"price": 650}, "price", id="unknown-key"),
]


@pytest.mark.parametrize(("change", "field"), INVALID)
def test_invalid_record_names_the_field(schema, change, field):
    record = {k: v for k, v in {**COMPLETE, **change}.items() if v is not DROP}
    problems = schema.validate(record)
    assert len(problems) == 1
    assert problems[0].startswith(f"{field}: ")


def test_validate_reports_every_problem(schema):
    problems = schema.validate({"unit_type": "loft", "price": 1})
    # one bad enum, five missing required fields, one unknown key
    assert len(problems) == 7


def test_load_schema_default_is_cached():
    assert load_schema() is load_schema()
    assert load_schema(SCHEMA_PATH) is load_schema()


def test_load_schema_from_a_copy_is_equal_but_not_cached_together(tmp_path):
    copy = tmp_path / "unit_schema.yaml"
    copy.write_text(SCHEMA_PATH.read_text())
    assert load_schema(copy) is not load_schema()
    assert load_schema(copy) == load_schema()


def test_broken_yaml_raises_value_error(tmp_path):
    bad = tmp_path / "unit_schema.yaml"
    bad.write_text("required: [\n")
    with pytest.raises(ValueError, match="not valid YAML"):
        load_schema(bad)


def _minimal() -> dict:
    return {
        "version": 1,
        "required": [{"name": "unit_type", "type": "enum", "values": ["room"], "description": "x"}],
        "optional": [],
        "derived": [{"name": "neighbourhood", "type": "str", "how": "postal", "description": "x"}],
    }


MALFORMED = [
    pytest.param(lambda d: d["required"][0].update(type="integer"), "unknown type", id="type"),
    pytest.param(lambda d: d["required"][0].pop("values"), "enum needs", id="enum-values"),
    pytest.param(lambda d: d["optional"].append(dict(d["required"][0])), "duplicate", id="dup"),
    pytest.param(lambda d: d["required"][0].pop("description"), "missing description", id="desc"),
    pytest.param(lambda d: d["required"][0].update(descripton="x"), "unknown keys", id="typo"),
    pytest.param(lambda d: d.pop("derived"), "'derived' must be a list", id="group"),
    pytest.param(lambda d: d.update(version="1"), "version", id="version"),
]


@pytest.mark.parametrize(("mutate", "message"), MALFORMED)
def test_malformed_schema_raises_value_error(tmp_path, mutate, message):
    data = _minimal()
    mutate(data)
    path = tmp_path / "unit_schema.yaml"
    path.write_text(yaml.safe_dump(data))
    with pytest.raises(ValueError, match=message):
        load_schema(path)
