"""Test statici sul theme Keycloak SecureScan Cloud.

Questa suite protegge i flow di autenticazione visibili all'utente:
registrazione, verifica email, login e reset password. I test restano statici,
ma impediscono di introdurre facilmente regressioni nei template del theme.
"""

from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
KEYCLOAK_THEME_DIR = REPO_ROOT / "infrastructure" / "keycloak" / "theme" / "securescan" / "login"
KEYCLOAK_EMAIL_THEME_DIR = REPO_ROOT / "infrastructure" / "keycloak" / "theme" / "securescan" / "email"


def _read_theme_file(name: str) -> str:
    """Legge un file del theme login dal repository per asserzioni statiche."""
    return (KEYCLOAK_THEME_DIR / name).read_text(encoding="utf-8")


def _read_email_theme_file(name: str) -> str:
    """Legge un file del theme email dal repository per asserzioni statiche."""
    return (KEYCLOAK_EMAIL_THEME_DIR / name).read_text(encoding="utf-8")


def test_info_template_recognizes_runtime_post_registration_messages() -> None:
    template = _read_theme_file("info.ftl")

    assert 'headerLower?contains("devi verificare il tuo indirizzo email")' in template
    assert 'summaryLower?contains("ti è stata inviata una email")' in template
    assert 'data-auto-redirect-delay="${redirectDelay}"' in template


def test_info_template_personalizes_execute_actions_verify_email_via_required_actions() -> None:
    template = _read_theme_file("info.ftl")
    messages = _read_theme_file("messages/messages_it.properties")

    assert 'requiredActions?? && requiredActions?size == 1 && requiredActions?seq_contains("VERIFY_EMAIL")' in template
    execute_verify_branch = template.split('<#if requiredActions?? && requiredActions?size == 1 && requiredActions?seq_contains("VERIFY_EMAIL")>', 1)[1]
    execute_verify_branch = execute_verify_branch.split('<#elseif actionUri?has_content', 1)[0]

    assert '<#assign titleText = msg("verificationEmailActionTitle")>' in execute_verify_branch
    assert '<#assign bodyText = msg("verificationEmailActionBody")>' in execute_verify_branch
    assert '<#assign hintText = msg("verificationEmailActionHint")>' in execute_verify_branch
    assert '<#assign eyebrowText = msg("verificationEmailActionEyebrow")>' in execute_verify_branch
    assert '<#assign isExecuteActionVerifyEmail = true>' in execute_verify_branch
    assert '<#if actionUri?has_content>' in execute_verify_branch
    assert '<#assign redirectUrl = actionUri>' in execute_verify_branch
    assert '<#assign linkLabel = msg("doContinue")>' in execute_verify_branch
    assert '<#elseif pageRedirectTarget?has_content>' in execute_verify_branch
    assert '<#assign redirectUrl = pageRedirectTarget>' in execute_verify_branch
    assert 'summaryLower?contains("verify your email")' not in execute_verify_branch
    assert "verificationEmailActionTitle=Verifica il tuo indirizzo email" in messages
    assert "verificationEmailActionBody=Per completare la verifica del nuovo indirizzo email, conferma l''operazione tramite il pulsante seguente." in messages
    assert "verificationEmailActionHint=Al termine potrai tornare direttamente a SecureScan Cloud e continuare a usare il tuo account." in messages
    assert "verificationEmailActionNoticeTitle=Non hai ricevuto l''email?" in messages
    assert "verificationEmailActionNoticeBody=Controlla anche la cartella spam o posta indesiderata." in messages


def test_verify_email_template_has_dedicated_post_registration_layout_without_auto_redirect() -> None:
    template = _read_theme_file("login-verify-email.ftl")
    messages = _read_theme_file("messages/messages_it.properties")

    assert '<#assign clientLoginDestination = client.baseUrl>' in template
    assert 'ssc-info-card--verify-email' in template
    assert 'ssc-verify-email-icon' in template
    assert '${msg("verificationEmailSentHelpTitle")}' in template
    assert '${msg("verificationEmailSentHelpBody")}' in template
    assert 'ssc-info-card__button' in template
    assert '${msg("backToLogin")}' in template
    assert "Per continuare" not in template
    assert "verificationEmailSentStepsTitle" not in template
    assert "verificationEmailSentStepOne" not in template
    assert "verificationEmailSentStepTwo" not in template
    assert "verificationEmailSentStepThree" not in template
    assert 'data-auto-redirect-url="${clientLoginDestination}"' not in template
    assert 'data-auto-redirect-delay="6000"' not in template
    assert 'data-clear-session-before-redirect="true"' not in template
    assert "verificationEmailSentLead=La registrazione è quasi completata" in messages
    assert "verificationEmailSentHelpTitle=Non hai ricevuto l''email?" in messages


