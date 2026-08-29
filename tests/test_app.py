from __future__ import annotations


def test_legacy_rsi_route_uses_initialized_application(client):
    response = client.get("/rsi/5m")

    assert response.status_code == 200
    data = response.get_json()
    assert data["success"] is True
    assert data["intervalo"] == "5m"
    assert data["results"] == []


def test_legacy_rsi_route_rejects_invalid_timeframe(client):
    response = client.get("/rsi/invalido")

    assert response.status_code == 400
