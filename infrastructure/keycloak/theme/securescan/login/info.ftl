<#--
  Template FreeMarker usato da Keycloak per varie pagine informative.

  I file .ftl sono template HTML renderizzati lato server da Keycloak. Non
  implementano la sicurezza del login in sé, ma personalizzano la presentazione
  dei flow di autenticazione già gestiti dal server.

  In SecureScan Cloud questo template viene riusato soprattutto per:
  - Verifica email: email inviata, verifica in corso, email verificata;
  - Password dimenticata: conferma neutrale dopo la richiesta reset;
  - Password aggiornata: pagina finale stabile dopo il reset completato.

  Il caso "Password aggiornata" è importante: resta volutamente una pagina
  finale senza auto-redirect, così l'utente può leggere la conferma e tornare
  al login soltanto tramite il pulsante "Torna all'accesso".
-->
<#import "template.ftl" as layout>
<#assign summaryText = kcSanitize(message.summary!'')?no_esc>
<#assign summaryLower = (message.summary!'')?lower_case>
<#assign headerLower = (messageHeader!'')?lower_case>
<#assign titleText = (messageHeader!'Informazione')>
<#assign bodyText = summaryText>
<#assign hintText = "">
<#assign eyebrowText = "SecureScan Cloud">
<#assign eyebrowSuccess = false>
<#assign redirectDelay = 0>
<#assign clearSessionBeforeRedirect = false>
<#assign isPasswordResetSuccess = false>
<#assign isVerificationEmailSentSuccess = false>
<#assign isExecuteActionVerifyEmail = false>
<#assign isEmailUpdatedSuccess = false>
<#assign clientLoginDestination = url.loginUrl>
<#if client?? && (client.baseUrl!'')?has_content>
  <#assign clientLoginDestination = client.baseUrl>
</#if>
<#assign redirectUrl = clientLoginDestination>
<#assign linkLabel = msg("backToLogin")>
<#assign pageRedirectTarget = pageRedirectUri!''>

<#if requiredActions?? && requiredActions?size == 1 && requiredActions?seq_contains("VERIFY_EMAIL")>
  <#assign titleText = msg("verificationEmailActionTitle")>
  <#assign bodyText = msg("verificationEmailActionBody")>
  <#assign hintText = msg("verificationEmailActionHint")>
  <#assign eyebrowText = msg("verificationEmailActionEyebrow")>
  <#assign isExecuteActionVerifyEmail = true>
  <#if actionUri?has_content>
    <#assign redirectUrl = actionUri>
    <#assign linkLabel = msg("doContinue")>
  <#elseif pageRedirectTarget?has_content>
    <#assign redirectUrl = pageRedirectTarget>
    <#assign linkLabel = msg("returnToSecureScan")>
  <#else>
    <#assign redirectUrl = clientLoginDestination>
    <#assign linkLabel = msg("returnToSecureScan")>
  </#if>
<#elseif actionUri?has_content
    && (summaryLower?contains("conferma la validità dell'indirizzo email")
      || summaryLower?contains("conferma la validità del tuo indirizzo email")
      || summaryLower?contains("verify the validity of email address")
      || headerLower?contains("verifica dell'indirizzo email")
      || headerLower?contains("verify email"))>
  <#assign titleText = msg("verificationEmailProgressTitle")>
  <#assign bodyText = msg("verificationEmailProgressBody")>
  <#assign hintText = msg("verificationEmailProgressHint")>
  <#assign eyebrowText = "SecureScan Cloud">
  <#assign redirectDelay = 80>
  <#assign redirectUrl = actionUri>
  <#assign linkLabel = msg("doContinue")>
<#elseif headerLower?contains("email di verifica inviata")
    || headerLower?contains("confirmation email sent")
    || summaryLower?contains("confermare il nuovo indirizzo email")
    || summaryLower?contains("confirmation email has been sent")
    || summaryLower?contains("verification email was sent to the new address")>
  <#assign titleText = msg("verificationEmailResentSuccessTitle")>
  <#assign bodyText = msg("verificationEmailResentSuccessBody")>
  <#assign hintText = msg("verificationEmailResentSuccessHint")>
  <#assign eyebrowText = "SecureScan Cloud">
  <#assign eyebrowSuccess = true>
  <#assign isVerificationEmailSentSuccess = true>
<#elseif summaryLower?contains("verificare il tuo indirizzo email")
    || summaryLower?contains("ti è stata inviata una email")
    || summaryLower?contains("ti è stata inviata un''email")
    || summaryLower?contains("email verification")
    || summaryLower?contains("verify your email")
    || headerLower?contains("devi verificare il tuo indirizzo email")
    || headerLower?contains("verify your email")>
  <#assign titleText = msg("verificationEmailResentSuccessTitle")>
  <#assign bodyText = msg("verificationEmailResentSuccessBody")>
  <#assign hintText = msg("verificationEmailResentSuccessHint")>
  <#assign eyebrowText = "SecureScan Cloud">
  <#assign eyebrowSuccess = true>
  <#assign isVerificationEmailSentSuccess = true>
