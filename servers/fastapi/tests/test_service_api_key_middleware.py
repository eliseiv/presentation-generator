import os
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.middlewares import ServiceApiKeyMiddleware


def create_test_client() -> TestClient:
    app = FastAPI()
    app.add_middleware(ServiceApiKeyMiddleware)

    @app.get("/api/v1/protected")
    async def protected_route():
        return {"ok": True}

    @app.get("/public")
    async def public_route():
        return {"ok": True}

    return TestClient(app)


def test_service_api_key_allows_valid_x_api_key():
    client = create_test_client()

    with patch.dict(os.environ, {"SERVICE_API_KEY": "service-secret"}):
        response = client.get(
            "/api/v1/protected",
            headers={"X-API-Key": "service-secret"},
        )

    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_service_api_key_allows_valid_bearer_token():
    client = create_test_client()

    with patch.dict(os.environ, {"SERVICE_API_KEY": "service-secret"}):
        response = client.get(
            "/api/v1/protected",
            headers={"Authorization": "Bearer service-secret"},
        )

    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_service_api_key_rejects_missing_key():
    client = create_test_client()

    with patch.dict(os.environ, {"SERVICE_API_KEY": "service-secret"}):
        response = client.get("/api/v1/protected")

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid or missing API key"


def test_service_api_key_requires_server_configuration():
    client = create_test_client()

    with patch.dict(os.environ, {}, clear=True):
        response = client.get(
            "/api/v1/protected",
            headers={"X-API-Key": "service-secret"},
        )

    assert response.status_code == 500
    assert response.json()["detail"] == "SERVICE_API_KEY is not configured"


def test_service_api_key_does_not_protect_public_routes():
    client = create_test_client()

    with patch.dict(os.environ, {}, clear=True):
        response = client.get("/public")

    assert response.status_code == 200
    assert response.json() == {"ok": True}