def test_info_template_clears_session_before_redirect_for_registration_and_verification_success() -> None:
    template = _read_theme_file("info.ftl")

    assert '<#assign clearSessionBeforeRedirect = true>' in template
    assert 'data-clear-session-before-redirect="true"' in template
    assert '<#assign redirectUrl = clientLoginDestination>' in template
    assert 'data-login-url="${url.loginUrl}"' in template
    assert 'data-client-login-destination="${clientLoginDestination}"' in template


def test_info_template_handles_email_verification_confirmation_without_profile_redirect() -> None:
    template = _read_theme_file("info.ftl")

    assert 'actionUri?has_content' in template
    assert 'redirectUrl = actionUri' in template
    assert 'summaryLower?contains("conferma la validità dell\'indirizzo email")' in template
    assert '<#assign linkLabel = msg("doContinue")>' in template
    assert '${linkLabel}' in template
    assert "/profile" not in template


def test_info_template_does_not_intentionally_redirect_to_profile() -> None:
    template = _read_theme_file("info.ftl")
    script = _read_theme_file("resources/js/auth-theme.js")

    assert "/profile" not in template
    assert "/profile" not in script
    assert "post_logout_redirect_uri" in script
    assert 'data-client-login-destination' in script
    assert "parsedLoginUrl.toString()" not in script


def test_logout_redirect_uses_client_destination_instead_of_keycloak_login_url() -> None:
    script = _read_theme_file("resources/js/auth-theme.js")

    assert 'getClientLoginDestination(loginUrl, explicitDestination)' in script
    assert 'redirectNode.getAttribute("data-client-login-destination")' in script
    assert 'post_logout_redirect_uri' in script


def test_info_template_contains_email_verified_success_copy() -> None:
    messages = _read_theme_file("messages/messages_it.properties")

    assert "verificationEmailSuccessTitle=Email verificata" in messages
    assert "verificationEmailSuccessBody=L''indirizzo email associato all''account è stato verificato con successo" in messages
    assert "verificationEmailSuccessHint=Puoi ora accedere al tuo account" in messages


def test_info_template_reuses_success_panel_for_verification_email_resend_without_redirect() -> None:
    template = _read_theme_file("info.ftl")
    messages = _read_theme_file("messages/messages_it.properties")

    resend_branch = template.split('<#elseif summaryLower?contains("verificare il tuo indirizzo email")', 1)[1]
    resend_branch = resend_branch.split('<#elseif summaryLower?contains("indirizzo email è stato verificato")', 1)[0]

    assert '<#assign titleText = msg("verificationEmailResentSuccessTitle")>' in resend_branch
    assert '<#assign bodyText = msg("verificationEmailResentSuccessBody")>' in resend_branch
    assert '<#assign hintText = msg("verificationEmailResentSuccessHint")>' in resend_branch
    assert '<#assign eyebrowSuccess = true>' in resend_branch
    assert '<#assign isVerificationEmailSentSuccess = true>' in resend_branch
    assert "redirectDelay = 6000" not in resend_branch
    assert "clearSessionBeforeRedirect = true" not in resend_branch
    assert 'ssc-info-card--success-panel' in template
    assert 'ssc-success-icon__spark' in template
    assert 'ssc-info-card__notice-icon--mail' in template
    assert "verificationEmailResentSuccessTitle=Email di verifica inviata" in messages
    assert "verificationEmailResentSuccessBody=Abbiamo inviato un link di verifica al nuovo indirizzo email associato all''account." not in messages
    assert "verificationEmailResentSuccessBody=Abbiamo inviato un link di verifica al nuovo indirizzo email associato al tuo account." in messages
    assert "verificationEmailResentSuccessHint=Apri il messaggio ricevuto e segui le istruzioni per confermare il nuovo indirizzo email." in messages
    assert "verificationEmailResentSuccessNoticeTitle=Non hai ricevuto l''email?" in messages
    assert "verificationEmailResentSuccessNoticeBody=Controlla anche la cartella spam o posta indesiderata." in messages
    assert "emailUpdateConfirmationSentTitle=Email di verifica inviata" in messages
    assert "emailUpdateConfirmationSent=Abbiamo inviato un link di verifica al nuovo indirizzo email {0}. Apri il messaggio e segui le istruzioni per confermarlo." in messages


