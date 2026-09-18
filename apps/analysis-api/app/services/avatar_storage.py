"""Storage locale degli avatar applicativi.

Questo servizio supporta Profilo, Modifica profilo e alcune viste
amministrative. Gli avatar non vengono salvati in Keycloak: l'applicazione li
mantiene in uno storage locale separato e collega il file al subject utente.
"""

# Permette di gestire le annotazioni di tipo in modo posticipato
from __future__ import annotations

# `base64` permette di convertire i byte dell'immagine in testo Base64 per costruire le data URL usate dal pannello amministrativo
import base64

# `imghdr` riconosce il formato reale dell'immagine analizzandone i byte invece di fidarsi del nome del file
import imghdr

# `logging` permette di registrare eventuali errori durante la lettura o la cancellazione dei file
import logging

# `Path` permette di costruire e manipolare in modo strutturato i percorsi dei file sul filesystem
from pathlib import Path

# `uuid4` genera identificatori casuali utilizzati per assegnare un nome univoco agli avatar salvati
from uuid import uuid4

# `UploadFile` rappresenta il file ricevuto da FastAPI tramite una richiesta multipart/form-data
from fastapi import UploadFile

# Configurazione applicativa da cui vengono letti la directory degli avatar e il limite massimo della loro dimensione
from app.core.config import settings

# Logger associato a questo modulo, utilizzato soprattutto per registrare errori di lettura o cleanup dei file
logger = logging.getLogger(__name__)

# Associa ciascun formato immagine riconosciuto al relativo MIME type e all'estensione con cui il file verrà salvato
_ALLOWED_IMAGE_TYPES = {
    "png": ("image/png", ".png"),
    "jpeg": ("image/jpeg", ".jpg"),
    "gif": ("image/gif", ".gif"),
}

# Gli avatar sono salvati sul filesystem nella directory configurata, che in Docker è montata su un volume persistente condiviso dalle repliche API

# Eccezione utilizzata quando fallisce un'operazione sul filesystem, come il salvataggio o la cancellazione di un avatar
class AvatarStorageError(Exception):
    """Raised when avatar storage fails."""


# Eccezione utilizzata quando il file caricato dall'utente non rispetta i requisiti previsti per gli avatar
class AvatarValidationError(ValueError):
    """Raised when an uploaded avatar is invalid."""


# Rappresenta i dati minimi dell'avatar dopo che il file è stato salvato correttamente nello storage
class StoredAvatar:
    """Metadati minimi dell'avatar appena persistito."""

    # Memorizza il percorso del file salvato e il relativo MIME type senza conservare direttamente i byte dell'immagine
    def __init__(self, path: str, media_type: str) -> None:
        self.path = path
        self.media_type = media_type


