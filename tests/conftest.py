from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def vcr_config():
    return {
        # Replace the Authorization request header in cassettes
        "filter_headers": [("authorization", "")],
        "record_mode": "new_episodes",
    }


@pytest.fixture(scope="module")
def vcr_cassette_dir(request):
    # Put all cassettes in tests/cassettes/
    return str(Path(__file__).parent / "cassettes")


@pytest.fixture
def vcr_cassette_name(request):
    # Name all cassettes {module}.{test}.yaml
    return request.module.__name__ + "." + request.function.__name__ + ".yaml"
