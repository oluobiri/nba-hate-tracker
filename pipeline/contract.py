"""
The contract described as data: schema.json.

pipeline/schemas.py declares the produced tables and the manifest's
shape; this module renders those declarations as one JSON document a
consumer generates its types from, so no column list is ever written
by hand in a second language. Two vocabularies, deliberately: a table
column's dtype is parquet-side (what the file holds), a manifest
field's type is JSON-side (what the document holds). The document has
no timestamp, so a rebuild under the same contract is byte-identical.
"""

import types
from typing import Union, get_args, get_origin, get_type_hints, is_typeddict

import polars as pl

from pipeline.schemas import (
    DASHBOARD_OUTPUT_SCHEMAS,
    NULLABLE_COLUMNS,
    SCHEMA_VERSION,
    Manifest,
)

# Parquet-side dtype names: the closed vocabulary a type generator needs.
TABLE_DTYPES: dict[pl.DataType, str] = {
    pl.String: "string",
    pl.Int64: "int64",
    pl.Float64: "float64",
    pl.Boolean: "bool",
    pl.Date: "date",
    pl.Datetime("us"): "datetime",
    pl.List(pl.String): "list<string>",
}

# JSON-side names for the manifest's scalar fields.
MANIFEST_PRIMITIVES: dict[type, str] = {
    str: "string",
    int: "int",
    float: "float",
    bool: "bool",
}

MANIFEST_ROOT = Manifest


def build_contract_schema() -> dict:
    """
    Describe the published contract: every table's columns and the manifest's shape.

    Returns:
        A JSON-serializable dict: ``schema_version``; ``tables``, the
        registry in order, each with its ordered ``columns`` of
        ``name`` / ``dtype`` / ``nullable``; and ``manifest``, the
        TypedDict family as named ``types`` under a ``root``, each field
        a node of ``type`` / ``nullable`` (maps add ``values``).

    Raises:
        ValueError: If a produced column's dtype is outside TABLE_DTYPES.
        TypeError: If a manifest field's annotation is outside the
            supported vocabulary.
    """
    tables = {
        name: {
            "columns": [
                {
                    "name": column,
                    "dtype": _table_dtype(name, column, dtype),
                    "nullable": column in NULLABLE_COLUMNS[name],
                }
                for column, dtype in schema.items()
            ]
        }
        for name, schema in DASHBOARD_OUTPUT_SCHEMAS.items()
    }
    named_types: dict[str, dict] = {}
    _register_typed_dict(MANIFEST_ROOT, named_types)
    return {
        "schema_version": SCHEMA_VERSION,
        "tables": tables,
        "manifest": {"root": MANIFEST_ROOT.__name__, "types": named_types},
    }


def _table_dtype(table: str, column: str, dtype: pl.DataType) -> str:
    """Name a column's dtype in the parquet-side vocabulary."""
    try:
        return TABLE_DTYPES[dtype]
    except KeyError:
        raise ValueError(
            f"{table}.{column}: dtype {dtype} is not in the contract vocabulary"
        ) from None


def _register_typed_dict(typed_dict: type, named_types: dict[str, dict]) -> None:
    """Add a TypedDict's fields to the named types, root first, then what it references."""
    name = typed_dict.__name__
    if name in named_types:
        return
    fields: dict[str, dict] = {}
    named_types[name] = fields  # registered before recursing: root stays first
    for field, hint in get_type_hints(typed_dict).items():
        fields[field] = _field_node(f"{name}.{field}", hint, named_types)


def _field_node(where: str, hint: object, named_types: dict[str, dict]) -> dict:
    """Render one annotation as a type node, unwrapping X | None into nullable."""
    nullable = False
    if get_origin(hint) in (types.UnionType, Union):
        inner = [arg for arg in get_args(hint) if arg is not type(None)]
        if len(inner) != 1 or len(get_args(hint)) != 2:
            raise TypeError(f"{where}: only X | None unions are supported, got {hint}")
        hint, nullable = inner[0], True

    if hint in MANIFEST_PRIMITIVES:
        return {"type": MANIFEST_PRIMITIVES[hint], "nullable": nullable}
    if get_origin(hint) is dict:
        key, value = get_args(hint)
        if key is not str:
            raise TypeError(f"{where}: JSON object keys must be str, got {key}")
        return {
            "type": "map",
            "values": _field_node(where, value, named_types),
            "nullable": nullable,
        }
    if is_typeddict(hint):
        _register_typed_dict(hint, named_types)
        return {"type": hint.__name__, "nullable": nullable}
    raise TypeError(f"{where}: unsupported annotation {hint}")