def test_update_email_template_uses_dedicated_secure_scan_layout() -> None:
    template = _read_theme_file("update-email.ftl")
    messages = _read_theme_file("messages/messages_it.properties")

    assert 'id="kc-update-email-form"' in template
    assert 'ssc-auth-shell ssc-auth-shell--action' in template
    assert 'ssc-auth-card__title ssc-auth-card__title--icon' in template
    assert 'msg("updateEmailActionTitle")' in template
    assert 'msg("updateEmailActionSubtitle")' in template
    assert 'msg("updateEmailActionPendingSubtitle")' in template
    assert 'msg("updateEmailActionNoticeTitle")' in template
    assert 'msg("updateEmailActionPendingNoticeTitle")' in template
    assert '<@userProfileCommons.userProfileFormFields/>' in template
    assert 'displayRequiredFields=false' in template
    assert '<#import "password-commons.ftl" as passwordCommons>' not in template
    assert '<@passwordCommons.logoutOtherSessions/>' not in template
    assert "Campi obbligatori" not in template
    assert "Scollegati da tutti gli altri dispositivi" not in template
    assert "updateEmailActionTitle=Aggiorna email" in messages
    assert "updateEmailActionNoticeBody=Il nuovo indirizzo diventerà effettivo solo dopo la conferma tramite il link ricevuto." in messages
    assert "emailVerificationPending=Abbiamo già inviato un link di verifica al nuovo indirizzo email {0}. Puoi inserirne un altro oppure chiedere un nuovo invio." in messages


def test_info_template_reuses_success_panel_for_email_updated_confirmation_without_summary_leak() -> None:
    template = _read_theme_file("info.ftl")
    messages = _read_theme_file("messages/messages_it.properties")

    assert 'isEmailUpdatedSuccess = true' in template
    assert 'summaryLower?contains("nuovo indirizzo email è stato confermato correttamente")' in template
    assert '<#assign linkLabel = msg("loginToSecureScan")>' in template

    email_updated_branch = template.split('<#elseif headerLower?contains("email aggiornata")', 1)[1]
    email_updated_branch = email_updated_branch.split('<#elseif summaryLower?contains("account has been updated")', 1)[0]
    assert '${summaryText}' not in email_updated_branch

    success_panel_branch = template.split('<#elseif isEmailUpdatedSuccess>', 1)[1].split('<#else>', 1)[0]
    assert '${msg("emailUpdatedSuccessNoticeLineOne")}' in success_panel_branch
    assert '${msg("emailUpdatedSuccessNoticeLineTwo")}' in success_panel_branch
    assert 'ssc-info-card__body--success' in success_panel_branch
    assert 'ssc-info-card__notice' in success_panel_branch

    assert "emailUpdatedSuccessBodyLineOne=Il nuovo indirizzo email è stato verificato e associato correttamente al tuo account." in messages
    assert "emailUpdatedSuccessBodyLineTwo=Da questo momento SecureScan Cloud utilizzerà il nuovo indirizzo." in messages
    assert "emailUpdatedSuccessNoticeLineOne=Sessioni aggiornate" in messages
    assert "emailUpdatedSuccessNoticeLineTwo=Per proteggere il tuo account abbiamo chiuso le sessioni attive. Accedi nuovamente per continuare." in messages
    assert "loginToSecureScan=Accedi a SecureScan" in messages


def test_email_update_confirmation_email_uses_dedicated_cta_without_visible_raw_url() -> None:
    email_theme_properties = _read_email_theme_file("theme.properties")
    email_messages = _read_email_theme_file("messages/messages_it.properties")
    html_template = _read_email_theme_file("html/email-update-confirmation.ftl")
    text_template = _read_email_theme_file("text/email-update-confirmation.ftl")

    assert "parent=base" in email_theme_properties
    assert "emailUpdateConfirmationSubject=Verifica il nuovo indirizzo email di SecureScan Cloud" in email_messages
    assert "emailUpdateConfirmationExpiryTitle=Scadenza del link" in email_messages
    assert '${msg("emailUpdateConfirmationCta")}' in html_template
    assert 'href="${link}"' in html_template
    assert '>${link}<' not in html_template
    assert "SecureScan Cloud" in html_template
    assert '${msg("emailUpdateConfirmationIgnore")}' in html_template
    assert "stopwatch.png" not in html_template
    assert '<img ' not in html_template
    assert 'border-right:1px solid rgba(143,211,220,0.14);' not in html_template
    assert "${link}" in text_template
    assert '${msg("emailUpdateConfirmationPlainTextAction")}' in text_template


