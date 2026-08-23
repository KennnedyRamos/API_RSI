from __future__ import annotations

import pytest
from datetime import datetime

from app import db
from database.models.rsi import RSIData
from database.repositories.rsi_snapshot_repository import RSISnapshotRepository


def test_signals_returns_empty_list_without_data(client):
    response = client.get("/api/v1/signals")

    assert response.status_code == 200
    assert response.get_json()["results"] == []


@pytest.mark.parametrize("query", ["limite=abc", "limit=abc"])
def test_signals_rejects_invalid_limit(client, query):
    response = client.get(f"/api/v1/signals?{query}")

    assert response.status_code == 400
    assert "limite" in response.get_json()["error"]


@pytest.mark.parametrize("query", ["intervalo=invalido", "timeframe=invalido"])
def test_rsi_rejects_invalid_timeframe(client, query):
    response = client.get(f"/api/v1/rsi?{query}")

    assert response.status_code == 400
    assert "Timeframe inválido" in response.get_json()["error"]


def test_current_signals_returns_latest_snapshot(client, app):
    with app.app_context():
        registro = RSIData(
            symbol="BTC/USDT",
            intervalo="1h",
            rsi=72.41,
            rsi_previous=69.84,
            rsi_difference=2.57,
            timestamp=datetime(2026, 8, 21, 20),
            rsi_status="OVERBOUGHT",
            signal_type="OVERBOUGHT",
            signal_level="MODERATE",
            current_price=104250.0,
            change_24h=3.82,
            volume_24h=42_310_000_000.0,
            market_cap=2_000_000_000_000.0,
            ranking=1,
        )
        db.session.add(registro)
        db.session.commit()
        RSISnapshotRepository.atualizar(
            symbol=registro.symbol,
            intervalo=registro.intervalo,
            rsi_data_id=registro.id,
        )

    response = client.get("/api/v1/signals/current?intervalo=1h")

    assert response.status_code == 200
    data = response.get_json()
    assert data["total"] == 1
    assert data["results"][0]["symbol"] == "BTC/USDT"
    assert data["results"][0]["signal_level"] == "MODERATE"
    assert data["results"][0]["signal_level_label"] == "Moderado"


def test_history_is_chronological(client, app):
    with app.app_context():
        for hour, rsi in ((18, 61.0), (19, 67.0), (20, 72.0)):
            db.session.add(
                RSIData(
                    symbol="ETH/USDT",
                    intervalo="1h",
                    rsi=rsi,
                    timestamp=datetime(2026, 8, 21, hour),
                    rsi_status="NORMAL",
                    signal_level="NORMAL",
                    current_price=4000.0,
                )
            )
        db.session.commit()

    response = client.get("/api/v1/history/ETHUSDT?timeframe=1h&limit=10")

    assert response.status_code == 200
    results = response.get_json()["results"]
    assert [item["rsi"] for item in results] == [61.0, 67.0, 72.0]
