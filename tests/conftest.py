from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

TEST_RULES = Path(__file__).parent / "rules"


@pytest.fixture
def client(tmp_path):
    app = create_app(db_path=tmp_path / "test.db", rules_dir=TEST_RULES)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def named(client):
    client.post("/naam", data={"new_name": "Sanne"})
    return client
