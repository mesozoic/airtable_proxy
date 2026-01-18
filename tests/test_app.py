from fastapi.testclient import TestClient

from airtable_proxy import app
from airtable_proxy.config import Config


def make_config(tmp_path):
    return Config(
        hostname="test.example.com",
        bases={},
        storage={"sqlite": tmp_path / "test.db"},
    )


def test_health_endpoint(tmp_path):
    application = app.create_app(config=make_config(tmp_path))
    with TestClient(application) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


def test_persistence_available_in_app_state(tmp_path):
    application = app.create_app(config=make_config(tmp_path))
    with TestClient(application):
        assert application.state.persistence is not None
