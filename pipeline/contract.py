"""
The contract described as data: schema.json.

pipeline/schemas.py declares the produced tables, the manifest's shape
and the recap document's frames; this module renders those declarations
as one JSON document a consumer generates its types from, so no column
list is ever written by hand in a second language. Two vocabularies,
deliberately: a table column's dtype is parquet-side (what the file
holds), a manifest field's type is JSON-side (what the document holds).
A document that is not a table (a recap) is a JSON-side header plus
frames described in the tables' column vocabulary, since each frame is
a table serialized as column arrays. The file has no timestamp, so a
rebuild under the same contract is byte-identical.
"""

import types
from typing import Any, Union, get_args, get_origin, get_type_hints, is_typeddict

import polars as pl

from pipeline.schemas import (
    DASHBOARD_OUTPUT_SCHEMAS,
    NULLABLE_COLUMNS,
    RECAP_FRAME_SCHEMAS,
    RECAP_NULLABLE_COLUMNS,
    SCHEMA_VERSION,
    Manifest,
    RecapHeader,
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

# Document name -> (header root, frame schemas, nullable registry): the
# JSON files that are not tables, each a scalar header and named frames.
DOCUMENT_ROOTS: dict[
    str, tuple[type, dict[str, pl.Schema], dict[str, frozenset[str]]]
] = {
    "recap": (RecapHeader, RECAP_FRAME_SCHEMAS, RECAP_NULLABLE_COLUMNS),
}


def build_contract_schema() -> dict:
    """
    Describe the published contract: tables, the manifest's shape, the documents.

    Returns:
        A JSON-serializable dict: ``schema_version``; ``tables``, the
        registry in order, each with its ordered ``columns`` of
        ``name`` / ``dtype`` / ``nullable``; ``manifest``, the TypedDict
        family as named ``types`` under a ``root``, each field a node of
        ``type`` / ``nullable`` (maps add ``values``); and ``documents``,
        each with its ``header`` (a typed block like the manifest's) and
        its ``frames`` (columns like the tables').

    Raises:
        ValueError: If a produced column's dtype is outside TABLE_DTYPES.
        TypeError: If a manifest or header field's annotation is outside
            the supported vocabulary.
    """
    tables = {
        name: {"columns": _columns(name, schema, NULLABLE_COLUMNS[name])}
        for name, schema in DASHBOARD_OUTPUT_SCHEMAS.items()
    }
    documents = {
        name: {
            "header": _typed_dict_block(root),
            "frames": {
                frame: {"columns": _columns(f"{name}.{frame}", schema, nullable[frame])}
                for frame, schema in frames.items()
            },
        }
        for name, (root, frames, nullable) in DOCUMENT_ROOTS.items()
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "tables": tables,
        "manifest": _typed_dict_block(MANIFEST_ROOT),
        "documents": documents,
    }


def _columns(where: str, schema: pl.Schema, nullable: frozenset[str]) -> list[dict]:
    """Render a frame's columns in order, each with its dtype name and flag."""
    return [
        {
            "name": column,
            "dtype": _table_dtype(where, column, dtype),
            "nullable": column in nullable,
        }
        for column, dtype in schema.items()
    ]


def _typed_dict_block(root: type) -> dict:
    """Render a TypedDict family as named types under its root."""
    named_types: dict[str, dict] = {}
    _register_typed_dict(root, named_types)
    return {"root": root.__name__, "types": named_types}


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
    if hint is Any:
        # An opaque value, taken as it comes: no shape the contract declares
        return {"type": "json", "nullable": nullable}
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
