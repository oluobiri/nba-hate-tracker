"""Tests for pipeline/contract.py: schema.json generated from the contract."""

import json
from typing import TypedDict

import polars as pl
import pytest

from pipeline.contract import TABLE_DTYPES, build_contract_schema
from pipeline.schemas import (
    DASHBOARD_OUTPUT_SCHEMAS,
    NULLABLE_COLUMNS,
    SCHEMA_VERSION,
    ClassifierIdentity,
    Corpus,
    Floors,
    Manifest,
    ReceiptsFigures,
    Rules,
    SamplesRule,
    TableEntry,
)

MANIFEST_FAMILY = (
    Manifest,
    ClassifierIdentity,
    SamplesRule,
    ReceiptsFigures,
    Floors,
    Rules,
    Corpus,
    TableEntry,
)


def _distinct_dashboard_dtypes() -> list[pl.DataType]:
    """Every dtype used by a produced table, once each."""
    seen: list[pl.DataType] = []
    for schema in DASHBOARD_OUTPUT_SCHEMAS.values():
        for dtype in schema.dtypes():
            if dtype not in seen:
                seen.append(dtype)
    return seen


class TestBuildContractSchema:
    """The file's three blocks: version, tables, manifest."""

    @pytest.fixture
    def contract(self) -> dict:
        return build_contract_schema()

    def test_stamps_the_contract_version(self, contract):
        """The file says which contract it describes."""
        assert contract["schema_version"] == SCHEMA_VERSION
        assert list(contract) == ["schema_version", "tables", "manifest"]

    def test_is_deterministic_json(self, contract):
        """No timestamp, no set ordering: two builds are byte-identical, so
        a rebuild publishes nothing new."""
        assert json.dumps(contract) == json.dumps(build_contract_schema())

    def test_tables_are_the_registry_in_order(self, contract):
        """Every produced table appears, keyed and ordered as the registry."""
        assert list(contract["tables"]) == list(DASHBOARD_OUTPUT_SCHEMAS)

    def test_columns_follow_each_schema_in_order(self, contract):
        """Column order is part of the contract, so it is an array."""
        for name, schema in DASHBOARD_OUTPUT_SCHEMAS.items():
            columns = contract["tables"][name]["columns"]
            assert [c["name"] for c in columns] == schema.names(), name

    def test_nullable_flags_are_the_registry(self, contract):
        """Each column's flag is its membership in NULLABLE_COLUMNS."""
        for name in DASHBOARD_OUTPUT_SCHEMAS:
            for column in contract["tables"][name]["columns"]:
                expected = column["name"] in NULLABLE_COLUMNS[name]
                assert column["nullable"] is expected, f"{name}.{column['name']}"

    @pytest.mark.parametrize("dtype", _distinct_dashboard_dtypes(), ids=repr)
    def test_every_dashboard_dtype_is_in_the_vocabulary(self, dtype):
        """The closed vocabulary covers every dtype a produced table uses."""
        assert dtype in TABLE_DTYPES

    @pytest.mark.parametrize(
        "table,column,expected",
        [
            ("player_overall", "attributed_player", "string"),
            ("player_overall", "player_id", "int64"),
            ("player_overall", "neg_rate", "float64"),
            ("player_temporal", "week", "datetime"),
            ("players", "birth_date", "date"),
            ("player_games", "is_home", "bool"),
        ],
    )
    def test_dtype_names(self, contract, table, column, expected):
        """Spot-check the parquet-side vocabulary on real columns."""
        columns = {c["name"]: c for c in contract["tables"][table]["columns"]}
        assert columns[column]["dtype"] == expected

    def test_unmapped_dtype_raises(self, monkeypatch):
        """A dtype outside the vocabulary is a build failure naming the
        column, never a silent guess."""
        monkeypatch.setattr(
            "pipeline.contract.DASHBOARD_OUTPUT_SCHEMAS",
            {"odd": pl.Schema({"x": pl.Int32})},
        )
        monkeypatch.setattr("pipeline.contract.NULLABLE_COLUMNS", {"odd": frozenset()})

        with pytest.raises(ValueError, match="odd.x"):
            build_contract_schema()


class TestManifestBlock:
    """The manifest's own shape: named types with refs, root Manifest."""

    @pytest.fixture
    def manifest(self) -> dict:
        return build_contract_schema()["manifest"]

    def test_root_is_manifest_and_first(self, manifest):
        """The consumer starts at the root; it is the first type listed."""
        assert manifest["root"] == "Manifest"
        assert next(iter(manifest["types"])) == "Manifest"

    def test_every_typed_dict_in_the_family_is_present(self, manifest):
        """Every TypedDict reachable from Manifest gets its own named type."""
        assert set(manifest["types"]) == {td.__name__ for td in MANIFEST_FAMILY}

    @pytest.mark.parametrize("typed_dict", MANIFEST_FAMILY, ids=lambda t: t.__name__)
    def test_fields_follow_annotation_order(self, manifest, typed_dict):
        """Field order mirrors the Python declaration, so the TS interface
        reads as the file does."""
        fields = manifest["types"][typed_dict.__name__]
        assert list(fields) == list(typed_dict.__annotations__)

    def test_primitives(self, manifest):
        """int, str, float and bool map to the JSON-side names."""
        root = manifest["types"]["Manifest"]
        assert root["schema_version"] == {"type": "int", "nullable": False}
        assert root["season"] == {"type": "string", "nullable": False}
        samples = manifest["types"]["SamplesRule"]
        assert samples["min_confidence"] == {"type": "float", "nullable": False}
        assert samples["requires_target"] == {"type": "bool", "nullable": False}

    def test_optional_marks_nullable(self, manifest):
        """X | None is the same type with nullable true."""
        assert manifest["types"]["TableEntry"]["population"] == {
            "type": "string",
            "nullable": True,
        }
        assert manifest["types"]["Corpus"]["raw_comments"] == {
            "type": "int",
            "nullable": True,
        }
        assert manifest["types"]["ReceiptsFigures"]["coverage"] == {
            "type": "float",
            "nullable": True,
        }

    def test_maps_carry_their_value_node(self, manifest):
        """dict[str, X] is a map whose values node is X, nullability
        included: the calendar's values may be null, the tables' may not."""
        root = manifest["types"]["Manifest"]
        assert root["config_versions"] == {
            "type": "map",
            "values": {"type": "string", "nullable": False},
            "nullable": False,
        }
        assert root["calendar"] == {
            "type": "map",
            "values": {"type": "string", "nullable": True},
            "nullable": False,
        }
        assert root["tables"] == {
            "type": "map",
            "values": {"type": "TableEntry", "nullable": False},
            "nullable": False,
        }

    def test_nested_typed_dicts_are_refs(self, manifest):
        """A nested TypedDict field references its type by name."""
        assert manifest["types"]["Manifest"]["rules"] == {
            "type": "Rules",
            "nullable": False,
        }
        assert manifest["types"]["Rules"]["floors"] == {
            "type": "Floors",
            "nullable": False,
        }

    def test_unsupported_hint_raises(self, monkeypatch):
        """A field type outside the vocabulary fails the build by name."""

        class Odd(TypedDict):
            items: list[str]

        monkeypatch.setattr("pipeline.contract.MANIFEST_ROOT", Odd)

        with pytest.raises(TypeError, match="Odd.items"):
            build_contract_schema()
