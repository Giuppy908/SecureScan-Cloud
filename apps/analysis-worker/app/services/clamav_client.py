"""Client ClamAV usato dal worker per la scansione antivirus reale.

ClamAV è il motore antivirus che controlla il file cercando firme note di
minacce. Questo modulo parla con `clamd`, il demone già avviato nello stack,
senza esporre ClamAV al browser o al frontend.

Se ClamAV non è raggiungibile o non completa la scansione, il file non viene
considerato pulito: la pipeline potrà produrre `scan_error`.
"""

# Permette di gestire le annotazioni di tipo in modo posticipato
from __future__ import annotations

# `socket` viene usato per aprire la connessione TCP verso il demone ClamAV
import socket

# `struct` permette di convertire la lunghezza di ogni chunk in 4 byte nel formato richiesto dal protocollo INSTREAM
import struct

# `dataclass` permette di definire una struttura compatta e immutabile per il risultato della scansione
from dataclasses import dataclass

# Configurazione da cui vengono letti host, porta e timeout del servizio ClamAV
from app.core.config import settings

# Dimensione di ogni blocco inviato a ClamAV tramite INSTREAM: 64 KiB
_CHUNK_SIZE = 64 * 1024


# Raccoglie in una struttura uniforme l'esito restituito dal client ClamAV
@dataclass(frozen=True, slots=True)
class ClamAvScanResult:
    """Esito normalizzato della scansione ClamAV usato dal resto della pipeline."""

    # Stato normalizzato della scansione, ad esempio clean, found, timeout, unavailable o error
    status: str

    # Nome della firma malware rilevata, valorizzato normalmente solo quando lo stato è found
    signature_name: str | None = None

    # Messaggio tecnico associato a un errore o a un problema di raggiungibilità
    error_message: str | None = None

    # Versione del motore ClamAV, utilizzata dal metodo get_version()
    engine_version: str | None = None


# Eccezione specifica usata quando la risposta di clamd non può essere interpretata correttamente
class ClamAvProtocolError(RuntimeError):
    """Errore quando `clamd` risponde con un payload non interpretabile."""


