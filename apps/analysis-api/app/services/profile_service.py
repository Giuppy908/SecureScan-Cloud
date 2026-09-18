"""Servizi che alimentano Profilo, Modifica profilo e Amministrazione utenti.

Questo modulo mette insieme tre mondi diversi:
- Keycloak, che conserva identità, ruoli, email e password;
- PostgreSQL, che conserva dati applicativi locali come avatar e alcuni snapshot;
- le pagine del sito che devono mostrare queste informazioni in modo coerente.

Il risultato è una logica unica che permette al frontend di lavorare con un
solo backend, senza dover conoscere i dettagli di Keycloak Admin API.
"""

# Permette la gestione posticipata delle annotazioni di tipo
from __future__ import annotations

# `dataclass` permette di definire in modo compatto una classe che conserva dipendenze come Session, client Keycloak e storage avatar
from dataclasses import dataclass

# `HTTPStatus` fornisce costanti leggibili per i codici di stato HTTP come 400, 404, 409, 500 e 502
from http import HTTPStatus

# `Path` rappresenta in modo strutturato i percorsi dei file avatar presenti nello storage
from pathlib import Path

# `Depends` permette a FastAPI di risolvere automaticamente le dipendenze necessarie alla costruzione del service
from fastapi import Depends

# `func` espone funzioni SQL come COUNT, mentre `select` permette di costruire query SQLAlchemy
from sqlalchemy import func, select

# Eccezione SQLAlchemy intercettata quando falliscono operazioni sul database applicativo
from sqlalchemy.exc import SQLAlchemyError

# `Session` rappresenta la sessione SQLAlchemy utilizzata dal service per leggere e modificare PostgreSQL
from sqlalchemy.orm import Session

# Modello dell'utente autenticato ottenuto dal layer di sicurezza dopo la validazione del token
from app.auth.security import AuthenticatedUser

# Modelli ORM utilizzati rispettivamente per le analisi e per il profilo locale dell'utente
from app.db.models import AnalysisRecordModel, UserProfileModel

# Dependency che fornisce una Session SQLAlchemy gestita per la richiesta FastAPI corrente
from app.db.session import get_db_session

# Modelli ed enum del dominio analisi utilizzati per statistiche, cronologia e distribuzione del rischio
from app.models.analysis import Analysis, AnalysisStatus, RiskLevel

# Modello utilizzato per rappresentare una voce della distribuzione del rischio
from app.models.dashboard import DashboardRiskDistributionEntry

# Modelli Pydantic di input e output utilizzati dagli endpoint Profilo e Amministrazione
from app.models.profile import (
    AdminUserAnalysesSnapshot,
    AdminUserProfileUpdateRequest,
    AdminUserSummary,
    AdminUserUpdateRequest,
    ProfileStatistics,
    UpdateOwnPasswordRequest,
    UpdateOwnProfileRequest,
    VerificationEmailResponse,
    UserProfileSnapshot,
)

# Repository SQLAlchemy riutilizzato soltanto per recuperare la cronologia completa delle analisi di un utente nella vista amministrativa
from app.repositories.sqlalchemy_repository import SqlAlchemyAnalysisRepository

# Service e modello relativi allo storage degli avatar, insieme alla dependency FastAPI che fornisce il service
from app.services.avatar_storage import AvatarStorageService, StoredAvatar, get_avatar_storage_service

# Client amministrativo Keycloak, relativa eccezione applicativa e modello che rappresenta un utente letto da Keycloak
from app.services.keycloak_admin import KeycloakAdminClient, KeycloakAdminError, KeycloakUser

# Configurazione applicativa utilizzata soprattutto per verifica email e disponibilità SMTP
from app.core.config import settings


# Eccezione applicativa del service che associa a un messaggio leggibile anche il codice HTTP che l'endpoint dovrà restituire
class ProfileServiceError(Exception):
    """Errore applicativo mostrabile dalla UI di Profilo o Amministrazione."""

    # Inizializza l'eccezione usando BAD_REQUEST come codice HTTP predefinito se il chiamante non ne specifica uno diverso
    def __init__(self, message: str, status_code: int = HTTPStatus.BAD_REQUEST) -> None:

        # Inizializza la classe Exception con il messaggio applicativo
        super().__init__(message)

        # Conserva il codice HTTP come intero per permettere all'endpoint di costruire la risposta corretta
        self.status_code = int(status_code)