<#elseif summaryLower?contains("indirizzo email è stato verificato")
    || summaryLower?contains("email address has been verified")
    || summaryLower?contains("email verificata")
    || headerLower?contains("email verificata")
    || headerLower?contains("email address has been verified")>
  <#assign titleText = msg("verificationEmailSuccessTitle")>
  <#assign bodyText = msg("verificationEmailSuccessBody")>
  <#assign hintText = msg("verificationEmailSuccessHint") + " " + msg("autoRedirectLoginHint")>
  <#assign eyebrowText = "SecureScan Cloud">
  <#assign eyebrowSuccess = true>
  <#assign redirectDelay = 5000>
  <#assign clearSessionBeforeRedirect = true>
<#elseif headerLower?contains("email aggiornata")
    || summaryLower?contains("nuovo indirizzo email è stato confermato correttamente")
    || summaryLower?contains("new email address has been successfully updated")
    || summaryLower?contains("new email address has been verified and associated")>
  <#assign titleText = msg("emailUpdatedTitle")>
  <#assign bodyText = msg("emailUpdatedSuccessBodyLineOne")>
  <#assign hintText = msg("emailUpdatedSuccessBodyLineTwo")>
  <#assign eyebrowText = "SecureScan Cloud">
  <#assign eyebrowSuccess = true>
  <#assign isEmailUpdatedSuccess = true>
  <#assign redirectUrl = clientLoginDestination>
  <#assign linkLabel = msg("loginToSecureScan")>
<#elseif summaryLower?contains("account has been updated")
    || summaryLower?contains("utente è stato aggiornato")
    || summaryLower?contains("account è stato aggiornato")
    || summaryLower?contains("password aggiornata")
    || summaryLower?contains("password updated")
    || headerLower?contains("accountupdatedtitle")>
  <#-- Questo ramo intercetta il successo del reset password e costruisce la pagina finale stabile. -->
  <#assign titleText = msg("passwordUpdatedSuccessTitle")>
  <#assign bodyText = msg("passwordUpdatedSuccessBody")>
  <#assign hintText = "">
  <#assign eyebrowText = "SecureScan Cloud">
  <#assign eyebrowSuccess = true>
  <#assign isPasswordResetSuccess = true>
<#elseif summaryLower?contains("reimpostare la password")
    || summaryLower?contains("reset your credentials")
    || summaryLower?contains("email with further instructions")>
  <#assign titleText = msg("resetPasswordTitle")>
  <#assign bodyText = msg("passwordResetNeutralNotice")>
  <#assign hintText = msg("autoRedirectLoginHint")>
  <#assign eyebrowText = "Operazione avviata">
  <#assign eyebrowSuccess = true>
  <#assign redirectDelay = 6000>
</#if>

