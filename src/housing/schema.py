"""Loader for the unit schema contract (``schema/unit_schema.yaml``, HANDOFF section 3).

The scraper, the text extractor, the form and the model all read the schema through
:func:`load_schema`, so they agree on field names, types and enum values. Typical use::

    from housing.schema import load_schema

    schema = load_schema()
    schema.names("required")         # ('unit_type', 'bedrooms', 'lat', ...)
    schema.enum_values("unit_type")  # ('room', 'studio', '1bed', ...)
    schema.validate(record)          # [] when valid, else one message per problem

The YAML file is the contract; this module only reads it. Asking price is not a schema
field (it is the target), so a record passed to :meth:`UnitSchema.validate` never carries it.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from housing.paths import SCHEMA_PATH

GROUPS: tuple[str, ...] = ("required", "optional", "derived")
"""The three field groups, in file order."""

TYPES: tuple[str, ...] = ("enum", "int", "float", "bool", "str")
"""Allowed values of a field's ``type``. ``str`` exists for ``neighbourhood`` only."""

_TOP_KEYS = frozenset({"version", "notes", *GROUPS})
_FIELD_KEYS = frozenset({"name", "type", "description", "values", "min", "max", "how", "target"})


@dataclass(frozen=True)
class FieldSpec:
    """One field of the unit schema, as read from the YAML file.

    Attributes:
        name: Field name, as used in records and in the ``units`` table.
        group: ``required``, ``optional`` or ``derived``.
        type: ``enum``, ``int``, ``float``, ``bool`` or ``str``.
        description: What the field means and how it is extracted.
        values: The allowed strings of an ``enum`` field, else None.
        min: Smallest allowed value of a numeric field (inclusive), else None.
        max: Largest allowed value of a numeric field (inclusive), else None.
        how: How a ``derived`` field is computed, else None.
        target: True for the model target (``price_per_bedroom``) only.
    """

    name: str
    group: str
    type: str
    description: str
    values: tuple[str, ...] | None = None
    min: float | None = None
    max: float | None = None
    how: str | None = None
    target: bool = False


@dataclass(frozen=True)
class UnitSchema:
    """The unit schema: the file's version and its fields in file order.

    Attributes:
        version: The ``version`` value from the file.
        fields: Every field: required first, then optional, then derived.
    """

    version: int
    fields: tuple[FieldSpec, ...]

    @property
    def required(self) -> tuple[FieldSpec, ...]:
        """Fields a record must carry; no prediction without them."""
        return self._group("required")

    @property
    def optional(self) -> tuple[FieldSpec, ...]:
        """Fields that may be absent or None."""
        return self._group("optional")

    @property
    def derived(self) -> tuple[FieldSpec, ...]:
        """Fields computed by us and never supplied in a record."""
        return self._group("derived")

    def names(self, group: str | None = None) -> tuple[str, ...]:
        """Return field names in file order, for one group or for every field.

        Args:
            group: ``required``, ``optional``, ``derived``, or None for all fields.

        Raises:
            ValueError: If ``group`` is not one of the three groups.
        """
        fields = self.fields if group is None else self._group(group)
        return tuple(f.name for f in fields)

    def get(self, name: str) -> FieldSpec | None:
        """Return the field called ``name``, or None if the schema has no such field."""
        for spec in self.fields:
            if spec.name == name:
                return spec
        return None

    def __getitem__(self, name: str) -> FieldSpec:
        spec = self.get(name)
        if spec is None:
            raise KeyError(name)
        return spec

    def enum_values(self, name: str) -> tuple[str, ...]:
        """Return the allowed values of the enum field ``name``.

        Raises:
            KeyError: If there is no field called ``name``.
            ValueError: If the field is not an enum.
        """
        spec = self[name]
        if spec.values is None:
            raise ValueError(f"{name} is a {spec.type} field, not an enum")
        return spec.values

    def validate(self, record: Mapping[str, object]) -> list[str]:
        """Check one record against the schema and describe every problem found.

        Rules: every required field is present and not None; optional fields may be
        absent or None; a derived field or an unknown key is an error; an enum value
        must be one of the field's ``values``; ``int`` means an int (never a bool),
        ``float`` accepts an int or a float (never a bool, never NaN), ``bool`` means a
        bool; ``min`` and ``max`` are inclusive.

        Args:
            record: Field name to value, as the parser, the form or the extractor built it.

        Returns:
            Human-readable problems, each starting with the field name. Empty means valid.
        """
        problems = [f"{key}: not a schema field" for key in record if self.get(key) is None]
        for spec in self.fields:
            present = spec.name in record
            value = record.get(spec.name)
            if spec.group == "derived":
                if present:
                    problems.append(f"{spec.name}: derived field, computed by us, never supplied")
            elif value is None:
                if spec.group == "required":
                    state = "None" if present else "missing"
                    problems.append(f"{spec.name}: required field is {state}")
            else:
                problem = _check_value(spec, value)
                if problem is not None:
                    problems.append(problem)
        return problems

    def _group(self, group: str) -> tuple[FieldSpec, ...]:
        if group not in GROUPS:
            raise ValueError(f"unknown group {group!r}; expected one of {', '.join(GROUPS)}")
        return tuple(f for f in self.fields if f.group == group)


