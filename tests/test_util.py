"""Tests for airtable_proxy.util."""

import pytest
from pyairtable.testing import fake_id

from airtable_proxy.persistence import AirtablePersistence
from airtable_proxy.storage import Storage
from airtable_proxy.util import is_empty_value, resolve_table_id


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
