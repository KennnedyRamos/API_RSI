from __future__ import annotations


def test_home(client):
    response = client.get("/")

    assert response.status_code == 200
    assert response.get_json() == {
        "service": "API RSI",
        "status": "online",
        "success": True,
        "version": "v1",
    }


def test_api_health(client):
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.get_json()["status"] == "online"


def test_api_readiness(client):
    response = client.get("/api/v1/ready")

    assert response.status_code == 200
    assert response.get_json() == {
        "service": "API RSI",
        "status": "ready",
        "success": True,
        "database": "online",
    }


def test_legacy_health(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.get_json()["service"] == "API RSI"
