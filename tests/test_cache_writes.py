"""Tests for the cache_writes module."""

from pyairtable.testing import fake_id

from airtable_proxy import cache_writes
from airtable_proxy.persistence import AirtablePersistence
from airtable_proxy.storage import Storage

BASE_ID = fake_id("app")
TABLE_ID = fake_id("tbl")
FLD_NAME = fake_id("fld")
FLD_AGE = fake_id("fld")
REC_1 = fake_id("rec")
REC_2 = fake_id("rec")


def make_persistence(tmp_path):
    storage = Storage(tmp_path / "test.db")
    persistence = AirtablePersistence(storage)
    persistence.save_table(BASE_ID, TABLE_ID, "Test Table")
    persistence.save_field(BASE_ID, TABLE_ID, FLD_NAME, "Name", "singleLineText")
    persistence.save_field(BASE_ID, TABLE_ID, FLD_AGE, "Age", "number")
    return persistence


def test_apply_create_single_record_with_field_names(tmp_path):
    persistence = make_persistence(tmp_path)
    body = {
        "id": REC_1,
        "createdTime": "2024-01-01T00:00:00.000Z",
        "fields": {"Name": "Alice", "Age": 30},
    }

    cache_writes.apply_create(persistence, BASE_ID, TABLE_ID, body, response_uses_field_ids=False)

    stored = persistence.get_record(BASE_ID, TABLE_ID, REC_1)
    assert stored is not None
    assert stored.created_time == "2024-01-01T00:00:00.000Z"
    assert stored.fields == {FLD_NAME: "Alice", FLD_AGE: 30}


def test_apply_create_multi_record_response(tmp_path):
    persistence = make_persistence(tmp_path)
    body = {
        "records": [
            {
                "id": REC_1,
                "createdTime": "2024-01-01T00:00:00.000Z",
                "fields": {"Name": "Alice"},
            },
            {
                "id": REC_2,
                "createdTime": "2024-01-02T00:00:00.000Z",
                "fields": {"Name": "Bob"},
            },
        ]
    }

    cache_writes.apply_create(persistence, BASE_ID, TABLE_ID, body, response_uses_field_ids=False)

    assert persistence.get_record(BASE_ID, TABLE_ID, REC_1).fields == {FLD_NAME: "Alice"}
    assert persistence.get_record(BASE_ID, TABLE_ID, REC_2).fields == {FLD_NAME: "Bob"}


def test_apply_create_upsert_response_ignores_created_and_updated_arrays(tmp_path):
    persistence = make_persistence(tmp_path)
    body = {
        "records": [
            {
                "id": REC_1,
                "createdTime": "2024-01-01T00:00:00.000Z",
                "fields": {"Name": "Alice"},
            }
        ],
        "createdRecords": [REC_1],
        "updatedRecords": [],
    }

    cache_writes.apply_create(persistence, BASE_ID, TABLE_ID, body, response_uses_field_ids=False)

    assert persistence.get_record(BASE_ID, TABLE_ID, REC_1).fields == {FLD_NAME: "Alice"}


def test_apply_create_passes_through_field_ids_when_flag_set(tmp_path):
    persistence = make_persistence(tmp_path)
    body = {
        "id": REC_1,
        "createdTime": "2024-01-01T00:00:00.000Z",
        "fields": {FLD_NAME: "Alice", FLD_AGE: 30},
    }

    cache_writes.apply_create(persistence, BASE_ID, TABLE_ID, body, response_uses_field_ids=True)

    stored = persistence.get_record(BASE_ID, TABLE_ID, REC_1)
    assert stored.fields == {FLD_NAME: "Alice", FLD_AGE: 30}


def test_apply_create_skips_unknown_field_name(tmp_path):
    persistence = make_persistence(tmp_path)
    body = {
        "id": REC_1,
        "createdTime": "2024-01-01T00:00:00.000Z",
        "fields": {"Name": "Alice", "Unknown": "x"},
    }

    cache_writes.apply_create(persistence, BASE_ID, TABLE_ID, body, response_uses_field_ids=False)

    stored = persistence.get_record(BASE_ID, TABLE_ID, REC_1)
    assert stored.fields == {FLD_NAME: "Alice"}


