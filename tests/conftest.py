import os
from pathlib import Path

import pytest

RECORD_HEADERS = ("content-type", "content-length", "content-encoding", "date")


def scrub_vcr_response(response):
    response["headers"] = {
        key: value
        for key, value in response["headers"].items()
        if key.lower() in RECORD_HEADERS
    }
    return response


@pytest.fixture(scope="module")
def vcr_config():
    return {
        # Replace the Authorization request header in cassettes
        "filter_headers": [("Authorization", ""), ("Cookie", "")],
        "record_mode": os.environ.get("VCR_RECORD_MODE", "none"),  # "new_episodes",
        "before_record_response": scrub_vcr_response,
    }


@pytest.fixture(scope="module")
def vcr_cassette_dir(request):
    # Put all cassettes in tests/cassettes/
    return str(Path(__file__).parent / "cassettes")


@pytest.fixture
def vcr_cassette_name(request):
    # Name all cassettes {module}.{test}.yaml
    return request.module.__name__ + "." + request.function.__name__ + ".yaml"


@pytest.fixture
def api_key():
    return os.environ["AIRTABLE_API_KEY"]


@pytest.fixture
def base_id():
    return "appG3A7GCIJjrjf8j"


@pytest.fixture
def table_id():
    return "tblH5kStARFR6wTwX"
