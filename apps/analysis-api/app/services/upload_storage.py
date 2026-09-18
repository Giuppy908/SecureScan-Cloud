"""Storage condiviso dei file caricati da Nuova analisi.

Quando l'utente invia un file, l'API lo salva temporaneamente in una directory
condivisa. Il worker leggerà poi quel percorso per eseguire la scansione e
aggiornare Cronologia e Dettaglio analisi.
"""

# Permette di gestire le annotazioni di tipo in modo posticipato
from __future__ import annotations

# `logging` permette di registrare eventuali errori che avvengono durante il cleanup dei file
import logging

# `Path` permette di costruire e manipolare i percorsi dei file sul filesystem
from pathlib import Path

# `uuid4` genera un identificatore casuale utilizzato per assegnare al file un nome univoco sullo storage
from uuid import uuid4

# `UploadFile` rappresenta il file ricevuto da FastAPI tramite una richiesta multipart/form-data
from fastapi import UploadFile

# Configurazione applicativa da cui vengono letti la directory degli upload e il limite massimo della loro dimensione
from app.core.config import settings

# Modello che raccoglie i dati necessari per creare successivamente il job dell'analisi nel database
from app.models.analysis import QueuedAnalysisCreate

# Logger associato a questo modulo, usato soprattutto quando fallisce la rimozione di un file parziale
logger = logging.getLogger(__name__)


# Eccezione utilizzata quando fallisce un'operazione sul filesystem relativa agli upload
class UploadStorageError(Exception):
    """Raised when upload storage operations fail."""


# Eccezione utilizzata quando il file supera la dimensione massima configurata
class UploadTooLargeError(ValueError):
    """Raised when an upload exceeds the configured size limit."""


# Service che salva temporaneamente sul filesystem i file destinati alla pipeline asincrona di analisi
class UploadStorageService:
    """Persistenza temporanea degli upload destinati alla pipeline asincrona."""

    # Il file viene letto e scritto progressivamente a blocchi da 1 MiB per evitare di caricarlo interamente in memoria lato API
    _chunk_size_bytes = 1024 * 1024

    # Riceve la directory configurata per gli upload e la converte in un oggetto Path
    def __init__(self, upload_dir: str) -> None:
        self._upload_dir = Path(upload_dir)

    # Salva il file caricato nello storage condiviso e restituisce i metadati necessari per creare il job PostgreSQL
    async def save_upload(self, uploaded_file: UploadFile) -> QueuedAnalysisCreate:
        """Valida dimensione e salva il file nello storage condiviso.

        Il file viene scritto a chunk per limitare la memoria usata lato API
        anche con upload grandi, lasciando il contenuto intatto per il worker.
        """

        # Conserva il nome originale ricevuto dal browser oppure usa un nome di fallback se il filename è assente
        file_name = uploaded_file.filename or "uploaded-file"

        # Ricava solamente l'estensione del filename originale e la converte in minuscolo
        suffix = Path(file_name).suffix.lower()

        # Genera il nome fisico del file usando un UUID casuale seguito dall'estensione originale
        storage_name = f"{uuid4().hex}{suffix}"

        # Costruisce il percorso completo in cui verrà salvato il file all'interno della directory degli upload
        storage_path = self._upload_dir / storage_name

        # Tiene traccia del numero totale di byte ricevuti per verificare il limite massimo configurato
        size_bytes = 0

        try:

            # Crea la directory degli upload e le eventuali directory superiori se non esistono già
            self._upload_dir.mkdir(parents=True, exist_ok=True)

            # Apre il nuovo file in modalità binaria di scrittura e lo chiude automaticamente al termine del blocco
            with storage_path.open("wb") as storage_file:

                # Continua a leggere il file caricato finché FastAPI non restituisce più dati
                while True:

                    # Legge il blocco successivo dell'upload, con dimensione massima di 1 MiB
                    chunk = await uploaded_file.read(self._chunk_size_bytes)

                    # Un blocco vuoto indica che è stata raggiunta la fine del file
                    if not chunk:
                        break

                    # Aggiorna la dimensione totale ricevuta
                    size_bytes += len(chunk)

                    # Interrompe il salvataggio se la dimensione supera il limite massimo configurato
                    if size_bytes > settings.max_upload_size_bytes:
                        raise UploadTooLargeError(
                            f"Uploaded file exceeds the maximum allowed size of {settings.max_upload_size_label}."
                        )

                    # Scrive immediatamente il blocco sul filesystem senza mantenere l'intero upload in memoria
                    storage_file.write(chunk)

            # Rifiuta gli upload che non contengono alcun byte
            if size_bytes == 0:
                raise ValueError("Uploaded file is empty.")

        except UploadTooLargeError:

            # Elimina il file parzialmente scritto quando viene superato il limite dimensionale
            self._delete_partial_file(storage_path)
            raise

        except ValueError:

            # Elimina il file creato anche quando l'upload risulta vuoto
            self._delete_partial_file(storage_path)
            raise

        except OSError as exc:

            # In caso di errore del filesystem tenta prima di eliminare l'eventuale file parziale
            self._delete_partial_file(storage_path)

            # Traduce l'errore del filesystem in un'eccezione specifica dello storage
            raise UploadStorageError("Failed to store uploaded file.") from exc

        finally:

            # Chiude sempre l'UploadFile ricevuto da FastAPI, indipendentemente dall'esito dell'operazione
            await uploaded_file.close()

        # Restituisce nome originale, dimensione e percorso fisico che verranno utilizzati per creare il job dell'analisi
        return QueuedAnalysisCreate(
            file_name=file_name,
            size_bytes=size_bytes,
            storage_path=str(storage_path),
        )

    # Helper di cleanup che tenta di eliminare un file rimasto parzialmente scritto dopo un errore
    def _delete_partial_file(self, storage_path: Path) -> None:
        """Delete a partially stored upload when present."""

        try:

            # Se il file esiste ancora sul filesystem prova a rimuoverlo
            if storage_path.exists():
                storage_path.unlink()

        except OSError:

            # Il cleanup è best-effort: se fallisce registra l'errore senza sostituire l'eccezione originale
            logger.exception(
                "Failed to remove partially stored upload.",
                extra={"storage_path": str(storage_path)},
            )

    # Elimina un file temporaneo dallo storage condiviso quando non è più necessario per la pipeline di analisi
    def delete_path(self, storage_path: str | None) -> None:
        """Delete one stored file when present."""

        # Se non è stato fornito alcun percorso non deve essere eseguita alcuna operazione
        if not storage_path:
            return

        # Converte il percorso ricevuto in un oggetto Path
        target = Path(storage_path)

        try:

            # Elimina il file soltanto se il percorso indicato esiste
            if target.exists():
                target.unlink()

        except OSError as exc:

            # Traduce un eventuale errore del filesystem in un'eccezione specifica dello storage
            raise UploadStorageError(f"Failed to delete stored file '{storage_path}'.") from exc

    # Elimina più file temporanei dallo storage richiamando delete_path() per ciascun percorso ricevuto
    def delete_paths(self, storage_paths: list[str]) -> None:
        """Delete multiple stored files."""

        # Scorre tutti i percorsi ricevuti e prova a eliminare ogni file singolarmente
        for storage_path in storage_paths:
            self.delete_path(storage_path)


# Dependency FastAPI che costruisce il service usando la directory degli upload definita nella configurazione
def get_upload_storage_service() -> UploadStorageService:
    """Dependency FastAPI per lo storage temporaneo degli upload."""

    # Crea una nuova istanza del service configurata con la directory condivisa utilizzata per gli upload
    return UploadStorageService(settings.upload_dir)