def test_apply_create_with_missing_id_logs_and_skips_record(tmp_path, caplog):
    persistence = make_persistence(tmp_path)
    body = {"records": [{"createdTime": "x", "fields": {"Name": "Alice"}}]}

    with caplog.at_level("WARNING", logger="airtable_proxy.cache_writes"):
        cache_writes.apply_create(
            persistence, BASE_ID, TABLE_ID, body, response_uses_field_ids=False
        )

    assert persistence.get_records(BASE_ID, TABLE_ID) == {}
    assert any("missing 'id'" in rec.message for rec in caplog.records)


def test_apply_create_with_unrecognized_body_shape_does_nothing(tmp_path):
    persistence = make_persistence(tmp_path)
    body = {"unrecognized": "shape"}

    cache_writes.apply_create(persistence, BASE_ID, TABLE_ID, body, response_uses_field_ids=False)

    assert persistence.get_records(BASE_ID, TABLE_ID) == {}


def test_apply_update_merges_with_existing_record(tmp_path):
    persistence = make_persistence(tmp_path)
    persistence.save_record(
        BASE_ID,
        TABLE_ID,
        REC_1,
        {FLD_NAME: "Alice", FLD_AGE: 30},
        "2024-01-01T00:00:00.000Z",
    )
    body = {
        "id": REC_1,
        "createdTime": "2024-01-01T00:00:00.000Z",
        "fields": {"Age": 31},
    }

    cache_writes.apply_update(persistence, BASE_ID, TABLE_ID, body, response_uses_field_ids=False)

    stored = persistence.get_record(BASE_ID, TABLE_ID, REC_1)
    assert stored.fields == {FLD_NAME: "Alice", FLD_AGE: 31}
    assert stored.created_time == "2024-01-01T00:00:00.000Z"


def test_apply_update_replace_clears_unspecified_fields(tmp_path):
    persistence = make_persistence(tmp_path)
    persistence.save_record(
        BASE_ID,
        TABLE_ID,
        REC_1,
        {FLD_NAME: "Alice", FLD_AGE: 30},
        "2024-01-01T00:00:00.000Z",
    )
    body = {
        "id": REC_1,
        "createdTime": "2024-01-01T00:00:00.000Z",
        "fields": {"Name": "Alicia"},
    }

    cache_writes.apply_update(
        persistence,
        BASE_ID,
        TABLE_ID,
        body,
        response_uses_field_ids=False,
        replace=True,
    )

    stored = persistence.get_record(BASE_ID, TABLE_ID, REC_1)
    assert stored.fields == {FLD_NAME: "Alicia"}


def test_apply_update_missing_record_is_treated_as_create(tmp_path):
    persistence = make_persistence(tmp_path)
    body = {
        "id": REC_1,
        "createdTime": "2024-01-01T00:00:00.000Z",
        "fields": {"Name": "Alice"},
    }

    cache_writes.apply_update(persistence, BASE_ID, TABLE_ID, body, response_uses_field_ids=False)

    stored = persistence.get_record(BASE_ID, TABLE_ID, REC_1)
    assert stored.fields == {FLD_NAME: "Alice"}


def test_apply_update_missing_record_with_replace_is_treated_as_create(tmp_path):
    persistence = make_persistence(tmp_path)
    body = {
        "id": REC_1,
        "createdTime": "2024-01-01T00:00:00.000Z",
        "fields": {"Name": "Alice"},
    }

    cache_writes.apply_update(
        persistence,
        BASE_ID,
        TABLE_ID,
        body,
        response_uses_field_ids=False,
        replace=True,
    )

    stored = persistence.get_record(BASE_ID, TABLE_ID, REC_1)
    assert stored.fields == {FLD_NAME: "Alice"}
    assert stored.created_time == "2024-01-01T00:00:00.000Z"


