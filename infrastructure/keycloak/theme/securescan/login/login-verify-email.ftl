<#--
  Pagina informativa del flow "Verifica email".

  Keycloak la usa quando deve informare l'utente che la verifica email è stata
  avviata oppure, nelle app-initiated actions, quando può ancora permettere il
  reinvio del messaggio.
-->
<#import "template.ftl" as layout>
<#assign clientLoginDestination = url.loginUrl>
<#if client?? && (client.baseUrl!'')?has_content>
  <#assign clientLoginDestination = client.baseUrl>
</#if>
<@layout.registrationLayout displayMessage=false displayInfo=false; section>
  <#if section = "header">
    
  <#elseif section = "form">
    <div class="ssc-auth-shell ssc-auth-shell--action">
      <div class="ssc-auth-card ssc-info-card ssc-info-card--verify-email">
        <div class="ssc-auth-card__header">
          <span class="ssc-info-card__eyebrow ssc-info-card__eyebrow--teal">${msg("verificationEmailSentEyebrow")}</span>
          <div class="ssc-verify-email-icon" aria-hidden="true">
            <span class="ssc-verify-email-icon__ring"></span>
            <span class="ssc-verify-email-icon__glyph"></span>
            <span class="ssc-verify-email-icon__badge"></span>
          </div>
          <h1 class="ssc-auth-card__title ssc-auth-card__title--centered">${msg("verificationEmailSentTitle")}</h1>
        </div>

        <div class="ssc-info-card__body ssc-info-card__body--verify-email">
          <p class="ssc-info-card__body-lead">${msg("verificationEmailSentLead")}</p>
          <p>${msg("verificationEmailSentBody")}</p>
          <p>${msg("verificationEmailSentHint")}</p>
        </div>

        <div class="ssc-info-card__notice" role="note">
          <span class="ssc-info-card__notice-icon ssc-info-card__notice-icon--mail" aria-hidden="true"></span>
          <div class="ssc-info-card__notice-copy">
            <p>${msg("verificationEmailSentHelpTitle")}</p>
            <p>${msg("verificationEmailSentHelpBody")}</p>
          </div>
        </div>

        <#if isAppInitiatedAction?? && isAppInitiatedAction>
          <form id="kc-verify-email-form" class="ssc-form-stack ssc-form-stack--verify-email" action="${url.loginAction}" method="post">
            <button id="kc-verify-email-submit" class="ssc-submit ssc-submit--full" type="submit">
              <#if verifyEmail??>${msg("emailVerifyResend")}<#else>${msg("emailVerifySend")}</#if>
            </button>
            <button
              class="ssc-submit ssc-submit--full ssc-submit--secondary"
              type="submit"
              name="cancel-aia"
              value="true"
              formnovalidate
            >
              ${msg("doCancel")}
            </button>
          </form>
        <#else>
          <div class="ssc-info-card__actions">
            <a
              class="ssc-info-card__button"
              href="${clientLoginDestination}"
              data-login-url="${url.loginUrl}"
              data-client-login-destination="${clientLoginDestination}"
            >
              ${msg("backToLogin")}
            </a>
          </div>
        </#if>

        <p class="ssc-info-card__footer">
          <span class="ssc-info-card__footer-icon" aria-hidden="true"></span>
          <span>${msg("protectedConnectionLabel")}</span>
        </p>
      </div>
    </div>
  <#elseif section = "info">
    
  </#if>
</@layout.registrationLayout>
