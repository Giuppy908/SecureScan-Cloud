"""Endpoint amministrativi usati dalla pagina Amministrazione.

Questo file raccoglie le API che l'amministratore usa per:
- vedere l'elenco utenti;
- aprire il dettaglio di un utente;
- modificare ruolo o stato dell'account;
- consultare le analisi associate a quell'utente;
- reinviare la verifica email o eliminare un account.

Il frontend non parla direttamente con Keycloak Admin API: passa sempre da
questi endpoint, che applicano RBAC server-side e coordinano Keycloak con i
dati applicativi locali salvati in PostgreSQL.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.auth.security import AuthenticatedUser, require_admin
from app.models.profile import (
    AdminUserAnalysesSnapshot,
    AdminUserProfileUpdateRequest,
    AdminUserSummary,
    AdminUserUpdateRequest,
    VerificationEmailResponse,
)
from app.services.profile_service import ProfileServiceError, UserProfileService, get_profile_service

router = APIRouter(prefix="/admin/users", tags=["admin-users"])


@router.get("", response_model=list[AdminUserSummary])
def list_admin_users(
    _: AuthenticatedUser = Depends(require_admin),
    service: UserProfileService = Depends(get_profile_service),
) -> list[AdminUserSummary]:
    """Restituisce l'elenco utenti mostrato nel pannello Amministrazione."""
    try:
        return service.list_admin_users()
    except ProfileServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.patch("/{subject}", response_model=AdminUserSummary)
def update_admin_user(
    subject: str,
    payload: AdminUserUpdateRequest,
    user: AuthenticatedUser = Depends(require_admin),
    service: UserProfileService = Depends(get_profile_service),
) -> AdminUserSummary:
    """Aggiorna ruolo o stato di un utente dal pannello Amministrazione."""
    try:
        return service.update_admin_user(acting_user=user, subject=subject, payload=payload)
    except ProfileServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.patch("/{subject}/profile", response_model=AdminUserSummary)
def update_admin_user_profile(
    subject: str,
    payload: AdminUserProfileUpdateRequest,
    user: AuthenticatedUser = Depends(require_admin),
    service: UserProfileService = Depends(get_profile_service),
) -> AdminUserSummary:
    """Aggiorna i dati anagrafici mostrati nel Dettaglio utente amministrativo."""
    try:
        return service.update_admin_user_profile(acting_user=user, subject=subject, payload=payload)
    except ProfileServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.get("/{subject}", response_model=AdminUserAnalysesSnapshot)
def get_admin_user_detail(
    subject: str,
    _: AuthenticatedUser = Depends(require_admin),
    service: UserProfileService = Depends(get_profile_service),
) -> AdminUserAnalysesSnapshot:
    """Carica il Dettaglio utente amministrativo con profilo, statistiche e analisi."""
    try:
        return service.get_admin_user_analyses(subject)
    except ProfileServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.post("/{subject}/verification-email", response_model=VerificationEmailResponse)
def resend_admin_verification_email(
    subject: str,
    _: AuthenticatedUser = Depends(require_admin),
    service: UserProfileService = Depends(get_profile_service),
) -> VerificationEmailResponse:
    """Permette all'amministratore di reinviare la mail di verifica account."""
    try:
        return service.send_admin_verification_email(subject=subject)
    except ProfileServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.delete("/{subject}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def delete_admin_user(
    subject: str,
    user: AuthenticatedUser = Depends(require_admin),
    service: UserProfileService = Depends(get_profile_service),
) -> Response:
    """Elimina un account dal pannello admin rispettando i vincoli di sicurezza."""
    try:
        service.delete_admin_user(acting_user=user, subject=subject)
    except ProfileServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{subject}/analyses", response_model=AdminUserAnalysesSnapshot)
def get_admin_user_analyses(
    subject: str,
    _: AuthenticatedUser = Depends(require_admin),
    service: UserProfileService = Depends(get_profile_service),
) -> AdminUserAnalysesSnapshot:
    """Espone la cronologia di un singolo utente nel Dettaglio utente amministrativo."""
    try:
        return service.get_admin_user_analyses(subject)
    except ProfileServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