# Service che gestisce le operazioni sul filesystem necessarie per salvare, recuperare e cancellare le foto profilo
class AvatarStorageService:
    """Valida e salva avatar utenti nello storage condiviso dell'app."""

    # Ogni file caricato viene letto a blocchi da 256 KiB per controllarne progressivamente la dimensione
    _chunk_size_bytes = 256 * 1024

    # Riceve la directory configurata per gli avatar e la converte in un oggetto Path
    def __init__(self, avatar_dir: str) -> None:
        self._avatar_dir = Path(avatar_dir)

    # Legge il file caricato, ne controlla dimensione e formato, quindi lo salva con un nome casuale generato dal server
    async def save_avatar(self, uploaded_file: UploadFile, previous_path: str | None = None) -> StoredAvatar:
        """Legge interamente l'avatar, lo valida e lo salva con nome casuale.

        L'avatar viene caricato in memoria perché il limite è volutamente
        ristretto (5 MB), così la validazione del formato resta semplice.
        """

        # Tiene traccia del numero totale di byte letti per poter applicare il limite massimo configurato
        size_bytes = 0

        # Accumula in memoria i byte ricevuti perché il file verrà successivamente validato e scritto sul filesystem
        payload = bytearray()

        try:

            # Continua a leggere il file a blocchi finché UploadFile non restituisce più dati
            while True:

                # Legge il blocco successivo del file caricato
                chunk = await uploaded_file.read(self._chunk_size_bytes)

                # Un blocco vuoto indica che è stata raggiunta la fine del file
                if not chunk:
                    break

                # Aggiorna la dimensione complessiva del file ricevuto
                size_bytes += len(chunk)

                # Interrompe l'upload se la dimensione supera il limite configurato
                if size_bytes > settings.max_avatar_size_bytes:
                    raise AvatarValidationError(
                        f"L'avatar supera la dimensione massima consentita di {settings.max_avatar_size_mb} MB."
                    )

                # Aggiunge il blocco appena letto ai byte dell'immagine mantenuti in memoria
                payload.extend(chunk)

        finally:

            # Chiude sempre il file ricevuto da FastAPI, anche se durante la lettura viene sollevata un'eccezione
            await uploaded_file.close()

        # Rifiuta un upload che non contiene alcun byte
        if size_bytes == 0:
            raise AvatarValidationError("Il file avatar è vuoto.")

        # Analizza direttamente i byte per determinare il formato reale dell'immagine
        image_type = imghdr.what(None, h=bytes(payload))

        # Accetta soltanto i formati presenti nella whitelist PNG, JPEG e GIF
        if image_type not in _ALLOWED_IMAGE_TYPES:
            raise AvatarValidationError("Il file avatar deve essere PNG, JPEG o GIF.")

        # Recupera dalla whitelist il MIME type e l'estensione associati al formato realmente riconosciuto
        media_type, suffix = _ALLOWED_IMAGE_TYPES[image_type]

        # Genera un nome casuale tramite UUID e costruisce il percorso completo in cui salvare il nuovo avatar
        storage_path = self._avatar_dir / f"{uuid4().hex}{suffix}"

        try:

            # Crea la directory degli avatar e le eventuali directory superiori se non esistono ancora
            self._avatar_dir.mkdir(parents=True, exist_ok=True)

            # Scrive sul filesystem tutti i byte dell'immagine raccolti in memoria
            storage_path.write_bytes(payload)

        except OSError as exc:

            # In caso di errore tenta di eliminare un eventuale file rimasto parzialmente scritto
            self._delete_partial_file(storage_path)

            # Traduce l'errore del filesystem in un'eccezione specifica del service
            raise AvatarStorageError("Failed to store avatar.") from exc

        # Se il chiamante ha indicato un avatar precedente, lo elimina soltanto dopo aver salvato correttamente quello nuovo
        if previous_path:
            self.delete_avatar(previous_path)

        # Restituisce il percorso e il MIME type del file appena salvato senza restituirne nuovamente i byte
        return StoredAvatar(path=str(storage_path), media_type=media_type)

    # Verifica che percorso e MIME type dell'avatar siano disponibili e che il percorso indicato esista sul filesystem
    def resolve_avatar(self, avatar_path: str | None, media_type: str | None) -> tuple[Path, str] | None:
        """Return the stored avatar path and media type when available."""

        # Senza percorso o MIME type non è possibile risolvere un avatar valido
        if not avatar_path or not media_type:
            return None

        # Converte il percorso memorizzato in un oggetto Path
        target = Path(avatar_path)

        # Se il percorso non esiste più sul filesystem considera l'avatar non disponibile
        if not target.exists():
            return None

        # Restituisce il percorso esistente insieme al MIME type memorizzato
        return target, media_type

    # Converte un avatar salvato in una data URL contenente direttamente l'immagine codificata in Base64
    def build_data_url(self, avatar_path: str | None, media_type: str | None) -> str | None:
        """Costruisce una data URL usata dalle viste admin senza endpoint dedicato."""

        # Verifica prima che il riferimento all'avatar sia utilizzabile
        avatar = self.resolve_avatar(avatar_path, media_type)

        # Se percorso, MIME type o file non sono disponibili non viene costruita alcuna data URL
        if avatar is None:
            return None

        # Estrae il percorso del file e il MIME type restituiti da resolve_avatar()
        target, resolved_media_type = avatar

        try:

            # Legge interamente in memoria i byte dell'immagine salvata
            payload = target.read_bytes()

        except OSError:

            # Registra l'errore di lettura e restituisce None invece di propagare l'eccezione al chiamante
            logger.exception("Failed to read stored avatar.", extra={"avatar_path": avatar_path})
            return None

        # Codifica i byte dell'immagine in Base64 e converte il risultato binario in una stringa ASCII
        encoded = base64.b64encode(payload).decode("ascii")

        # Costruisce la data URL completa che il frontend può utilizzare direttamente come sorgente dell'immagine
        return f"data:{resolved_media_type};base64,{encoded}"

    # Elimina dal filesystem l'avatar indicato dal percorso se il file esiste
    def delete_avatar(self, avatar_path: str | None) -> None:
        """Delete a stored avatar if it exists."""

        # Se non è stato fornito alcun percorso non è necessario effettuare operazioni
        if not avatar_path:
            return

        # Converte il percorso ricevuto in un oggetto Path
        target = Path(avatar_path)

        try:

            # Tenta la cancellazione soltanto se il percorso esiste
            if target.exists():
                target.unlink()

        except OSError as exc:

            # Traduce eventuali errori del filesystem in un'eccezione specifica dello storage avatar
            raise AvatarStorageError(f"Failed to delete stored avatar '{avatar_path}'.") from exc

    # Helper utilizzato dopo un errore di scrittura per tentare di rimuovere un eventuale file incompleto
    @staticmethod
    def _delete_partial_file(storage_path: Path) -> None:

        try:

            # Se il file parzialmente scritto esiste ancora tenta di cancellarlo
            if storage_path.exists():
                storage_path.unlink()

        except OSError:

            # Il cleanup è best-effort: se fallisce viene registrato l'errore senza sollevare una nuova eccezione
            logger.exception("Failed to remove partially stored avatar.", extra={"avatar_path": str(storage_path)})


# Dependency FastAPI che costruisce il servizio usando la directory avatar definita nella configurazione applicativa
def get_avatar_storage_service() -> AvatarStorageService:
    """Dependency FastAPI per lo storage avatar."""

    # Crea una nuova istanza del service configurata con la directory in cui vengono conservate le foto profilo
    return AvatarStorageService(settings.avatar_dir)