def test_registration_verification_email_uses_secure_scan_layout_and_updated_italian_copy() -> None:
    email_messages = _read_email_theme_file("messages/messages_it.properties")
    html_template = _read_email_theme_file("html/email-verification.ftl")
    text_template = _read_email_theme_file("text/email-verification.ftl")

    assert "emailVerificationSubject=Completa la registrazione a SecureScan Cloud" in email_messages
    assert "emailVerificationHeading=Completa la registrazione" in email_messages
    assert "emailVerificationCta=Verifica il mio account" in email_messages
    assert "emailVerificationExpiry=Questo link resterà valido per {0}." in email_messages
    assert 'href="${link}"' in html_template
    assert '>${link}<' not in html_template
    assert "stopwatch.png" not in html_template
    assert '<img ' not in html_template
    assert 'border-right:1px solid rgba(143,211,220,0.14);' not in html_template
    assert '${msg("emailVerificationExpiry", linkExpirationFormatter(linkExpiration))}' in html_template
    assert '${msg("emailVerificationIgnore")}' in html_template
    assert "${link}" in text_template
    assert '${msg("emailVerificationPlainTextExpiry", linkExpirationFormatter(linkExpiration))}' in text_template
    assert '${msg("emailVerificationPlainTextAction")}' in text_template


def test_password_reset_email_uses_secure_scan_layout_and_dedicated_copy() -> None:
    email_messages = _read_email_theme_file("messages/messages_it.properties")
    html_template = _read_email_theme_file("html/password-reset.ftl")
    text_template = _read_email_theme_file("text/password-reset.ftl")

    assert "passwordResetSubject=Reimposta la password di SecureScan Cloud" in email_messages
    assert "passwordResetHeading=Reimposta la password" in email_messages
    assert "passwordResetCta=Reimposta password" in email_messages
    assert "passwordResetExpiry=Questo link resterà valido per {0}." in email_messages
    assert 'href="${link}"' in html_template
    assert '>${link}<' not in html_template
    assert "stopwatch.png" not in html_template
    assert '<img ' not in html_template
    assert 'border-right:1px solid rgba(143,211,220,0.14);' not in html_template
    assert '${msg("passwordResetExpiry", linkExpirationFormatter(linkExpiration))}' in html_template
    assert '${msg("passwordResetIgnore")}' in html_template
    assert "${link}" in text_template
    assert '${msg("passwordResetPlainTextExpiry", linkExpirationFormatter(linkExpiration))}' in text_template
    assert '${msg("passwordResetPlainTextAction")}' in text_template


def test_email_theme_keeps_update_email_template_isolated_from_registration_and_reset_templates() -> None:
    update_html_template = _read_email_theme_file("html/email-update-confirmation.ftl")
    registration_html_template = _read_email_theme_file("html/email-verification.ftl")
    reset_html_template = _read_email_theme_file("html/password-reset.ftl")
    email_messages = _read_email_theme_file("messages/messages_it.properties")

    assert '${msg("emailUpdateConfirmationCta")}' in update_html_template
    assert '${msg("emailVerificationCta")}' not in update_html_template
    assert '${msg("passwordResetCta")}' not in update_html_template
    assert '${msg("emailVerificationCta")}' in registration_html_template
    assert '${msg("passwordResetCta")}' in reset_html_template
    assert "executeActions" not in reset_html_template
    assert "emailVerificationSubject=Completa la registrazione a SecureScan Cloud" in email_messages
    assert "passwordResetSubject=Reimposta la password di SecureScan Cloud" in email_messages


