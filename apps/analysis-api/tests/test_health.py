"""Test dell'endpoint `/health` usato da Docker e Kong.

Questi casi proteggono la base dell'alta disponibilità: se `/health` cambia in
modo incompatibile, Docker e Kong potrebbero prendere decisioni errate sulle
repliche analysis-api.
"""

from app.api import health


def test_health_returns_service_status(client) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.headers["X-Backend-Instance"] == "test-analysis-api"
    assert response.json() == {
        "status": "healthy",
        "service": "analysis-api",
        "version": "0.1.0",
        "database": "reachable",
        "instance_id": "test-analysis-api",
    }


def test_health_returns_503_when_database_is_unreachable(client, monkeypatch) -> None:
    monkeypatch.setattr(health, "is_database_reachable", lambda: False)

    response = client.get("/health")

    assert response.status_code == 503
    assert response.headers["X-Backend-Instance"] == "test-analysis-api"
    assert response.json() == {
        "status": "unhealthy",
        "service": "analysis-api",
        "version": "0.1.0",
        "database": "unreachable",
        "instance_id": "test-analysis-api",
    }