# `dataclass(slots=True)` genera automaticamente l'inizializzazione delle tre dipendenze e limita gli attributi a quelli dichiarati
@dataclass(slots=True)
class UserProfileService:
    """Coordina i dati mostrati nelle pagine Profilo e Amministrazione."""

    # Session SQLAlchemy utilizzata per dati locali e statistiche applicative
    session: Session

    # Client utilizzato per leggere e modificare utenti, ruoli, email e password in Keycloak
    keycloak_admin: KeycloakAdminClient

    # Service che gestisce i file avatar nello storage applicativo
    avatar_storage: AvatarStorageService

    # Costruisce lo snapshot mostrato all'utente autenticato nella propria pagina Profilo
    def get_profile_snapshot(self, user: AuthenticatedUser) -> UserProfileSnapshot:
        """Carica i dati mostrati quando l'utente apre la pagina Profilo."""

        try:

            # Recupera da Keycloak i dati identificativi dell'utente usando il subject presente nel token autenticato
            keycloak_user = self.keycloak_admin.get_user(user.subject)

            # Recupera il profilo applicativo locale o lo crea in Session se non esiste ancora
            profile_record = self._get_or_create_profile_record(user.subject)

            # Combina identità Keycloak, avatar locale e statistiche sulle analisi in un unico snapshot
            return self._build_profile_snapshot(keycloak_user, profile_record)

        # Gli errori provenienti dal client Keycloak vengono tradotti in indisponibilità temporanea del servizio esterno
        except KeycloakAdminError as exc:

            # Annulla eventuali modifiche SQLAlchemy ancora pendenti nella Session
            self.session.rollback()

            raise ProfileServiceError(
                "Le informazioni del profilo non sono temporaneamente disponibili.",
                HTTPStatus.BAD_GATEWAY,
            ) from exc

        # Gli errori SQLAlchemy vengono trasformati in un errore interno del backend
        except SQLAlchemyError as exc:

            # Ripristina la Session dopo il fallimento dell'operazione database
            self.session.rollback()

            raise ProfileServiceError(
                "Le informazioni del profilo non sono temporaneamente disponibili.",
                HTTPStatus.INTERNAL_SERVER_ERROR,
            ) from exc

    # Aggiorna i dati identificativi dell'utente e gestisce separatamente il caso in cui venga richiesto anche un cambio email
    def update_profile(self, user: AuthenticatedUser, payload: UpdateOwnProfileRequest) -> UserProfileSnapshot:
        """Aggiorna i dati della pagina Modifica profilo."""

        try:

            # Legge prima lo stato corrente dell'utente da Keycloak per confrontare soprattutto l'indirizzo email
            current_user = self.keycloak_admin.get_user(user.subject)

            # Normalizza l'email attuale rimuovendo spazi e ignorando differenze tra maiuscole e minuscole
            normalized_current_email = (current_user.email or "").strip().lower()

            # Determina se la richiesta contiene effettivamente un nuovo indirizzo email
            email_changed = normalized_current_email != payload.email

            # Il cambio email segue un flusso distinto perché richiede verifica e configurazione SMTP
            if email_changed:

                # Blocca il cambio email se la funzionalità di verifica email è disabilitata
                if not settings.email_verification_enabled:
                    raise ProfileServiceError(
                        "Il cambio email non è disponibile perché la verifica email non è attiva.",
                        HTTPStatus.SERVICE_UNAVAILABLE,
                    )

                # Blocca il cambio email se non è disponibile un server SMTP configurato
                if not settings.smtp_configured:
                    raise ProfileServiceError(
                        "Il cambio email richiede un server SMTP configurato correttamente.",
                        HTTPStatus.SERVICE_UNAVAILABLE,
                    )

                # Richiede che l'indirizzo email corrente sia già stato verificato prima di iniziare il cambio
                if not current_user.email_verified:
                    raise ProfileServiceError(
                        "Completa prima la verifica dell'indirizzo email attuale.",
                        HTTPStatus.CONFLICT,
                    )

                # Blocca il flusso se Keycloak non contiene attualmente alcun indirizzo email
                if not current_user.email:
                    raise ProfileServiceError(
                        "Nessun indirizzo email attualmente associato all'account.",
                        HTTPStatus.CONFLICT,
                    )

                # Verifica tramite Keycloak che la nuova email possa essere utilizzata per il cambio pendente
                self.keycloak_admin.validate_pending_email_change(
                    subject=user.subject,
                    new_email=payload.email,
                )

                # Aggiorna username, nome e cognome senza richiedere ancora il nuovo oggetto utente
                self.keycloak_admin.update_user_identity_fields(
                    subject=user.subject,
                    username=payload.username,
                    first_name=payload.first_name,
                    last_name=payload.last_name,
                    fetch_updated_user=False,
                )

                # Avvia in Keycloak il flusso di cambio email che mantiene il nuovo indirizzo in attesa di verifica
                self.keycloak_admin.initiate_pending_email_change(
                    subject=user.subject,
                    new_email=payload.email,
                )

                # Rilegge l'utente da Keycloak per ottenere lo stato aggiornato dopo l'avvio del cambio email
                keycloak_user = self.keycloak_admin.get_user(user.subject)

            else:

                # Se l'email non cambia aggiorna direttamente i normali campi identificativi e riceve il nuovo stato dell'utente
                keycloak_user = self.keycloak_admin.update_user_identity_fields(
                    subject=user.subject,
                    username=payload.username,
                    first_name=payload.first_name,
                    last_name=payload.last_name,
                )

            # Garantisce che esista anche il record applicativo locale collegato al subject
            profile_record = self._get_or_create_profile_record(user.subject)

            # Conferma definitivamente le eventuali modifiche locali ancora pendenti nella Session
            self.session.commit()

            # Restituisce al frontend il profilo aggiornato combinando Keycloak, database locale e statistiche
            return self._build_profile_snapshot(keycloak_user, profile_record)

        # Traduce gli errori del client Keycloak in ProfileServiceError con codice HTTP dedotto dal messaggio
        except KeycloakAdminError as exc:

            self.session.rollback()

            raise ProfileServiceError(
                str(exc),
                _infer_profile_http_status(str(exc), default_status=HTTPStatus.BAD_REQUEST),
            ) from exc

        # Un errore SQLAlchemy provoca rollback della parte locale ma non può annullare eventuali modifiche già applicate in Keycloak
        except SQLAlchemyError as exc:

            self.session.rollback()

            raise ProfileServiceError("Aggiornamento profilo non riuscito.", HTTPStatus.INTERNAL_SERVER_ERROR) from exc

    # Modifica la password dell'utente esclusivamente attraverso Keycloak senza salvarla nel database applicativo
    def change_password(self, user: AuthenticatedUser, payload: UpdateOwnPasswordRequest) -> None:
        """Aggiorna la password passando solo da Keycloak.

        Il database applicativo non salva password utenti: questa scelta riduce
        la superficie sensibile del backend e mantiene l'autenticazione in un
        solo punto.
        """

        # Impedisce di impostare nuovamente la stessa password ricevuta come password corrente
        if payload.current_password == payload.new_password:
            raise ProfileServiceError("La nuova password deve essere diversa da quella attuale.")

        # Verifica che nuova password e conferma coincidano
        if payload.new_password != payload.confirm_new_password:
            raise ProfileServiceError("La conferma della nuova password non corrisponde.")

        try:

            # Recupera da Keycloak l'utente per conoscere anche lo username corrente
            current_keycloak_user = self.keycloak_admin.get_user(user.subject)

            # Impedisce di utilizzare come password lo stesso valore dello username ignorando maiuscole e minuscole
            if current_keycloak_user.username.lower() == payload.new_password.lower():
                raise ProfileServiceError("La nuova password non può coincidere con lo username.")

            # Chiede a Keycloak di validare la password corrente e impostare quella nuova
            self.keycloak_admin.update_user_password(
                subject=user.subject,
                username=current_keycloak_user.username,
                current_password=payload.current_password,
                new_password=payload.new_password,
            )

            # Se richiesto dall'utente tenta di invalidare tutte le altre sessioni lasciando attiva quella corrente
            if payload.logout_other_sessions:

                # Recupera dal token l'identificatore della sessione Keycloak corrente
                current_session_id = getattr(user, "session_id", None)

                # Senza session_id non è possibile distinguere la sessione corrente dalle altre
                if not current_session_id:
                    raise ProfileServiceError(
                        "La sessione corrente non espone un identificatore valido per disconnettere gli altri dispositivi.",
                        HTTPStatus.SERVICE_UNAVAILABLE,
                    )

                try:

                    # Chiede a Keycloak di terminare tutte le altre sessioni dell'utente
                    self.keycloak_admin.logout_other_user_sessions(
                        subject=user.subject,
                        current_session_id=current_session_id,
                    )

                # La password può essere già stata aggiornata anche se la revoca delle altre sessioni fallisce
                except KeycloakAdminError as exc:
                    raise ProfileServiceError(
                        "Password aggiornata, ma non è stato possibile disconnettere le altre sessioni attive.",
                        HTTPStatus.BAD_GATEWAY,
                    ) from exc

        # Traduce gli errori Keycloak in un errore applicativo comprensibile dagli endpoint
        except KeycloakAdminError as exc:
            raise ProfileServiceError(
                str(exc),
                _infer_profile_http_status(str(exc), default_status=HTTPStatus.BAD_REQUEST),
            ) from exc

    # Collega un nuovo file avatar già salvato nello storage al profilo locale dell'utente
    def replace_avatar(self, user: AuthenticatedUser, avatar: StoredAvatar) -> UserProfileSnapshot:
        """Sostituisce l'avatar locale dell'utente mantenendo coerenza DB/storage."""

        # Conserva il vecchio percorso per poter eliminare il precedente avatar dopo l'aggiornamento
        previous_path: str | None = None

        try:

            # Recupera o crea il record locale associato al subject autenticato
            record = self._get_or_create_profile_record(user.subject)

            # Memorizza il percorso dell'avatar precedente prima di sovrascriverlo
            previous_path = record.avatar_path

            # Salva nel record locale il percorso del nuovo avatar
            record.avatar_path = avatar.path

            # Salva anche il media type del nuovo file
            record.avatar_media_type = avatar.media_type

            # Associa esplicitamente il record alla Session
            self.session.add(record)

            # Conferma sul database il nuovo riferimento all'avatar
            self.session.commit()

            # Recupera i dati identificativi Keycloak necessari per costruire la risposta completa
            keycloak_user = self.keycloak_admin.get_user(user.subject)

            # Se esisteva un avatar diverso dal nuovo, prova a eliminare il vecchio file dallo storage
            if previous_path and previous_path != avatar.path:
                self.avatar_storage.delete_avatar(previous_path)

            return self._build_profile_snapshot(keycloak_user, record)

        # Se Keycloak fallisce dopo il commit locale, il nuovo file viene eliminato ma il commit del database non può essere annullato dal rollback
        except KeycloakAdminError as exc:

            self.session.rollback()

            self.avatar_storage.delete_avatar(avatar.path)

            raise ProfileServiceError("Aggiornamento immagine profilo non riuscito.", HTTPStatus.BAD_GATEWAY) from exc

        # Se fallisce la parte SQL il nuovo file viene eliminato per evitare di lasciare un file non associato
        except SQLAlchemyError as exc:

            self.session.rollback()

            self.avatar_storage.delete_avatar(avatar.path)

            raise ProfileServiceError("Aggiornamento immagine profilo non riuscito.", HTTPStatus.INTERNAL_SERVER_ERROR) from exc

    # Rimuove dal profilo locale il riferimento all'avatar corrente e successivamente prova a cancellarne il file
    def delete_avatar(self, user: AuthenticatedUser) -> UserProfileSnapshot:
        """Rimuove l'avatar applicativo dell'utente corrente."""

        try:

            # Recupera o crea il record locale dell'utente
            record = self._get_or_create_profile_record(user.subject)

            # Conserva il percorso precedente per poter cancellare fisicamente il file dopo il commit
            previous_path = record.avatar_path

            # Rimuove il collegamento database al file avatar
            record.avatar_path = None

            # Rimuove anche il media type associato
            record.avatar_media_type = None

            self.session.add(record)

            # Conferma prima nel database che il profilo non utilizza più quell'avatar
            self.session.commit()

            # Se esisteva un file associato, ne richiede la cancellazione dallo storage
            if previous_path:
                self.avatar_storage.delete_avatar(previous_path)

            # Recupera i dati Keycloak necessari per ricostruire lo snapshot del profilo
            keycloak_user = self.keycloak_admin.get_user(user.subject)

            return self._build_profile_snapshot(keycloak_user, record)

        except KeycloakAdminError as exc:

            self.session.rollback()

            raise ProfileServiceError("Rimozione immagine profilo non riuscita.", HTTPStatus.BAD_GATEWAY) from exc

        except SQLAlchemyError as exc:

            self.session.rollback()

            raise ProfileServiceError("Rimozione immagine profilo non riuscita.", HTTPStatus.INTERNAL_SERVER_ERROR) from exc

    # Recupera il file avatar associato all'utente autenticato insieme al relativo media type
    def get_avatar_file(self, user: AuthenticatedUser) -> tuple[Path, str]:
        """Restituisce file e media type dell'avatar persistito per il subject dato."""

        try:

            # Recupera il record applicativo collegato al subject
            record = self._get_or_create_profile_record(user.subject)

            # Chiede allo storage di risolvere percorso e media type in un file effettivamente disponibile
            avatar = self.avatar_storage.resolve_avatar(record.avatar_path, record.avatar_media_type)

            # Se non esiste un avatar valido viene restituito un errore 404 applicativo
            if avatar is None:
                raise ProfileServiceError("Immagine profilo non trovata.", HTTPStatus.NOT_FOUND)

            return avatar

        except SQLAlchemyError as exc:

            self.session.rollback()

            raise ProfileServiceError("Immagine profilo non disponibile.", HTTPStatus.INTERNAL_SERVER_ERROR) from exc

    # Costruisce l'elenco mostrato nella pagina amministrazione combinando utenti Keycloak, conteggi delle analisi e profili locali
    def list_admin_users(self) -> list[AdminUserSummary]:
        """Costruisce l'elenco utenti mostrato nel pannello Amministrazione."""

        try:

            # Recupera da Keycloak tutti gli utenti gestiti
            users = self.keycloak_admin.list_users()

            # Costruisce una mappa subject -> numero di analisi usando una query aggregata sul database
            analysis_counts = {
                owner_sub: count
                for owner_sub, count in self.session.execute(
                    select(AnalysisRecordModel.owner_sub, func.count())
                    .where(AnalysisRecordModel.owner_sub.is_not(None))
                    .group_by(AnalysisRecordModel.owner_sub)
                ).all()
                if isinstance(owner_sub, str)
            }

            # Carica tutti i profili locali e li indicizza per subject per poter recuperare rapidamente eventuali avatar
            profile_records = {
                record.subject: record
                for record in self.session.scalars(select(UserProfileModel)).all()
            }

            # Costruisce una card amministrativa per ogni utente Keycloak
            return [
                self._build_admin_user_summary(
                    keycloak_user=user,
                    analysis_count=int(analysis_counts.get(user.subject, 0)),
                    profile_record=profile_records.get(user.subject),
                )
                for user in users
            ]

        # Un errore Keycloak o database rende non disponibile l'intero elenco amministrativo
        except (KeycloakAdminError, SQLAlchemyError) as exc:

            self.session.rollback()

            raise ProfileServiceError("Elenco utenti non disponibile.", HTTPStatus.INTERNAL_SERVER_ERROR) from exc

    # Aggiorna ruolo o stato enabled di un utente dopo aver applicato i vincoli che proteggono gli amministratori (ad esempio da analyst ad admin o viceversa)
    def update_admin_user(
        self,
        *,
        acting_user: AuthenticatedUser,
        subject: str,
        payload: AdminUserUpdateRequest,
    ) -> AdminUserSummary:
        """Aggiorna ruolo o stato di un utente applicando i guard rail admin."""

        try:

            # Recupera da Keycloak l'utente che l'amministratore vuole modificare
            target_user = self.keycloak_admin.get_user(subject)

            # Recupera tutti gli utenti per verificare quanti amministratori attivi rimarrebbero dopo la modifica
            managed_users = self.keycloak_admin.list_users()

            # Applica i vincoli che impediscono di rimuovere o disabilitare l'ultimo amministratore attivo
            self._validate_admin_update(
                acting_user=acting_user,
                target_user=target_user,
                payload=payload,
                managed_users=managed_users,
            )

            # Applica effettivamente in Keycloak il nuovo ruolo e/o stato enabled
            keycloak_user = self.keycloak_admin.update_user_access(
                subject=subject,
                role=payload.role,
                enabled=payload.enabled,
            )

            # Recupera l'eventuale profilo applicativo locale dell'utente
            profile_record = self.session.get(UserProfileModel, subject)

            # Conta le analisi appartenenti all'utente senza caricarle tutte
            analysis_count = self._count_user_analyses(subject)

            # Restituisce la card amministrativa aggiornata
            return self._build_admin_user_summary(
                keycloak_user=keycloak_user,
                analysis_count=analysis_count,
                profile_record=profile_record,
            )

        except KeycloakAdminError as exc:

            self.session.rollback()

            raise ProfileServiceError(
                str(exc),
                _infer_profile_http_status(str(exc), default_status=HTTPStatus.BAD_GATEWAY),
            ) from exc

        except SQLAlchemyError as exc:

            self.session.rollback()

            raise ProfileServiceError(
                "Aggiornamento utente amministrativo non riuscito.",
                HTTPStatus.INTERNAL_SERVER_ERROR,
            ) from exc

    # Aggiorna i dati identificativi di un utente scelto dall'amministratore
    def update_admin_user_profile(
        self,
        *,
        acting_user: AuthenticatedUser,
        subject: str,
        payload: AdminUserProfileUpdateRequest,
    ) -> AdminUserSummary:
        """Aggiorna i dati identitari di un utente scelto dall'amministratore."""

        # Il parametro viene intenzionalmente scartato perché questo metodo si affida al router per il controllo del ruolo admin
        del acting_user

        try:

            # Aggiorna in Keycloak username, nome, cognome ed email del soggetto target
            keycloak_user = self.keycloak_admin.update_user_profile(
                subject=subject,
                username=payload.username,
                first_name=payload.first_name,
                last_name=payload.last_name,
                email=payload.email,
            )

            # Recupera l'eventuale record applicativo locale collegato al subject
            profile_record = self.session.get(UserProfileModel, subject)

            # Conta le analisi dell'utente per popolare il riepilogo amministrativo
            analysis_count = self._count_user_analyses(subject)

            return self._build_admin_user_summary(
                keycloak_user=keycloak_user,
                analysis_count=analysis_count,
                profile_record=profile_record,
            )

        except KeycloakAdminError as exc:

            self.session.rollback()

            raise ProfileServiceError(
                str(exc),
                _infer_profile_http_status(str(exc), default_status=HTTPStatus.BAD_GATEWAY),
            ) from exc

        except SQLAlchemyError as exc:

            self.session.rollback()

            raise ProfileServiceError(
                "Aggiornamento dati utente non riuscito.",
                HTTPStatus.INTERNAL_SERVER_ERROR,
            ) from exc

    # Recupera il profilo di un utente e tutte le informazioni sulle sue analisi per mostrarle nella pagina di amministrazione
    def get_admin_user_analyses(self, subject: str) -> AdminUserAnalysesSnapshot:
        """Costruisce il Dettaglio utente amministrativo con profilo e analisi."""

        try:

            # Recupera l'identità dell'utente da Keycloak
            keycloak_user = self.keycloak_admin.get_user(subject)

            # Recupera l'eventuale profilo locale
            profile_record = self.session.get(UserProfileModel, subject)

            # Costruisce il riepilogo amministrativo dell'utente
            user_summary = self._build_admin_user_summary(
                keycloak_user=keycloak_user,
                analysis_count=self._count_user_analyses(subject),
                profile_record=profile_record,
            )

            # Riutilizza il repository SQLAlchemy per ottenere tutte le analisi filtrate per owner_sub
            analyses = SqlAlchemyAnalysisRepository(self.session).list_all(owner_sub=subject)

            # Restituisce in un unico snapshot riepilogo utente, statistiche, distribuzione rischio e cronologia completa
            return AdminUserAnalysesSnapshot(
                user=user_summary,
                statistics=self._collect_profile_statistics(subject),
                risk_distribution=self._collect_risk_distribution(subject),
                analyses=analyses,
            )

        except (KeycloakAdminError, SQLAlchemyError) as exc:

            self.session.rollback()

            raise ProfileServiceError("Dettaglio utente non disponibile.", HTTPStatus.INTERNAL_SERVER_ERROR) from exc

    # Invia all'utente autenticato l'email necessaria per verificare il proprio indirizzo email
    def send_verification_email(self, user: AuthenticatedUser) -> VerificationEmailResponse:
        """Richiede una mail di verifica per l'utente autenticato, se configurata."""

        # La verifica email deve essere esplicitamente abilitata
        if not settings.email_verification_enabled:
            raise ProfileServiceError("La verifica email non è attualmente disponibile.", HTTPStatus.SERVICE_UNAVAILABLE)

        # L'invio richiede anche un server SMTP configurato
        if not settings.smtp_configured:
            raise ProfileServiceError(
                "L'invio dell'email non è disponibile. Configura correttamente il server SMTP.",
                HTTPStatus.SERVICE_UNAVAILABLE,
            )

        try:

            # Recupera lo stato corrente dell'utente da Keycloak
            keycloak_user = self.keycloak_admin.get_user(user.subject)

            # Se esiste già una nuova email pendente, reinvia la verifica relativa al cambio email
            if keycloak_user.pending_email:
                self.keycloak_admin.resend_pending_email_change(subject=user.subject)
                return VerificationEmailResponse(
                    detail="Email di verifica inviata correttamente al nuovo indirizzo."
                )

            # Non invia una nuova verifica se l'indirizzo corrente risulta già verificato
            if keycloak_user.email_verified:
                raise ProfileServiceError("L'indirizzo email risulta già verificato.", HTTPStatus.CONFLICT)

            # Non è possibile inviare una verifica se l'account non contiene un indirizzo email
            if not keycloak_user.email:
                raise ProfileServiceError("Nessun indirizzo email associato all'account.", HTTPStatus.CONFLICT)

            # Chiede a Keycloak di inviare la mail di verifica
            self.keycloak_admin.send_verification_email(subject=user.subject)

            return VerificationEmailResponse(detail="Email di verifica inviata correttamente")

        except KeycloakAdminError as exc:
            raise ProfileServiceError(
                str(exc),
                _infer_profile_http_status(str(exc), default_status=HTTPStatus.BAD_GATEWAY),
            ) from exc

    # Permette all'utente autenticato di eliminare il proprio account dal sistema
    def delete_own_account(self, user: AuthenticatedUser) -> None:
        """Elimina l'account corrente rispettando i vincoli di ultimo admin."""

        try:

            # Recupera l'utente corrente da Keycloak
            keycloak_user = self.keycloak_admin.get_user(user.subject)

            # Recupera tutti gli utenti per valutare il numero di amministratori attivi
            managed_users = self.keycloak_admin.list_users()

            # Verifica che la cancellazione sia consentita e non lasci il sistema senza amministratori
            self._validate_user_deletion(
                acting_user=user,
                target_user=keycloak_user,
                managed_users=managed_users,
                is_self_service=True,
            )

            # Recupera l'eventuale profilo applicativo locale
            profile_record = self.session.get(UserProfileModel, user.subject)

            # Conserva il percorso avatar prima dell'eventuale eliminazione del record
            avatar_path = profile_record.avatar_path if profile_record else None

            # Elimina prima l'account dal sistema di identità Keycloak
            self.keycloak_admin.delete_user(subject=user.subject)

            # Se esiste un profilo locale, lo elimina da PostgreSQL e conferma la transazione
            if profile_record is not None:
                self.session.delete(profile_record)
                self.session.commit()

            # Se era associato un avatar ne elimina anche il file dallo storage
            if avatar_path:
                self.avatar_storage.delete_avatar(avatar_path)

        except KeycloakAdminError as exc:

            self.session.rollback()

            raise ProfileServiceError(
                str(exc),
                _infer_profile_http_status(str(exc), default_status=HTTPStatus.BAD_GATEWAY),
            ) from exc

        except SQLAlchemyError as exc:

            self.session.rollback()

            raise ProfileServiceError("Eliminazione account non riuscita.", HTTPStatus.INTERNAL_SERVER_ERROR) from exc

    # Invia la mail di verifica a un utente scelto dall'amministratore
    def send_admin_verification_email(self, *, subject: str) -> VerificationEmailResponse:
        """Invia la mail di verifica per un utente scelto dall'amministratore."""

        # Anche il flusso amministrativo richiede la verifica email abilitata
        if not settings.email_verification_enabled:
            raise ProfileServiceError("La verifica email non è attualmente disponibile.", HTTPStatus.SERVICE_UNAVAILABLE)

        # Il server SMTP deve risultare configurato
        if not settings.smtp_configured:
            raise ProfileServiceError(
                "L'invio dell'email non è disponibile. Configura correttamente il server SMTP.",
                HTTPStatus.SERVICE_UNAVAILABLE,
            )

        try:

            # Recupera da Keycloak l'utente target
            keycloak_user = self.keycloak_admin.get_user(subject)

            # Blocca questo flusso se esiste già una nuova email in attesa di verifica
            if keycloak_user.pending_email:
                raise ProfileServiceError(
                    "È già presente una nuova email in attesa di verifica. Usa il flusso dedicato di aggiornamento email.",
                    HTTPStatus.CONFLICT,
                )

            # Non serve inviare una verifica se l'indirizzo risulta già verificato
            if keycloak_user.email_verified:
                raise ProfileServiceError("L'indirizzo email risulta già verificato.", HTTPStatus.CONFLICT)

            # Blocca l'operazione se non esiste alcun indirizzo email
            if not keycloak_user.email:
                raise ProfileServiceError("Nessun indirizzo email associato all'account.", HTTPStatus.CONFLICT)

            # Richiede a Keycloak l'invio della mail di verifica
            self.keycloak_admin.send_verification_email(subject=subject)

            return VerificationEmailResponse(detail="Email di verifica inviata correttamente")

        except KeycloakAdminError as exc:
            raise ProfileServiceError(
                str(exc),
                _infer_profile_http_status(str(exc), default_status=HTTPStatus.BAD_GATEWAY),
            ) from exc

    # Elimina un utente scelto dall'amministratore applicando gli stessi guard rail sulla presenza di admin attivi
    def delete_admin_user(self, *, acting_user: AuthenticatedUser, subject: str) -> None:
        """Elimina un utente dal perimetro amministrativo con i vincoli di sicurezza."""

        try:

            # Recupera l'utente target da Keycloak
            target_user = self.keycloak_admin.get_user(subject)

            # Recupera tutti gli utenti per poter verificare se il target è l'ultimo admin attivo
            managed_users = self.keycloak_admin.list_users()

            # Applica i controlli di sicurezza prima dell'eliminazione
            self._validate_user_deletion(
                acting_user=acting_user,
                target_user=target_user,
                managed_users=managed_users,
                is_self_service=False,
            )

            # Recupera l'eventuale profilo applicativo locale
            profile_record = self.session.get(UserProfileModel, subject)

            # Conserva il percorso dell'eventuale avatar
            avatar_path = profile_record.avatar_path if profile_record else None

            # Elimina l'account in Keycloak
            self.keycloak_admin.delete_user(subject=subject)

            # Elimina anche il profilo locale se presente
            if profile_record is not None:
                self.session.delete(profile_record)
                self.session.commit()

            # Elimina infine il file avatar eventualmente associato
            if avatar_path:
                self.avatar_storage.delete_avatar(avatar_path)

        except KeycloakAdminError as exc:

            self.session.rollback()

            raise ProfileServiceError(
                str(exc),
                _infer_profile_http_status(str(exc), default_status=HTTPStatus.BAD_GATEWAY),
            ) from exc

        except SQLAlchemyError as exc:

            self.session.rollback()

            raise ProfileServiceError("Eliminazione account non riuscita.", HTTPStatus.INTERNAL_SERVER_ERROR) from exc

    # Costruisce i dati completi mostrati nella pagina Profilo dell'utente autenticato unendo informazioni Keycloak, foto profilo e statistiche delle sue analisi
    def _build_profile_snapshot(
        self,
        keycloak_user: KeycloakUser,
        profile_record: UserProfileModel,
    ) -> UserProfileSnapshot:
        """Combina identità Keycloak, avatar locale e statistiche utente."""

        # Calcola le statistiche delle analisi appartenenti al subject corrente
        stats = self._collect_profile_statistics(keycloak_user.subject)

        # Costruisce il modello finale restituito alla UI
        return UserProfileSnapshot(
            subject=keycloak_user.subject,
            username=keycloak_user.username,
            first_name=keycloak_user.first_name,
            last_name=keycloak_user.last_name,
            email=keycloak_user.email,
            email_verified=keycloak_user.email_verified,
            pending_email=keycloak_user.pending_email,
            email_change_pending=bool(keycloak_user.pending_email),
            email_verification_available=settings.email_verification_enabled and settings.smtp_configured,
            roles=keycloak_user.roles,

            # Espone l'URL API dell'avatar solo se lo storage riesce effettivamente a risolvere il file associato
            avatar_url="/api/v1/me/avatar"
            if self.avatar_storage.resolve_avatar(
                profile_record.avatar_path,
                profile_record.avatar_media_type,
            )
            else None,
            statistics=stats,
        )

    # Costruisce il riepilogo usato nel pannello amministrativo combinando identità Keycloak, conteggio analisi e avatar locale (la card degli utenti mostrata nella pagina amministrazione)
    def _build_admin_user_summary(
        self,
        *,
        keycloak_user: KeycloakUser,
        analysis_count: int,
        profile_record: UserProfileModel | None,
    ) -> AdminUserSummary:
        """Costruisce la card amministrativa riassuntiva di un utente."""

        return AdminUserSummary(
            subject=keycloak_user.subject,
            username=keycloak_user.username,
            first_name=keycloak_user.first_name,
            last_name=keycloak_user.last_name,
            email=keycloak_user.email,
            email_verified=keycloak_user.email_verified,
            pending_email=keycloak_user.pending_email,
            email_change_pending=bool(keycloak_user.pending_email),
            enabled=keycloak_user.enabled,
            roles=keycloak_user.roles,
            email_verification_available=settings.email_verification_enabled and settings.smtp_configured,
            analysis_count=analysis_count,

            # Converte l'eventuale avatar locale in una data URL direttamente utilizzabile dal frontend amministrativo
            avatar_data_url=self.avatar_storage.build_data_url(
                profile_record.avatar_path if profile_record else None,
                profile_record.avatar_media_type if profile_record else None,
            ),
            created_at=keycloak_user.created_at,
        )

    # Calcola le statistiche sulle analisi di uno specifico utente mostrate nel suo profilo e nel dettaglio amministrativo
    def _collect_profile_statistics(self, owner_sub: str) -> ProfileStatistics:
        """Calcola i contatori usati nelle card profilo e dettaglio utente."""

        # Raggruppa per stato tecnico soltanto le analisi il cui owner_sub corrisponde al subject richiesto
        rows = self.session.execute(
            select(AnalysisRecordModel.status, func.count())
            .where(AnalysisRecordModel.owner_sub == owner_sub)
            .group_by(AnalysisRecordModel.status)
        ).all()

        # Converte le righe SQLAlchemy in un dizionario stato -> conteggio
        counts = {status: int(count) for status, count in rows if isinstance(status, AnalysisStatus)}

        # Recupera separatamente il numero di analisi in coda
        queued = counts.get(AnalysisStatus.QUEUED, 0)

        # Recupera il numero di analisi attualmente in elaborazione
        processing = counts.get(AnalysisStatus.PROCESSING, 0)

        # Costruisce le statistiche aggregate mostrate nella pagina Profilo e nel dettaglio amministrativo
        return ProfileStatistics(
            total_analyses=sum(counts.values()),
            completed=counts.get(AnalysisStatus.COMPLETED, 0),
            queued_or_processing=queued + processing,
            failed=counts.get(AnalysisStatus.FAILED, 0),
        )

    # Conta il numero totale di analisi appartenenti a un utente senza caricare i relativi record
    def _count_user_analyses(self, owner_sub: str) -> int:
        """Conta le analisi di un utente senza caricare la sua cronologia completa."""

        # `COUNT(*)` viene eseguito direttamente nel database applicando il filtro sul subject proprietario
        return int(
            self.session.scalar(
                select(func.count())
                .select_from(AnalysisRecordModel)
                .where(AnalysisRecordModel.owner_sub == owner_sub)
            )
            or 0
        )

    # Calcola la distribuzione delle analisi dell'utente per livello di rischio mostrata nel dettaglio amministrativo (sezione statistiche)
    def _collect_risk_distribution(self, owner_sub: str) -> list[DashboardRiskDistributionEntry]:
        """Calcola i badge rischio mostrati nel Dettaglio utente amministrativo."""

        # Raggruppa le analisi del subject per livello di rischio e ne conta i record
        rows = self.session.execute(
            select(AnalysisRecordModel.risk_level, func.count())
            .where(AnalysisRecordModel.owner_sub == owner_sub)
            .group_by(AnalysisRecordModel.risk_level)
        ).all()

        # Trasforma i risultati in una mappa valore testuale del rischio -> conteggio
        counts = {risk_level.value: int(count) for risk_level, count in rows if risk_level is not None}

        # Restituisce sempre i quattro livelli nell'ordine Critico, Alto, Medio, Basso anche quando alcuni hanno conteggio zero
        return [
            DashboardRiskDistributionEntry(risk_level=risk_level, count=counts.get(risk_level.value, 0))
            for risk_level in (RiskLevel.CRITICAL, RiskLevel.HIGH, RiskLevel.MEDIUM, RiskLevel.LOW)
        ]

    # Prima di cambiare il ruolo o disabilitare un utente, controlla che l'operazione non lasci il sistema senza amministratori attivi
    def _validate_admin_update(
        self,
        *,
        acting_user: AuthenticatedUser,
        target_user: KeycloakUser,
        payload: AdminUserUpdateRequest,
        managed_users: list[KeycloakUser],
    ) -> None:
        """Impedisce la rimozione o disabilitazione dell'ultimo admin attivo."""

        # Determina se il nuovo ruolo richiesto rimuoverebbe il ruolo admin da un amministratore esistente
        role_change_removes_admin = payload.role == "analyst" and "admin" in target_user.roles

        # Determina se la richiesta disabiliterebbe un amministratore attualmente attivo
        disable_removes_admin = payload.enabled is False and "admin" in target_user.roles and target_user.enabled

        # Se la modifica non riduce il numero di amministratori attivi non servono ulteriori controlli
        if not role_change_removes_admin and not disable_removes_admin:
            return

        # Costruisce l'elenco degli amministratori attualmente abilitati
        enabled_admins = [
            user for user in managed_users if user.enabled and "admin" in user.roles
        ]

        # Verifica se il target è esattamente l'unico amministratore ancora abilitato
        is_last_enabled_admin = len(enabled_admins) == 1 and enabled_admins[0].subject == target_user.subject

        # Impedisce qualsiasi modifica che lascerebbe il sistema senza amministratori attivi
        if is_last_enabled_admin:
            raise ProfileServiceError(
                "Non è possibile rimuovere o disabilitare l'ultimo amministratore attivo del sistema.",
                HTTPStatus.CONFLICT,
            )

        # Impedisce all'amministratore di rimuovere autonomamente il proprio ruolo o disabilitare il proprio account tramite questo flusso
        if acting_user.subject == target_user.subject:
            raise ProfileServiceError(
                "Per modificare il tuo ruolo o lo stato del tuo account è necessario usare un altro account amministrativo.",
                HTTPStatus.CONFLICT,
            )

    # Verifica che un'eliminazione non lasci il sistema senza amministratori e che il flusso self-service operi sul soggetto autenticato
    def _validate_user_deletion(
        self,
        *,
        acting_user: AuthenticatedUser,
        target_user: KeycloakUser,
        managed_users: list[KeycloakUser],
        is_self_service: bool,
    ) -> None:
        """Blocca eliminazioni che lascerebbero il sistema senza admin attivi."""

        # Individua tutti gli utenti Keycloak che risultano contemporaneamente abilitati e amministratori
        enabled_admins = [
            managed_user
            for managed_user in managed_users
            if managed_user.enabled and "admin" in managed_user.roles
        ]

        # Verifica se il target è l'unico amministratore attivo rimasto
        is_last_enabled_admin = (
            "admin" in target_user.roles
            and target_user.enabled
            and len(enabled_admins) == 1
            and enabled_admins[0].subject == target_user.subject
        )

        # Blocca la cancellazione dell'ultimo amministratore attivo
        if is_last_enabled_admin:
            raise ProfileServiceError(
                "Non è possibile eliminare l'ultimo amministratore attivo del sistema.",
                HTTPStatus.CONFLICT,
            )

        # Nel flusso self-service il subject autenticato deve coincidere con quello dell'account da eliminare
        if is_self_service and acting_user.subject != target_user.subject:
            raise ProfileServiceError("Operazione non consentita.", HTTPStatus.FORBIDDEN)

    # Cerca in PostgreSQL il profilo locale dell'utente e, se non esiste ancora, lo crea
    def _get_or_create_profile_record(self, subject: str) -> UserProfileModel:
        """Restituisce il record profilo locale, creandolo on demand se assente."""

        # Cerca direttamente tramite chiave primaria il record UserProfileModel corrispondente al subject
        record = self.session.get(UserProfileModel, subject)

        # Se il profilo applicativo non esiste ancora ne crea uno minimale collegato allo stesso subject Keycloak
        if record is None:
            record = UserProfileModel(subject=subject)

            # Inserisce il nuovo oggetto nella Session SQLAlchemy
            self.session.add(record)

            # `flush()` invia l'INSERT al database nella transazione corrente senza eseguire ancora il commit definitivo
            self.session.flush()

        return record