def test_email_theme_uses_consistent_expiry_box_without_icon_in_all_three_html_templates() -> None:
    update_html_template = _read_email_theme_file("html/email-update-confirmation.ftl")
    registration_html_template = _read_email_theme_file("html/email-verification.ftl")
    reset_html_template = _read_email_theme_file("html/password-reset.ftl")

    expected_boxes = [
        ('${msg("emailUpdateConfirmationExpiryTitle")}', '${msg("emailUpdateConfirmationExpiry", linkExpirationFormatter(linkExpiration))}'),
        ('${msg("emailVerificationExpiryTitle")}', '${msg("emailVerificationExpiry", linkExpirationFormatter(linkExpiration))}'),
        ('${msg("passwordResetExpiryTitle")}', '${msg("passwordResetExpiry", linkExpirationFormatter(linkExpiration))}'),
    ]

    for template, (title_marker, body_marker) in zip(
        [update_html_template, registration_html_template, reset_html_template],
        expected_boxes,
    ):
        assert title_marker in template
        assert body_marker in template
        assert "stopwatch.png" not in template
        assert '<img ' not in template
        assert '<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%">' not in template


def test_error_template_personalizes_only_already_authenticated_state() -> None:
    template = _read_theme_file("error.ftl")
    messages = _read_theme_file("messages/messages_it.properties")

    assert 'summaryLower?contains("sei già autenticato con l\'utente")' in template
    assert 'summaryLower?contains("you are already authenticated as different user")' in template
    assert 'ssc-info-card--session-state' in template
    assert 'ssc-session-state-icon' in template
    assert '${msg("alreadyAuthenticatedTitle")}' in template
    assert '${msg("alreadyAuthenticatedLead")}' in template
    assert '${msg("returnToSecureScan")}' in template
    personalized_branch = template.split('<#if isAlreadyAuthenticatedState>', 1)[1].split('<#else>', 1)[0]
    assert '${summaryText}' not in personalized_branch
    assert 'id="backToApplication"' in template
    assert '${msg("backToApplication")}' in template
    assert '${msg("alreadyAuthenticatedEyebrow")}' not in personalized_branch
    assert 'ssc-info-card__notice-icon--shield' in template
    assert 'ssc-session-state-icon__badge--shield' in template
    assert "alreadyAuthenticatedTitle=Sessione già attiva" in messages
    assert "alreadyAuthenticatedLead=Nel browser è già presente una sessione autenticata." in messages
    assert "alreadyAuthenticatedNoticeBody=Per motivi di sicurezza, torna a SecureScan, esci dalla sessione corrente e riapri il link di verifica." in messages
    assert "returnToSecureScan=Torna a SecureScan" in messages
    assert "differentUserAuthenticated=Hai già effettuato l''accesso con un altro account in questa sessione ({0}). Per completare questa operazione devi prima uscire dalla sessione attualmente attiva." in messages
    assert "alreadyLoggedIn=Hai già una sessione attiva. Per completare questa operazione devi prima uscire e poi riprovare." in messages


def test_error_template_personalizes_expired_verify_email_state() -> None:
    template = _read_theme_file("error.ftl")
    messages = _read_theme_file("messages/messages_it.properties")

    assert 'summaryLower?contains("azione è scaduta")' in template
    assert 'ssc-session-state-icon__badge--alert' in template
    expired_branch = template.split('<#elseif isExpiredVerifyEmailState>', 1)[1].split('<#if skipLink??>', 1)[0]
    assert '${msg("expiredVerifyEmailTitle")}' in expired_branch
    assert '${msg("expiredVerifyEmailLead")}' in expired_branch
    assert '${summaryText}' not in expired_branch
    assert '${msg("returnToSecureScan")}' in template
    assert '${msg("protectedConnectionLabel")}' in template
    assert "expiredVerifyEmailTitle=Link non più valido" in messages
    assert "expiredVerifyEmailNoticeBody=Torna a SecureScan e avvia nuovamente il flusso di verifica dell''indirizzo email." in messages


def test_login_messages_override_password_reset_request_banner_copy() -> None:
    messages = _read_theme_file("messages/messages_it.properties")

    assert "emailSentMessage=Riceverai a breve una email con maggiori dettagli" in messages
    assert "emailSentMessage=Riceverai a breve una email con maggiori istruzioni." not in messages


def test_login_template_does_not_contain_verify_email_residual_blocks() -> None:
    template = _read_theme_file("login.ftl")

    assert "backToLogin" not in template
    assert "emailVerify" not in template


