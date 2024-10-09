import pyairtable
import pytest
from pyairtable.utils import is_field_id

from airtable_proxy.record_cache import RecordCache

pytestmark = [pytest.mark.vcr()]


@pytest.fixture
def cache(tmp_path, api_key, base_id):
    api = pyairtable.Api(api_key)
    cache = RecordCache(tmp_path, api)
    cache.reload_base(base_id)
    return cache


@pytest.fixture
def forbid_requests(requests_mock):
    pass


def test_base_schema(cache, base_id, table_id, forbid_requests):
    assert len(cache.base_schema(base_id).tables) == 1
    assert cache.base_schema(base_id).table(table_id).name == "Table 1"


@pytest.mark.parametrize(
    "use_field_ids,expected_field",
    [
        (True, "fldRLjMJMBjUbn6XF"),
        (False, "Name"),
    ],
)
@pytest.mark.parametrize(
    "table_id_or_name",
    [
        "tblH5kStARFR6wTwX",
        "Table 1",
    ],
)
def test_get_record(
    cache,
    base_id,
    table_id_or_name,
    use_field_ids,
    expected_field,
    forbid_requests,
):
    record_id = "rec2gjdwMTRE5EewZ"
    result = cache.get_record(
        base_id, table_id_or_name, record_id, use_field_ids=use_field_ids
    )
    assert result == {
        "id": record_id,
        "createdTime": "2023-08-07T17:19:36.000Z",
        "fields": {expected_field: "Alpha"},
    }


@pytest.mark.parametrize("use_field_ids", (True, False))
@pytest.mark.parametrize("table_id_or_name", ["tblH5kStARFR6wTwX", "Table 1"])
def test_get_records(
    cache,
    base_id,
    table_id_or_name,
    use_field_ids,
    forbid_requests,
):
    records = cache.get_records(base_id, table_id_or_name, use_field_ids=use_field_ids)
    assert len(records) == 5
    assert {is_field_id(key) for r in records for key in r["fields"]} == {use_field_ids}
