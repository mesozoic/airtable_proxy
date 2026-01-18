import pytest

from airtable_proxy import storage


@pytest.fixture
def store(tmp_path):
    return storage.Storage(tmp_path / "test_storage")


def test_get_missing_key_returns_none(store):
    assert store.get("nonexistent") is None


def test_set_and_get(store):
    store.set("mykey", {"foo": "bar"})
    assert store.get("mykey") == {"foo": "bar"}


def test_set_overwrites_existing(store):
    store.set("mykey", "first")
    store.set("mykey", "second")
    assert store.get("mykey") == "second"


def test_delete(store):
    store.set("mykey", "value")
    store.delete("mykey")
    assert store.get("mykey") is None


def test_delete_nonexistent_key_is_noop(store):
    store.delete("nonexistent")  # Should not raise


def test_keys_with_prefix(store):
    store.set("webhook:app1", "w1")
    store.set("webhook:app2", "w2")
    store.set("record:app1:tbl1:rec1", "r1")

    webhook_keys = list(store.keys("webhook:"))
    assert sorted(webhook_keys) == ["webhook:app1", "webhook:app2"]

    record_keys = list(store.keys("record:"))
    assert record_keys == ["record:app1:tbl1:rec1"]


def test_keys_empty_prefix_returns_all(store):
    store.set("a", 1)
    store.set("b", 2)
    assert sorted(store.keys("")) == ["a", "b"]
