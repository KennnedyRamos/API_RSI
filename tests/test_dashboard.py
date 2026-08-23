from __future__ import annotations


def test_dashboard_page_is_served(client):
    response = client.get("/dashboard")

    assert response.status_code == 200
    assert b"RSI Radar" in response.data


def test_timeframes_include_30_minutes(client):
    response = client.get("/api/v1/meta/timeframes")

    assert response.status_code == 200
    assert "30m" in response.get_json()["results"]
