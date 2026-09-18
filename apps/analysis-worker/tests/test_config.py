"""Test della configurazione runtime del worker.

Proteggono i valori environment che controllano polling, heartbeat e tempi
della pipeline senza introdurre hardcoding sparso nel codice applicativo.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_settings_default_min_processing_seconds_is_zero(monkeypatch) -> None:
    """La modalità normale non deve introdurre ritardi artificiali di default."""
    monkeypatch.delenv("WORKER_MIN_PROCESSING_SECONDS", raising=False)

    settings = Settings()

    assert settings.min_processing_seconds == 0


def test_settings_accepts_explicit_min_processing_seconds(monkeypatch) -> None:
    monkeypatch.setenv("WORKER_MIN_PROCESSING_SECONDS", "2")

    settings = Settings()

    assert settings.min_processing_seconds == 2.0


def test_settings_accepts_heartbeat_configuration(monkeypatch) -> None:
    monkeypatch.setenv("WORKER_HEARTBEAT_INTERVAL_SECONDS", "4")

    settings = Settings()

    assert settings.heartbeat_interval_seconds == 4


def test_settings_rejects_negative_min_processing_seconds(monkeypatch) -> None:
    monkeypatch.setenv("WORKER_MIN_PROCESSING_SECONDS", "-1")

    with pytest.raises(ValidationError):
        Settings()


def test_settings_reject_zero_heartbeat_interval(monkeypatch) -> None:
    monkeypatch.setenv("WORKER_HEARTBEAT_INTERVAL_SECONDS", "0")

    with pytest.raises(ValidationError):
        Settings()