def _check_value(spec: FieldSpec, value: object) -> str | None:
    """Return the problem with a non-None ``value`` for ``spec``, or None if it is fine."""
    name, kind = spec.name, type(value).__name__
    if spec.type == "enum":
        values = spec.values or ()
        return None if value in values else f"{name}: {value!r} is not one of {', '.join(values)}"
    if spec.type == "bool":
        return None if isinstance(value, bool) else f"{name}: expected a bool, got {kind}"
    if spec.type == "str":
        return None if isinstance(value, str) else f"{name}: expected a str, got {kind}"
    # int and float. bool is a subclass of int in Python, so rule it out explicitly.
    want = "an int" if spec.type == "int" else "a number"
    if isinstance(value, bool) or not isinstance(value, int | float):
        return f"{name}: expected {want}, got {kind}"
    if spec.type == "int" and not isinstance(value, int):
        return f"{name}: expected an int, got {kind}"
    if isinstance(value, float) and math.isnan(value):
        return f"{name}: is NaN; use None for a missing value"
    if spec.min is not None and value < spec.min:
        return f"{name}: {value} is below the minimum {spec.min}"
    if spec.max is not None and value > spec.max:
        return f"{name}: {value} is above the maximum {spec.max}"
    return None


def load_schema(path: Path | None = None) -> UnitSchema:
    """Load the unit schema, by default the committed ``schema/unit_schema.yaml``.

    The result is cached per resolved path, so repeated calls return the same object.

    Args:
        path: Another schema file to load, for tests. None means the committed contract.

    Raises:
        ValueError: If the file is not valid YAML or does not have the expected structure.
        FileNotFoundError: If the file does not exist.
    """
    return _load_resolved(Path(path or SCHEMA_PATH).resolve())


@lru_cache
def _load_resolved(path: Path) -> UnitSchema:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"{path}: not valid YAML: {exc}") from exc
    return _parse_schema(data, str(path))


def _parse_schema(data: object, where: str) -> UnitSchema:
    """Turn the loaded YAML into a UnitSchema, rejecting anything unexpected."""
    if not isinstance(data, dict):
        raise ValueError(f"{where}: top level must be a mapping with version and the three groups")
    unknown = set(data) - _TOP_KEYS
    if unknown:
        raise ValueError(f"{where}: unknown top-level keys {sorted(unknown)}")
    version = data.get("version")
    if not isinstance(version, int) or isinstance(version, bool):
        raise ValueError(f"{where}: version must be an integer")
    fields: list[FieldSpec] = []
    for group in GROUPS:
        entries = data.get(group)
        if not isinstance(entries, list):
            raise ValueError(f"{where}: {group!r} must be a list of fields")
        fields.extend(_parse_field(raw, group, where) for raw in entries)
    names = [spec.name for spec in fields]
    duplicates = sorted({n for n in names if names.count(n) > 1})
    if duplicates:
        raise ValueError(f"{where}: duplicate field names {duplicates}")
    return UnitSchema(version=version, fields=tuple(fields))


def _parse_field(raw: object, group: str, where: str) -> FieldSpec:
    """Build one FieldSpec from its YAML mapping, rejecting anything unexpected."""
    if not isinstance(raw, dict) or not isinstance(raw.get("name"), str):
        raise ValueError(f"{where}: every entry under {group!r} needs a string 'name'")
    name = raw["name"]
    here = f"{where}: field {name!r} ({group})"
    unknown = set(raw) - _FIELD_KEYS
    if unknown:
        raise ValueError(f"{here}: unknown keys {sorted(unknown)}")
    kind = raw.get("type")
    if kind not in TYPES:
        raise ValueError(f"{here}: unknown type {kind!r}; expected one of {', '.join(TYPES)}")
    description = raw.get("description")
    if not isinstance(description, str) or not description.strip():
        raise ValueError(f"{here}: missing description")
    values = raw.get("values")
    if kind == "enum":
        if (
            not isinstance(values, list)
            or not values
            or not all(isinstance(v, str) for v in values)
        ):
            raise ValueError(f"{here}: an enum needs a non-empty list of string values")
    elif values is not None:
        raise ValueError(f"{here}: only an enum field takes values")
    for key in ("min", "max"):
        bound = raw.get(key)
        if bound is None:
            continue
        if (
            kind not in ("int", "float")
            or isinstance(bound, bool)
            or not isinstance(bound, int | float)
        ):
            raise ValueError(f"{here}: {key} must be a number on an int or float field")
    how = raw.get("how")
    if group == "derived" and not isinstance(how, str):
        raise ValueError(f"{here}: a derived field needs a 'how' sentence")
    if group != "derived" and how is not None:
        raise ValueError(f"{here}: only a derived field takes 'how'")
    target = raw.get("target", False)
    if not isinstance(target, bool):
        raise ValueError(f"{here}: target must be true or false")
    if target and group != "derived":
        raise ValueError(f"{here}: only a derived field can be the target")
    return FieldSpec(
        name=name,
        group=group,
        type=kind,
        description=description.strip(),
        values=tuple(values) if kind == "enum" else None,
        min=raw.get("min"),
        max=raw.get("max"),
        how=how,
        target=target,
    )
