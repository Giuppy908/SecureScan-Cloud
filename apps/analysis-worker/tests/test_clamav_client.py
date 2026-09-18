"""Test del client ClamAV usato dal worker.

Questi casi simulano le diverse risposte di `clamd` per verificare che la
pipeline distingua correttamente file puliti, rilevamenti, timeout, servizio
non disponibile e risposte malformate.
"""

import socket

import pytest

from app.services.clamav_client import ClamAvClient, ClamAvProtocolError


class FakeSocket:
    """Socket finto usato per simulare il protocollo TCP di `clamd`."""

    def __init__(self, response: bytes) -> None:
        self._response = response
        self.sent: list[bytes] = []

    def settimeout(self, _timeout: float) -> None:
        return None

    def sendall(self, data: bytes) -> None:
        self.sent.append(data)

    def recv(self, _size: int) -> bytes:
        response, self._response = self._response, b""
        return response

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


def test_clamav_client_returns_clean(monkeypatch) -> None:
    """Protegge il caso in cui ClamAV dichiara il file pulito."""
    fake_socket = FakeSocket(b"stream: OK\0")
    monkeypatch.setattr(socket, "create_connection", lambda *args, **kwargs: fake_socket)

    result = ClamAvClient(host="clamav", port=3310, timeout_seconds=1).scan_bytes(b"hello")

    assert result.status == "clean"


def test_clamav_client_returns_found(monkeypatch) -> None:
    """Protegge il mapping della firma rilevata verso il risultato applicativo."""
    fake_socket = FakeSocket(b"stream: Eicar-Signature FOUND\0")
    monkeypatch.setattr(socket, "create_connection", lambda *args, **kwargs: fake_socket)

    result = ClamAvClient(host="clamav", port=3310, timeout_seconds=1).scan_bytes(b"hello")

    assert result.status == "found"
    assert result.signature_name == "Eicar-Signature"


def test_clamav_client_returns_timeout(monkeypatch) -> None:
    """Verifica che un timeout non venga mai interpretato come file pulito."""
    def raise_timeout(*args, **kwargs):
        raise socket.timeout()

    monkeypatch.setattr(socket, "create_connection", raise_timeout)

    result = ClamAvClient(host="clamav", port=3310, timeout_seconds=1).scan_bytes(b"hello")

    assert result.status == "timeout"


def test_clamav_client_returns_unavailable(monkeypatch) -> None:
    """Verifica il comportamento quando il servizio ClamAV non è raggiungibile."""
    def raise_unavailable(*args, **kwargs):
        raise OSError("down")

    monkeypatch.setattr(socket, "create_connection", raise_unavailable)

    result = ClamAvClient(host="clamav", port=3310, timeout_seconds=1).scan_bytes(b"hello")

    assert result.status == "unavailable"


def test_clamav_client_raises_on_malformed_response(monkeypatch) -> None:
    """Blocca regressioni nel parsing del protocollo `clamd`."""
    fake_socket = FakeSocket(b"unexpected-response\0")
    monkeypatch.setattr(socket, "create_connection", lambda *args, **kwargs: fake_socket)

    with pytest.raises(ClamAvProtocolError):
        ClamAvClient(host="clamav", port=3310, timeout_seconds=1).scan_bytes(b"hello")
