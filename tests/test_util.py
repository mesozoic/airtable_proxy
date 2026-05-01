"""Tests for airtable_proxy.util."""

import pytest
from pyairtable.testing import fake_id

from airtable_proxy.persistence import AirtablePersistence, FieldInfo, RecordInfo
from airtable_proxy.storage import Storage
from airtable_proxy.util import format_record_fields, is_empty_value, resolve_table_id


@pytest.mark.parametrize("value", [None, "", [], False])
def test_is_empty_value_true(value):
    assert is_empty_value(value) is True


@pytest.mark.parametrize("value", ["x", 0, [None], True, {"k": "v"}])
def test_is_empty_value_false(value):
    assert is_empty_value(value) is False


@pytest.fixture
def persist(tmp_path):
    storage = Storage(tmp_path / "test.db")
    yield AirtablePersistence(storage)
    storage.close()


def test_resolve_table_id_by_id(persist):
    base_id = fake_id("app")
    table_id = fake_id("tbl")
    persist.save_table(base_id, table_id, "My Table")

    assert resolve_table_id(base_id, table_id, persist) == table_id


def test_resolve_table_id_by_name(persist):
    base_id = fake_id("app")
    table_id = fake_id("tbl")
    persist.save_table(base_id, table_id, "My Table")

    assert resolve_table_id(base_id, "My Table", persist) == table_id


def test_resolve_table_id_unknown_id(persist):
    base_id = fake_id("app")
    assert resolve_table_id(base_id, fake_id("tbl"), persist) is None


def test_resolve_table_id_unknown_name(persist):
    base_id = fake_id("app")
    assert resolve_table_id(base_id, "Nope", persist) is None


def test_resolve_table_id_id_prefix_but_missing_falls_through_to_name(persist):
    """A 'tbl'-prefixed value that isn't stored should still match by name."""
    base_id = fake_id("app")
    table_id = fake_id("tbl")
    fake_name = fake_id("tbl")  # also looks like a table id
    persist.save_table(base_id, table_id, fake_name)

    assert resolve_table_id(base_id, fake_name, persist) == table_id


def _record(fields):
    return RecordInfo(fields=fields, created_time="2024-01-01T00:00:00.000Z")


def _fields(*specs):
    """specs is an iterable of (field_id, field_name) tuples."""
    return {fid: FieldInfo(field_name=name, field_type="singleLineText") for fid, name in specs}


def test_format_record_fields_keys_by_name_by_default():
    record = _record({"fld1": "Alice", "fld2": 30})
    fields = _fields(("fld1", "Name"), ("fld2", "Age"))

    result = format_record_fields(record, fields, return_fields_by_field_id=False)

    assert result == {"Name": "Alice", "Age": 30}


def test_format_record_fields_keys_by_id_when_requested():
    record = _record({"fld1": "Alice", "fld2": 30})
    fields = _fields(("fld1", "Name"), ("fld2", "Age"))

    result = format_record_fields(record, fields, return_fields_by_field_id=True)

    assert result == {"fld1": "Alice", "fld2": 30}


def test_format_record_fields_omits_empty_values():
    record = _record({"fld1": "Alice", "fld2": "", "fld3": None, "fld4": False, "fld5": []})
    fields = _fields(
        ("fld1", "Name"), ("fld2", "Empty"), ("fld3", "Null"), ("fld4", "Off"), ("fld5", "List")
    )

    result = format_record_fields(record, fields, return_fields_by_field_id=False)

    assert result == {"Name": "Alice"}


def test_format_record_fields_falls_back_to_id_when_name_unknown():
    """If a record has a field that isn't in field_info, fall back to the field ID."""
    record = _record({"fld1": "Alice", "fld_unknown": "Mystery"})
    fields = _fields(("fld1", "Name"))

    result = format_record_fields(record, fields, return_fields_by_field_id=False)

    assert result == {"Name": "Alice", "fld_unknown": "Mystery"}


def test_format_record_fields_filters_by_include_set_by_id():
    record = _record({"fld1": "Alice", "fld2": 30, "fld3": True})
    fields = _fields(("fld1", "Name"), ("fld2", "Age"), ("fld3", "Active"))

    result = format_record_fields(
        record, fields, return_fields_by_field_id=False, include_field_ids={"fld1", "fld3"}
    )

    assert result == {"Name": "Alice", "Active": True}


def test_format_record_fields_empty_include_set_returns_no_fields():
    record = _record({"fld1": "Alice"})
    fields = _fields(("fld1", "Name"))

    result = format_record_fields(
        record, fields, return_fields_by_field_id=False, include_field_ids=set()
    )

    assert result == {}
