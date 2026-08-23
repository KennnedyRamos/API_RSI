from __future__ import annotations


def test_cors_libera_somente_origem_configurada(app):
    app.config["CORS_ALLOWED_ORIGINS"] = (
        "https://rsi-radar.onrender.com"
    )
    client = app.test_client()

    response = client.get(
        "/api/v1/health",
        headers={"Origin": "https://rsi-radar.onrender.com"},
    )

    assert response.status_code == 200
    assert response.headers["Access-Control-Allow-Origin"] == (
        "https://rsi-radar.onrender.com"
    )
    assert response.headers["Access-Control-Allow-Methods"] == "GET, OPTIONS"
    assert "Origin" in response.headers["Vary"]


def test_cors_nao_libera_origem_desconhecida(app):
    app.config["CORS_ALLOWED_ORIGINS"] = (
        "https://rsi-radar.onrender.com"
    )
    client = app.test_client()

    response = client.get(
        "/api/v1/health",
        headers={"Origin": "https://origem-invalida.example"},
    )

    assert response.status_code == 200
    assert "Access-Control-Allow-Origin" not in response.headers