def test_update_password_template_keeps_secure_scan_reset_copy() -> None:
    template = _read_theme_file("login-update-password.ftl")

    assert '${msg("resetPasswordActionTitle")}' in template
    assert '${msg("resetPasswordActionSubtitle")}' in template
    assert '${msg("doReset")}' in template
    assert "ssc-form-grid--password-reset" in template
    assert "Devi cambiare la password" not in template


def test_info_template_keeps_password_reset_success_page_stable() -> None:
    template = _read_theme_file("info.ftl")
    messages = _read_theme_file("messages/messages_it.properties")

    password_success_branch = template.split('<#elseif summaryLower?contains("account has been updated")', 1)[1]
    password_success_branch = password_success_branch.split('<#elseif summaryLower?contains("reimpostare la password")', 1)[0]

    assert '<#assign hintText = "">' in password_success_branch
    assert 'msg("autoRedirectLoginHint")' not in password_success_branch
    assert "redirectDelay = 5000" not in password_success_branch
    assert "clearSessionBeforeRedirect = true" not in password_success_branch
    assert 'ssc-info-card--success-panel' in template
    assert 'ssc-info-card__button' in template
    assert 'ssc-info-card__footer' in template
    assert 'ssc-info-card__notice' in template
    assert 'ssc-success-icon__spark' in template
    assert "passwordUpdatedSuccessBodyLineOne=La password del tuo account è stata aggiornata correttamente." in messages
    assert "passwordUpdatedSuccessBodyLineTwo=Puoi ora accedere con la tua nuova password in totale sicurezza." in messages
    assert "passwordUpdatedSuccessNoticeLineOne=Per motivi di sicurezza, ti invitiamo ad accedere nuovamente." in messages
    assert "passwordUpdatedSuccessNoticeLineTwo=Questa pagina rimarrà disponibile fino a quando non sceglierai di proseguire." in messages
    assert "protectedConnectionLabel=Connessione protetta" in messages


def test_register_template_marks_inline_errors_for_scoped_auto_dismiss() -> None:
    template = _read_theme_file("register.ftl")

    assert 'data-inline-error-dismiss-delay="5000"' in template
    assert "data-inline-field-error" in template


def test_auth_theme_scopes_inline_error_auto_dismiss_to_registration_form_only() -> None:
    script = _read_theme_file("resources/js/auth-theme.js")

    assert 'const registerForm = document.querySelector("#kc-register-form[data-inline-error-dismiss-delay]");' in script
    assert 'registerForm.querySelectorAll("[data-inline-field-error]")' in script
    assert 'scheduleVisualDismiss(errorNode, dismissDelay, "ssc-field-error--dismissing");' in script
    assert 'window.location.assign(finalRedirectUrl);' in script


def test_login_styles_include_verify_email_variant_and_inline_error_fade_class() -> None:
    styles = _read_theme_file("resources/css/login.css")

    assert ".ssc-field-error--dismissing" in styles
    assert ".ssc-info-card--verify-email" in styles
    assert ".ssc-info-card--session-state" in styles
    assert ".ssc-session-state-icon" in styles
    assert ".ssc-session-state-icon__badge--shield" in styles
    assert ".ssc-session-state-icon__badge--alert" in styles
    assert ".ssc-info-card__notice-icon--shield" in styles
    assert ".ssc-verify-email-icon" in styles
    assert ".ssc-info-card__notice" in styles
    assert ".ssc-info-card__steps" not in styles


def test_password_reset_spacing_styles_are_scoped_to_update_password_form() -> None:
    styles = _read_theme_file("resources/css/login.css")

    assert ".ssc-form-grid--password-reset .ssc-field__messages" in styles
    assert ".ssc-form-grid--password-reset .ssc-password-policy--compact" in styles
    assert ".ssc-info-card--success-panel .ssc-auth-card__header" in styles
    assert ".ssc-success-icon" in styles
    assert ".ssc-success-icon__spark" in styles
    assert ".ssc-info-card__button" in styles
    assert ".ssc-info-card__notice" in styles


def test_registration_template_still_uses_password_source_marker_for_policy_feedback() -> None:
    template = _read_theme_file("register.ftl")

    assert "data-password-source" in template
    assert "Da 8 a 24 caratteri" in template
    assert "Almeno una lettera maiuscola (A-Z)" in template
    assert "Almeno una lettera minuscola (a-z)" in template


def test_theme_properties_registers_auth_theme_script() -> None:
    template = _read_theme_file("theme.properties")

    assert "scripts=js/auth-theme.js" in template
