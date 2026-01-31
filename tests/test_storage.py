def test_get_missing_key_returns_none(storage):
    assert storage.get("nonexistent") is None


def test_set_and_get(storage):
    storage.set("mykey", {"foo": "bar"})
    assert storage.get("mykey") == {"foo": "bar"}


def test_set_overwrites_existing(storage):
    storage.set("mykey", "first")
    storage.set("mykey", "second")
    assert storage.get("mykey") == "second"


def test_delete(storage):
    storage.set("mykey", "value")
    storage.delete("mykey")
    assert storage.get("mykey") is None


def test_delete_nonexistent_key_is_noop(storage):
    storage.delete("nonexistent")  # Should not raise


def test_keys_with_prefix(storage):
    storage.set("webhook:app1", "w1")
    storage.set("webhook:app2", "w2")
    storage.set("record:app1:tbl1:rec1", "r1")

    webhook_keys = list(storage.keys("webhook:"))
    assert sorted(webhook_keys) == ["webhook:app1", "webhook:app2"]

    record_keys = list(storage.keys("record:"))
    assert record_keys == ["record:app1:tbl1:rec1"]


def test_keys_empty_prefix_returns_all(storage):
    storage.set("a", 1)
    storage.set("b", 2)
    assert sorted(storage.keys("")) == ["a", "b"]
