import os
import uuid

import pytest
from pyairtable import Api, Base


@pytest.fixture
def api_key():
    """
    Get API key from environment, skip if not set.
    """
    api_key = os.environ.get("AIRTABLE_API_KEY")
    if not api_key:
        pytest.skip("AIRTABLE_API_KEY not set")
    return api_key


@pytest.fixture
def api(api_key) -> Api:
    """
    Airtable API client for integration tests.
    """
    return Api(api_key)


@pytest.fixture
def base(api, base_id) -> Base:
    """
    Pre-existing test base for integration tests.
    """
    return api.base(base_id)


@pytest.fixture
def base_id():
    """
    Pre-existing test base for integration tests.
    """
    return "appaPqizdsNHDvlEm"


@pytest.fixture
def nonce():
    """
    Random nonce to ensure unique webhooks per test run.
    """
    return uuid.uuid4().hex[:8]


@pytest.fixture
def hostname(nonce):
    """
    Unique hostname for webhook callback URL.
    """
    return f"{nonce}.test.example.com"
