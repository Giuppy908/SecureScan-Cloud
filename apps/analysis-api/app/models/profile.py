"""Schemi Pydantic per Profilo, Modifica profilo e Amministrazione utenti.

Questi modelli descrivono i dati scambiati tra backend e frontend quando:
- un utente apre il proprio Profilo;
- modifica i propri dati;
- cambia password;
- gestisce l'avatar;
- un amministratore consulta o modifica un altro utente.

Anche qui è importante una distinzione: alcuni dati arrivano da Keycloak
(identità, email, ruoli), altri dal database applicativo (avatar, contatori,
snapshot arricchiti usati dall'interfaccia).
"""

from __future__ import annotations

import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.analysis import Analysis
from app.models.dashboard import DashboardRiskDistributionEntry

USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9._-]{3,32}$")


def _validate_email(value: str) -> str:
    """Applica una validazione email minimale e coerente con la UI italiana."""
    normalized = value.strip().lower()
    if not normalized or "@" not in normalized:
        raise ValueError("L'indirizzo email non è valido.")
    local_part, _, domain_part = normalized.partition("@")
    if not local_part or not domain_part or "." not in domain_part:
        raise ValueError("L'indirizzo email non è valido.")
    return normalized


class ProfileStatistics(BaseModel):
    """Contatori analisi riferiti a un singolo utente o a uno snapshot admin."""

    total_analyses: int = Field(ge=0)
    completed: int = Field(ge=0)
    queued_or_processing: int = Field(ge=0)
    failed: int = Field(ge=0)


class UserProfileSnapshot(BaseModel):
    """Snapshot del profilo mostrato nella pagina profilo autenticata."""

    subject: str
    username: str
    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None
    email_verified: bool
    pending_email: str | None = None
    email_change_pending: bool = False
    email_verification_available: bool = False
    roles: list[str]
    avatar_url: str | None = None
    statistics: ProfileStatistics


class UpdateOwnProfileRequest(BaseModel):
    """Campi che l'utente può modificare dalla pagina Modifica profilo."""

    model_config = ConfigDict(extra="forbid")

    first_name: str = Field(min_length=1, max_length=50)
    last_name: str = Field(min_length=1, max_length=50)
    username: str = Field(min_length=3, max_length=32)
    email: str = Field(min_length=5, max_length=254)

    @field_validator("first_name", "last_name")
    @classmethod
    def validate_personal_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Questo campo è obbligatorio.")
        return normalized

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        normalized = value.strip()
        if not USERNAME_PATTERN.fullmatch(normalized):
            raise ValueError(
                "Lo username deve contenere da 3 a 32 caratteri e può includere solo lettere, numeri, punto, trattino o underscore."
            )
        return normalized

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        return _validate_email(value)


class UpdateOwnPasswordRequest(BaseModel):
    """Richiesta usata quando l'utente cambia password dal proprio profilo."""

    model_config = ConfigDict(extra="forbid")

    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=8, max_length=24)
    confirm_new_password: str = Field(min_length=8, max_length=24)
    logout_other_sessions: bool = True

    @field_validator("current_password")
    @classmethod
    def validate_current_password(cls, value: str) -> str:
        if not value:
            raise ValueError("La password attuale è obbligatoria.")
        return value

    @field_validator("new_password")
    @classmethod
    def validate_new_password(cls, value: str) -> str:
        if len(value) > 24:
            raise ValueError("La nuova password non può superare 24 caratteri.")
        if not re.search(r"[A-Z]", value):
            raise ValueError("La nuova password deve contenere almeno una lettera maiuscola.")
        if not re.search(r"[a-z]", value):
            raise ValueError("La nuova password deve contenere almeno una lettera minuscola.")
        if not re.search(r"[0-9]", value):
            raise ValueError("La nuova password deve contenere almeno una cifra.")
        if not re.search(r"[^A-Za-z0-9]", value):
            raise ValueError("La nuova password deve contenere almeno un carattere speciale.")
        return value

    @field_validator("confirm_new_password")
    @classmethod
    def validate_confirm_password(cls, value: str) -> str:
        if not value:
            raise ValueError("La conferma password è obbligatoria.")
        return value


class AdminUserSummary(BaseModel):
    """Rappresentazione amministrativa di un utente Keycloak arricchita dall'app."""

    subject: str
    username: str
    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None
    email_verified: bool
    pending_email: str | None = None
    email_change_pending: bool = False
    enabled: bool
    roles: list[str]
    email_verification_available: bool = False
    analysis_count: int = Field(ge=0)
    avatar_data_url: str | None = None
    created_at: datetime | None = None


class AdminUserUpdateRequest(BaseModel):
    """Modifiche che l'amministratore può applicare a un altro account."""

    model_config = ConfigDict(extra="forbid")

    role: str | None = None
    enabled: bool | None = None

    @field_validator("role")
    @classmethod
    def validate_role(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if value not in {"analyst", "admin"}:
            raise ValueError("Il ruolo deve essere analyst o admin.")
        return value


class AdminUserProfileUpdateRequest(BaseModel):
    """Dati identitari che l'amministratore può correggere per un altro utente."""

    model_config = ConfigDict(extra="forbid")

    first_name: str = Field(min_length=1, max_length=50)
    last_name: str = Field(min_length=1, max_length=50)
    username: str = Field(min_length=3, max_length=32)
    email: str = Field(min_length=5, max_length=254)

    @field_validator("first_name", "last_name")
    @classmethod
    def validate_personal_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Questo campo è obbligatorio.")
        return normalized

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        normalized = value.strip()
        if not USERNAME_PATTERN.fullmatch(normalized):
            raise ValueError(
                "Lo username deve contenere da 3 a 32 caratteri e può includere solo lettere, numeri, punto, trattino o underscore."
            )
        return normalized

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        return _validate_email(value)


class AdminUserAnalysesSnapshot(BaseModel):
    """Snapshot mostrato quando l'admin apre il dettaglio di un utente."""

    user: AdminUserSummary
    statistics: ProfileStatistics
    risk_distribution: list[DashboardRiskDistributionEntry]
    analyses: list[Analysis]


class VerificationEmailResponse(BaseModel):
    """Risposta restituita dopo l'invio o il reinvio della verifica email."""

    detail: str
