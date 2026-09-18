"""Regressioni statiche sul flow di cambio email self-service.

Questi test non eseguono un Keycloak reale, ma verificano che repository,
provider custom e frontend mantengano i contratti minimi richiesti dal flow:
- nessuna required action UPDATE_EMAIL persistente durante il pending state;
- token di conferma costruito con logout sessioni attivo;
- feedback UI transitorio separato dallo stato persistente dell'account.
"""

from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
PROVIDER_SOURCE = (
    REPO_ROOT
    / "infrastructure"
    / "keycloak"
    / "providers"
    / "securescan-email-change"
    / "src"
    / "main"
    / "java"
    / "cloud"
    / "securescan"
    / "keycloak"
    / "emailchange"
    / "SecureScanEmailChangeResource.java"
)
TOKEN_SOURCE = (
    REPO_ROOT
    / "infrastructure"
    / "keycloak"
    / "providers"
    / "securescan-email-change"
    / "src"
    / "main"
    / "java"
    / "cloud"
    / "securescan"
    / "keycloak"
    / "emailchange"
    / "SecureScanUpdateEmailActionToken.java"
)
TOKEN_HANDLER_SOURCE = (
    REPO_ROOT
    / "infrastructure"
    / "keycloak"
    / "providers"
    / "securescan-email-change"
    / "src"
    / "main"
    / "java"
    / "cloud"
    / "securescan"
    / "keycloak"
    / "emailchange"
    / "SecureScanUpdateEmailActionTokenHandler.java"
)
ACTION_TOKEN_SERVICE = (
    REPO_ROOT
    / "infrastructure"
    / "keycloak"
    / "providers"
    / "securescan-email-change"
    / "src"
    / "main"
    / "resources"
    / "META-INF"
    / "services"
    / "org.keycloak.authentication.actiontoken.ActionTokenHandlerFactory"
)
PROFILE_EDIT_PAGE = REPO_ROOT / "apps" / "frontend" / "src" / "pages" / "ProfileEditPage.tsx"


def test_provider_keeps_pending_email_without_persistent_update_email_required_action() -> None:
    source = PROVIDER_SOURCE.read_text(encoding="utf-8")

    assert 'SECURESCAN_PENDING_EMAIL_ATTRIBUTE = "securescan.email.pending"' in source
    assert "user.setSingleAttribute(SECURESCAN_PENDING_EMAIL_ATTRIBUTE, newEmail);" in source
    assert "user.removeAttribute(UserModel.EMAIL_PENDING);" in source
    assert "user.removeRequiredAction(UserModel.RequiredAction.UPDATE_EMAIL.name());" in source
    assert "user.removeRequiredAction(UserModel.RequiredAction.VERIFY_EMAIL.name());" in source
    assert "user.addRequiredAction(UserModel.RequiredAction.UPDATE_EMAIL);" not in source
    assert "user.addRequiredAction(UserModel.RequiredAction.VERIFY_EMAIL);" not in source
    assert "user.setEmail(newEmail);" not in source
    assert "user.setEmailVerified(false);" not in source
    assert "sendEmailChangeConfirmation(user, validatedProfile, emailActionContext);" in source


def test_provider_requests_session_logout_after_successful_email_confirmation() -> None:
    source = PROVIDER_SOURCE.read_text(encoding="utf-8")
    token_source = TOKEN_SOURCE.read_text(encoding="utf-8")
    handler_source = TOKEN_HANDLER_SOURCE.read_text(encoding="utf-8")
    action_token_service = ACTION_TOKEN_SERVICE.read_text(encoding="utf-8")

    assert "new SecureScanUpdateEmailActionToken(" in source
    assert "Boolean.TRUE," in source
    assert "emailActionContext.redirectUri()" in source
    assert 'public static final String TOKEN_TYPE = "securescan-update-email";' in token_source
    assert "extends DefaultActionToken" in token_source
    assert "UpdateEmail.updateEmailNow" in handler_source
    assert "user.removeAttribute(SecureScanEmailChangeResource.SECURESCAN_PENDING_EMAIL_ATTRIBUTE);" in handler_source
    assert "AuthenticationManager.backchannelLogout(" in handler_source
    assert "cloud.securescan.keycloak.emailchange.SecureScanUpdateEmailActionTokenHandler" in action_token_service


def test_profile_edit_page_keeps_transient_feedback_auto_dismiss_and_loading_state() -> None:
    source = PROFILE_EDIT_PAGE.read_text(encoding="utf-8")

    assert "type FeedbackState =" in source
    assert "autoHideMs?: number" in source
    assert "window.setTimeout(() => {" in source
    assert "}, feedback.autoHideMs ?? 6000)" in source
    assert "const [passwordFeedback, setPasswordFeedback] = useState<string | null>(null)" in source
    assert "}, 6000)" in source
    assert "autoHideMs: 6000" in source
    assert "CircularProgress" in source
    assert "Salvataggio..." in source
    assert "Nuova email in attesa di verifica:" in source