<@layout.registrationLayout displayMessage=false displayInfo=false; section>
  <#if section = "header">
    
  <#elseif section = "form">
    <div class="ssc-auth-shell ssc-auth-shell--action">
      <div class="ssc-auth-card ssc-info-card<#if isPasswordResetSuccess || isVerificationEmailSentSuccess || isEmailUpdatedSuccess> ssc-info-card--success-panel</#if><#if isExecuteActionVerifyEmail> ssc-info-card--verify-email</#if>">
        <#if isExecuteActionVerifyEmail>
          <div class="ssc-auth-card__header">
            <span class="ssc-info-card__eyebrow ssc-info-card__eyebrow--teal">${eyebrowText?upper_case}</span>
            <div class="ssc-verify-email-icon" aria-hidden="true">
              <span class="ssc-verify-email-icon__ring"></span>
              <span class="ssc-verify-email-icon__glyph"></span>
              <span class="ssc-verify-email-icon__badge"></span>
            </div>
            <h1 class="ssc-auth-card__title ssc-auth-card__title--centered">${titleText}</h1>
          </div>

          <div class="ssc-info-card__body ssc-info-card__body--verify-email">
            <p class="ssc-info-card__body-lead">${bodyText}</p>
            <p>${hintText}</p>
          </div>

          <div class="ssc-info-card__notice" role="note">
            <span class="ssc-info-card__notice-icon ssc-info-card__notice-icon--mail" aria-hidden="true"></span>
            <div class="ssc-info-card__notice-copy">
              <p>${msg("verificationEmailActionNoticeTitle")}</p>
              <p>${msg("verificationEmailActionNoticeBody")}</p>
            </div>
          </div>

          <div class="ssc-info-card__actions">
            <a
              class="ssc-info-card__button"
              href="${redirectUrl}"
              data-login-url="${url.loginUrl}"
              data-client-login-destination="${clientLoginDestination}"
            >
              <span>${linkLabel}</span>
            </a>
          </div>

          <p class="ssc-info-card__footer">
            <span class="ssc-info-card__footer-icon" aria-hidden="true"></span>
            <span>${msg("protectedConnectionLabel")}</span>
          </p>
        <#else>
          <div class="ssc-auth-card__header">
            <span class="ssc-info-card__eyebrow<#if eyebrowSuccess> ssc-info-card__eyebrow--success</#if>">${eyebrowText?upper_case}</span>
            <#if isPasswordResetSuccess || isVerificationEmailSentSuccess || isEmailUpdatedSuccess>
            <div class="ssc-success-icon" aria-hidden="true">
              <span class="ssc-success-icon__spark ssc-success-icon__spark--top-left"></span>
              <span class="ssc-success-icon__spark ssc-success-icon__spark--top-right"></span>
              <span class="ssc-success-icon__spark ssc-success-icon__spark--left"></span>
              <span class="ssc-success-icon__spark ssc-success-icon__spark--right"></span>
              <span class="ssc-success-icon__check"></span>
            </div>
            <h1 class="ssc-auth-card__title ssc-auth-card__title--success">${titleText}</h1>
          <#else>
            <h1 class="ssc-auth-card__title ssc-auth-card__title--icon">${titleText}</h1>
          </#if>
          </div>

          <#if isPasswordResetSuccess>
          <#-- Card di conferma finale del flow: nessun timer, nessun redirect automatico. -->
            <div class="ssc-info-card__body ssc-info-card__body--success">
              <p class="ssc-info-card__body-lead">${msg("passwordUpdatedSuccessBodyLineOne")}</p>
              <p>${msg("passwordUpdatedSuccessBodyLineTwo")}</p>
            </div>
            <div class="ssc-info-card__notice" role="note">
              <span class="ssc-info-card__notice-icon" aria-hidden="true"></span>
              <div class="ssc-info-card__notice-copy">
                <p>${msg("passwordUpdatedSuccessNoticeLineOne")}</p>
                <p>${msg("passwordUpdatedSuccessNoticeLineTwo")}</p>
              </div>
            </div>
          <#elseif isVerificationEmailSentSuccess>
          <#-- Variante del pannello di successo riusata per il reinvio verifica email. -->
            <div class="ssc-info-card__body ssc-info-card__body--success">
              <p class="ssc-info-card__body-lead">${bodyText}</p>
              <p>${hintText}</p>
            </div>
            <div class="ssc-info-card__notice" role="note">
              <span class="ssc-info-card__notice-icon ssc-info-card__notice-icon--mail" aria-hidden="true"></span>
              <div class="ssc-info-card__notice-copy">
                <p>${msg("verificationEmailResentSuccessNoticeTitle")}</p>
                <p>${msg("verificationEmailResentSuccessNoticeBody")}</p>
              </div>
            </div>
          <#elseif isEmailUpdatedSuccess>
            <div class="ssc-info-card__body ssc-info-card__body--success">
              <p class="ssc-info-card__body-lead">${bodyText}</p>
              <p>${hintText}</p>
            </div>
            <div class="ssc-info-card__notice" role="note">
              <span class="ssc-info-card__notice-icon" aria-hidden="true"></span>
              <div class="ssc-info-card__notice-copy">
                <p>${msg("emailUpdatedSuccessNoticeLineOne")}</p>
                <p>${msg("emailUpdatedSuccessNoticeLineTwo")}</p>
              </div>
            </div>
          <#else>
            <p class="ssc-info-card__body">${bodyText}</p>
          </#if>
          <#if hintText?has_content && !isPasswordResetSuccess && !isVerificationEmailSentSuccess && !isEmailUpdatedSuccess>
            <p class="ssc-info-card__hint">${hintText}</p>
          </#if>

          <div class="ssc-info-card__actions">
            <a
              class="<#if isPasswordResetSuccess || isVerificationEmailSentSuccess || isEmailUpdatedSuccess>ssc-info-card__button<#else>ssc-inline-link ssc-inline-link--left</#if>"
              href="${redirectUrl}"
              data-login-url="${url.loginUrl}"
              data-client-login-destination="${clientLoginDestination}"
              <#if redirectDelay gt 0>data-auto-redirect-url="${redirectUrl}" data-auto-redirect-delay="${redirectDelay}"</#if>
              <#if clearSessionBeforeRedirect>data-clear-session-before-redirect="true"</#if>
            >
              <span>${linkLabel}</span>
            </a>
          </div>

          <#if isPasswordResetSuccess || isVerificationEmailSentSuccess || isEmailUpdatedSuccess>
            <p class="ssc-info-card__footer">
              <span class="ssc-info-card__footer-icon" aria-hidden="true"></span>
              <span>${msg("protectedConnectionLabel")}</span>
            </p>
          </#if>
        </#if>
      </div>
    </div>
  <#elseif section = "info">
    
  </#if>
</@layout.registrationLayout>
