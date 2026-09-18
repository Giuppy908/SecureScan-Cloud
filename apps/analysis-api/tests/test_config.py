"""Test della configurazione derivata dall'environment.

Questi casi proteggono i valori che permettono al backend di trovare
database, Keycloak, limiti upload e altre dipendenze senza hardcoding sparso.
"""

from app.core.config import Settings


def test_settings_default_instance_id_is_analysis_api(monkeypatch) -> None:
    monkeypatch.delenv("INSTANCE_ID", raising=False)

    settings = Settings()

    assert settings.instance_id == "analysis-api"


def test_settings_accepts_explicit_instance_and_replica_configuration(monkeypatch) -> None:
    monkeypatch.setenv("INSTANCE_ID", "analysis-api-2")
    monkeypatch.setenv("API_HEARTBEAT_INTERVAL_SECONDS", "5")
    monkeypatch.setenv("API_HEARTBEAT_TIMEOUT_SECONDS", "15")
    monkeypatch.setenv("CONFIGURED_API_REPLICAS", "2")

    settings = Settings()

    assert settings.instance_id == "analysis-api-2"
    assert settings.api_heartbeat_interval_seconds == 5
    assert settings.api_heartbeat_timeout_seconds == 15
    assert settings.configured_api_replicas == 2


def test_settings_parse_cors_origins_from_csv_env(monkeypatch) -> None:
    monkeypatch.setenv(
        "CORS_ALLOWED_ORIGINS",
        "https://app.example.com, https://admin.example.com ,https://app.example.com",
    )

    settings = Settings()

    assert settings.cors_origins == [
        "https://app.example.com",
        "https://admin.example.com",
        "https://app.example.com",
    ]