def test_apply_update_multi_record_response_with_upsert_shape(tmp_path):
    persistence = make_persistence(tmp_path)
    persistence.save_record(
        BASE_ID,
        TABLE_ID,
        REC_1,
        {FLD_NAME: "Old"},
        "2024-01-01T00:00:00.000Z",
    )
    body = {
        "records": [
            {
                "id": REC_1,
                "createdTime": "2024-01-01T00:00:00.000Z",
                "fields": {"Name": "New"},
            },
            {
                "id": REC_2,
                "createdTime": "2024-02-01T00:00:00.000Z",
                "fields": {"Name": "Brand New"},
            },
        ],
        "createdRecords": [REC_2],
        "updatedRecords": [REC_1],
    }

    cache_writes.apply_update(persistence, BASE_ID, TABLE_ID, body, response_uses_field_ids=False)

    assert persistence.get_record(BASE_ID, TABLE_ID, REC_1).fields == {FLD_NAME: "New"}
    assert persistence.get_record(BASE_ID, TABLE_ID, REC_2).fields == {FLD_NAME: "Brand New"}


def test_apply_update_with_missing_id_logs_and_skips_record(tmp_path, caplog):
    persistence = make_persistence(tmp_path)
    body = {"records": [{"createdTime": "x", "fields": {"Name": "Alice"}}]}

    with caplog.at_level("WARNING", logger="airtable_proxy.cache_writes"):
        cache_writes.apply_update(
            persistence, BASE_ID, TABLE_ID, body, response_uses_field_ids=False
        )

    assert persistence.get_records(BASE_ID, TABLE_ID) == {}
    assert any("missing 'id'" in rec.message for rec in caplog.records)


def test_apply_delete_single_record_shape(tmp_path):
    persistence = make_persistence(tmp_path)
    persistence.save_record(
        BASE_ID,
        TABLE_ID,
        REC_1,
        {FLD_NAME: "Alice"},
        "2024-01-01T00:00:00.000Z",
    )

    cache_writes.apply_delete(persistence, BASE_ID, TABLE_ID, {"id": REC_1, "deleted": True})

    assert persistence.get_record(BASE_ID, TABLE_ID, REC_1) is None


def test_apply_delete_multi_record_shape(tmp_path):
    persistence = make_persistence(tmp_path)
    persistence.save_record(
        BASE_ID,
        TABLE_ID,
        REC_1,
        {FLD_NAME: "Alice"},
        "2024-01-01T00:00:00.000Z",
    )
    persistence.save_record(
        BASE_ID,
        TABLE_ID,
        REC_2,
        {FLD_NAME: "Bob"},
        "2024-01-02T00:00:00.000Z",
    )

    cache_writes.apply_delete(
        persistence,
        BASE_ID,
        TABLE_ID,
        {"records": [{"id": REC_1, "deleted": True}, {"id": REC_2, "deleted": True}]},
    )

    assert persistence.get_record(BASE_ID, TABLE_ID, REC_1) is None
    assert persistence.get_record(BASE_ID, TABLE_ID, REC_2) is None


def test_apply_delete_missing_record_is_a_noop(tmp_path):
    persistence = make_persistence(tmp_path)

    cache_writes.apply_delete(persistence, BASE_ID, TABLE_ID, {"id": REC_1, "deleted": True})

    assert persistence.get_record(BASE_ID, TABLE_ID, REC_1) is None


def test_apply_delete_with_unrecognized_body_shape_does_nothing(tmp_path):
    persistence = make_persistence(tmp_path)
    persistence.save_record(
        BASE_ID,
        TABLE_ID,
        REC_1,
        {FLD_NAME: "Alice"},
        "2024-01-01T00:00:00.000Z",
    )

    cache_writes.apply_delete(persistence, BASE_ID, TABLE_ID, {"unrecognized": "shape"})

    assert persistence.get_record(BASE_ID, TABLE_ID, REC_1) is not None


def test_apply_delete_with_missing_id_logs_and_skips_record(tmp_path, caplog):
    persistence = make_persistence(tmp_path)
    persistence.save_record(
        BASE_ID,
        TABLE_ID,
        REC_1,
        {FLD_NAME: "Alice"},
        "2024-01-01T00:00:00.000Z",
    )

    with caplog.at_level("WARNING", logger="airtable_proxy.cache_writes"):
        cache_writes.apply_delete(
            persistence,
            BASE_ID,
            TABLE_ID,
            {"records": [{"deleted": True}]},
        )

    assert persistence.get_record(BASE_ID, TABLE_ID, REC_1) is not None
    assert any("missing 'id'" in rec.message for rec in caplog.records)