# Dependency FastAPI che costruisce UserProfileService combinando Session database, storage avatar e client Keycloak
def get_profile_service(
    session: Session = Depends(get_db_session),
    avatar_storage: AvatarStorageService = Depends(get_avatar_storage_service),
) -> UserProfileService:
    """Dependency FastAPI che fornisce il servizio a Profilo e Amministrazione."""

    # Crea il service usando le dipendenze risolte da FastAPI e una nuova istanza del client amministrativo Keycloak
    return UserProfileService(
        session=session,
        keycloak_admin=KeycloakAdminClient(),
        avatar_storage=avatar_storage,
    )


# Traduce alcuni messaggi applicativi provenienti dal layer Keycloak in codici HTTP più specifici per la UI
def _infer_profile_http_status(message: str, *, default_status: int) -> int:
    """Converte alcuni errori Keycloak in status HTTP più leggibili per la UI."""

    # Normalizza il messaggio in minuscolo per eseguire confronti testuali indipendenti dalle maiuscole
    normalized = message.lower()

    # Account già esistente corrisponde a un conflitto con una risorsa già presente
    if "esiste già un account" in normalized:
        return int(HTTPStatus.CONFLICT)

    # Username o altro valore già occupato viene trattato come conflitto
    if "non è disponibile. scegline un altro" in normalized:
        return int(HTTPStatus.CONFLICT)

    # Valori non validi o contrari alla policy vengono tradotti in 422 Unprocessable Entity
    if "non è valido" in normalized or "non rispetta la policy" in normalized:
        return int(HTTPStatus.UNPROCESSABLE_ENTITY)

    # Credenziale o valore non corretto viene trattato come richiesta non valida
    if "non è corretta" in normalized:
        return int(HTTPStatus.BAD_REQUEST)

    # Se nessuna regola testuale corrisponde utilizza il codice HTTP fornito dal chiamante
    return int(default_status)
