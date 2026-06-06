import os
import uuid

os.environ["AUTO_CREATE_TABLES"] = "false"

from fastapi.testclient import TestClient

from app.main import app


def test_health_check() -> None:
    client = TestClient(app)
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_request_id_header_is_returned() -> None:
    client = TestClient(app)
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert uuid.UUID(response.headers["x-request-id"])


def test_request_id_header_is_reused_when_provided() -> None:
    client = TestClient(app)
    response = client.get("/api/v1/health", headers={"X-Request-ID": "req-from-client"})

    assert response.status_code == 200
    assert response.headers["x-request-id"] == "req-from-client"


def test_document_recognition_requires_explicit_user() -> None:
    client = TestClient(app)
    response = client.post("/api/v1/documents/00000000-0000-0000-0000-000000000000/recognize")

    assert response.status_code == 422
