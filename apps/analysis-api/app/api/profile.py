"""Endpoint self-service usati da Profilo e Modifica profilo.

Queste API permettono all'utente autenticato di leggere e aggiornare i propri
dati, cambiare password, gestire l'avatar e richiedere di nuovo la verifica
email. Tutte le operazioni sono sempre riferite al subject del token corrente:
un utente non può passare un identificativo arbitrario e agire su un altro
profilo.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from fastapi.responses import FileResponse

from app.auth.security import AuthenticatedUser, require_analyst
from app.models.profile import (
    UpdateOwnPasswordRequest,
    UpdateOwnProfileRequest,
    UserProfileSnapshot,
    VerificationEmailResponse,
)
from app.services.avatar_storage import (
    AvatarStorageError,
    AvatarValidationError,
    AvatarStorageService,
    get_avatar_storage_service,
)
from app.services.profile_service import ProfileServiceError, UserProfileService, get_profile_service

router = APIRouter(prefix="/me", tags=["profile"])


@router.get("/profile", response_model=UserProfileSnapshot)
def get_profile(
    user: AuthenticatedUser = Depends(require_analyst),
    service: UserProfileService = Depends(get_profile_service),
) -> UserProfileSnapshot:
    """Restituisce il profilo completo dell'utente autenticato."""
    try:
        return service.get_profile_snapshot(user)
    except ProfileServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.put("/profile", response_model=UserProfileSnapshot)
def update_profile(
    payload: UpdateOwnProfileRequest,
    user: AuthenticatedUser = Depends(require_analyst),
    service: UserProfileService = Depends(get_profile_service),
) -> UserProfileSnapshot:
    """Aggiorna i campi profilo delegati a Keycloak per l'utente corrente."""
    try:
        return service.update_profile(user, payload)
    except ProfileServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.get("/avatar", response_class=FileResponse)
def get_avatar(
    user: AuthenticatedUser = Depends(require_analyst),
    service: UserProfileService = Depends(get_profile_service),
) -> FileResponse:
    """Restituisce l'avatar applicativo dell'utente autenticato, se presente."""
    try:
        avatar_path, media_type = service.get_avatar_file(user)
    except ProfileServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    return FileResponse(
        path=avatar_path,
        media_type=media_type,
        headers={
            "Cache-Control": "private, no-store",
            "Pragma": "no-cache",
            "Vary": "Authorization",
        },
    )


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def change_password(
    payload: UpdateOwnPasswordRequest,
    user: AuthenticatedUser = Depends(require_analyst),
    service: UserProfileService = Depends(get_profile_service),
) -> Response:
    """Aggiorna la password tramite Keycloak senza toccare il database applicativo."""
    try:
        service.change_password(user, payload)
    except ProfileServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/verification-email", response_model=VerificationEmailResponse)
def resend_own_verification_email(
    user: AuthenticatedUser = Depends(require_analyst),
    service: UserProfileService = Depends(get_profile_service),
) -> VerificationEmailResponse:
    """Richiede una nuova email di verifica indirizzata all'utente autenticato."""
    try:
        return service.send_verification_email(user)
    except ProfileServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.delete("/profile", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def delete_own_account(
    user: AuthenticatedUser = Depends(require_analyst),
    service: UserProfileService = Depends(get_profile_service),
) -> Response:
    """Elimina l'account dell'utente corrente nel perimetro self-service."""
    try:
        service.delete_own_account(user)
    except ProfileServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/avatar", response_model=UserProfileSnapshot, status_code=status.HTTP_201_CREATED)
async def upload_avatar(
    avatar: UploadFile = File(..., description="Avatar image"),
    user: AuthenticatedUser = Depends(require_analyst),
    service: UserProfileService = Depends(get_profile_service),
    storage: AvatarStorageService = Depends(get_avatar_storage_service),
) -> UserProfileSnapshot:
    """Valida e sostituisce l'avatar dell'utente autenticato."""
    stored_avatar = None
    try:
        stored_avatar = await storage.save_avatar(avatar, previous_path=None)
        return service.replace_avatar(user, stored_avatar)
    except AvatarValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except AvatarStorageError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to store avatar.") from exc
    except ProfileServiceError as exc:
        if stored_avatar is not None:
            # keep old avatar untouched when DB update fails
            try:
                storage.delete_avatar(stored_avatar.path)
            except Exception:  # noqa: BLE001
                pass
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc


@router.delete("/avatar", response_model=UserProfileSnapshot)
def delete_avatar(
    user: AuthenticatedUser = Depends(require_analyst),
    service: UserProfileService = Depends(get_profile_service),
) -> UserProfileSnapshot:
    """Rimuove l'avatar applicativo dell'utente autenticato."""
    try:
        return service.delete_avatar(user)
    except ProfileServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