# Client che comunica con il demone ClamAV tramite TCP e protocollo INSTREAM
class ClamAvClient:
    """Invia un file a `clamd` via TCP usando il protocollo INSTREAM.

    INSTREAM permette di mandare i byte del file direttamente al demone,
    senza esporre pubblicamente il motore antivirus e senza eseguire il file.
    """

    # Inizializza il client usando i parametri forniti oppure quelli configurati nel worker
    def __init__(
        self,
        *,
        host: str | None = None,
        port: int | None = None,
        timeout_seconds: float | None = None,
    ) -> None:

        # Host del servizio ClamAV, normalmente risolto tramite il nome del servizio Docker
        self._host = host or settings.clamd_host

        # Porta TCP su cui il demone clamd ascolta le richieste
        self._port = port or settings.clamd_port

        # Timeout massimo utilizzato per connessione e comunicazione con ClamAV
        self._timeout_seconds = timeout_seconds or settings.clamd_timeout_seconds

    # Invia a ClamAV i byte del file e traduce la risposta in un risultato normalizzato
    def scan_bytes(self, content: bytes) -> ClamAvScanResult:
        """Scansiona il contenuto del file e traduce la risposta di ClamAV."""

        # Tenta di stabilire la connessione TCP e completare la scansione
        try:

            # Apre una connessione verso clamd usando host, porta e timeout configurati
            with socket.create_connection(
                (self._host, self._port),
                timeout=self._timeout_seconds,
            ) as sock:

                # Applica il timeout anche alle successive operazioni di lettura e scrittura sul socket
                sock.settimeout(self._timeout_seconds)

                # Invia il comando INSTREAM terminato da byte NUL per indicare che seguiranno i byte del file
                sock.sendall(b"zINSTREAM\0")

                # Divide il contenuto in chunk da 64 KiB e li invia uno alla volta
                for offset in range(0, len(content), _CHUNK_SIZE):

                    # Estrae il blocco corrente dal contenuto completo del file
                    chunk = content[offset : offset + _CHUNK_SIZE]

                    # Invia prima la lunghezza del chunk come intero unsigned di 4 byte in ordine big-endian
                    sock.sendall(struct.pack("!I", len(chunk)))

                    # Invia subito dopo i byte effettivi del chunk
                    sock.sendall(chunk)

                # Una lunghezza pari a zero segnala a clamd la fine dello stream
                sock.sendall(struct.pack("!I", 0))

                # Legge la risposta testuale completa restituita da ClamAV
                response = self._read_response(sock)

        # Un timeout viene trasformato in un risultato esplicito invece di essere interpretato come file pulito
        except socket.timeout:
            return ClamAvScanResult(status="timeout", error_message="ClamAV ha superato il timeout di scansione.")

        # Un errore di rete o di connessione viene rappresentato come indisponibilità del servizio ClamAV
        except OSError as exc:
            return ClamAvScanResult(
                status="unavailable",
                error_message=f"ClamAV non è raggiungibile: {exc}",
            )

        # Rimuove terminatori NUL e spazi superflui dalla risposta prima di interpretarla
        normalized_response = response.rstrip("\0").strip()

        # Una risposta terminante con OK indica che ClamAV non ha rilevato firme note
        if normalized_response.endswith("OK"):
            return ClamAvScanResult(status="clean")

        # Una risposta contenente FOUND indica che ClamAV ha rilevato una firma malware
        if "FOUND" in normalized_response:

            # Estrae dalla risposta il nome della firma individuata
            signature_name = normalized_response.rsplit("FOUND", 1)[0].split(":", 1)[-1].strip() or None

            # Restituisce l'esito found insieme al nome della firma quando disponibile
            return ClamAvScanResult(status="found", signature_name=signature_name)

        # Segnala esplicitamente il superamento del limite massimo accettato dal protocollo INSTREAM
        if normalized_response.startswith("INSTREAM size limit exceeded"):
            return ClamAvScanResult(status="error", error_message=normalized_response)

        # Qualsiasi risposta contenente ERROR viene normalizzata come errore di scansione
        if "ERROR" in normalized_response:
            return ClamAvScanResult(status="error", error_message=normalized_response)

        # Una risposta non riconosciuta non viene mai interpretata come clean ma genera un errore di protocollo
        raise ClamAvProtocolError(f"Risposta ClamAV non valida: {normalized_response}")

    # Interroga ClamAV per conoscere la versione del motore senza eseguire una scansione file
    def get_version(self) -> ClamAvScanResult:
        """Recupera la versione del motore ClamAV per Stato del sistema."""

        # Tenta di connettersi a clamd e inviare il comando VERSION
        try:

            # Apre una connessione TCP verso ClamAV
            with socket.create_connection(
                (self._host, self._port),
                timeout=self._timeout_seconds,
            ) as sock:

                # Applica il timeout anche alle operazioni successive sul socket
                sock.settimeout(self._timeout_seconds)

                # Invia il comando VERSION terminato da byte NUL
                sock.sendall(b"zVERSION\0")

                # Legge e normalizza la risposta restituita dal demone
                response = self._read_response(sock).rstrip("\0").strip()

        # Se ClamAV non risponde entro il timeout restituisce uno stato timeout
        except socket.timeout:
            return ClamAvScanResult(status="timeout", error_message="ClamAV non ha risposto al comando VERSION.")

        # Un problema di connessione viene trasformato in stato unavailable
        except OSError as exc:
            return ClamAvScanResult(status="unavailable", error_message=f"ClamAV non è raggiungibile: {exc}")

        # Una risposta VERSION vuota viene considerata un errore di protocollo
        if not response:
            raise ClamAvProtocolError("VERSION di ClamAV vuota.")

        # Restituisce la versione del motore all'interno dello stesso tipo di risultato usato dal client
        return ClamAvScanResult(status="clean", engine_version=response)

    # Legge dal socket la risposta completa restituita da clamd
    @staticmethod
    def _read_response(sock: socket.socket) -> str:
        """Legge la risposta testuale completa restituita da `clamd`."""

        # Accumula i blocchi di byte ricevuti dal socket
        chunks: list[bytes] = []

        # Continua a leggere fino alla fine della risposta
        while True:

            # Riceve fino a 4096 byte per volta
            chunk = sock.recv(4096)

            # L'assenza di ulteriori byte indica che la connessione non fornisce altro contenuto
            if not chunk:
                break

            # Conserva il blocco appena ricevuto
            chunks.append(chunk)

            # Una risposta terminata da NUL o newline viene considerata completa
            if b"\0" in chunk or chunk.endswith(b"\n"):
                break

        # L'assenza totale di risposta viene considerata un errore di protocollo
        if not chunks:
            raise ClamAvProtocolError("ClamAV non ha restituito alcuna risposta.")

        # Unisce tutti i blocchi ricevuti e li converte in testo UTF-8 sostituendo eventuali byte non validi
        return b"".join(chunks).decode("utf-8", errors="replace")


# Istanza standard del client ClamAV riutilizzata dalla MalwareScanPipeline
clamav_client = ClamAvClient()
