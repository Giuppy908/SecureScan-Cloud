<#--
  Pagina Keycloak per il cambio email di un account già esistente.

  A differenza della registrazione iniziale, questo flow non deve trasformare
  l'utente in un "nuovo registrato" non ancora valido. Keycloak 26.7.0 gestisce
  qui il workflow nativo UPDATE_EMAIL: la nuova email resta pending finché il
  link ricevuto non viene confermato.
-->
<#import "template.ftl" as layout>
<#import "user-profile-commons.ftl" as userProfileCommons>
<#assign summaryText = kcSanitize(message.summary!'')?no_esc>
<#assign hasSummaryMessage = (message.summary!'')?has_content>
<#assign summaryLower = (message.summary!'')?lower_case>
<#assign isPendingVerificationState = summaryLower?contains("già inviato un link di verifica")
  || summaryLower?contains("already sent a verification email")
  || summaryLower?contains("verification email was sent to the new address")>

<@layout.registrationLayout displayMessage=false displayInfo=false displayRequiredFields=false; section>
  <#if section = "header">

  <#elseif section = "form">
    <div class="ssc-auth-shell ssc-auth-shell--action">
      <div class="ssc-auth-card">
        <div class="ssc-auth-card__header">
          <h1 class="ssc-auth-card__title ssc-auth-card__title--icon">${msg("updateEmailActionTitle")}</h1>
          <p class="ssc-auth-card__subtitle">
            <#if isPendingVerificationState>
              ${msg("updateEmailActionPendingSubtitle")}
            <#else>
              ${msg("updateEmailActionSubtitle")}
            </#if>
          </p>
        </div>

        <#if hasSummaryMessage>
          <div class="ssc-info-card__notice" role="note">
            <span class="ssc-info-card__notice-icon ssc-info-card__notice-icon--mail" aria-hidden="true"></span>
            <div class="ssc-info-card__notice-copy">
              <p>
                <#if isPendingVerificationState>
                  ${msg("updateEmailActionPendingNoticeTitle")}
                <#else>
                  ${msg("updateEmailActionNoticeTitle")}
                </#if>
              </p>
              <p>${summaryText}</p>
            </div>
          </div>
        <#else>
          <div class="ssc-info-card__notice" role="note">
            <span class="ssc-info-card__notice-icon ssc-info-card__notice-icon--mail" aria-hidden="true"></span>
            <div class="ssc-info-card__notice-copy">
              <p>${msg("updateEmailActionNoticeTitle")}</p>
              <p>${msg("updateEmailActionNoticeBody")}</p>
            </div>
          </div>
        </#if>

        <form id="kc-update-email-form" class="ssc-form-grid ssc-form-grid--compact" action="${url.loginAction}" method="post">
          <@userProfileCommons.userProfileFormFields/>

          <div id="kc-form-buttons" class="ssc-form-grid__actions">
            <#if isAppInitiatedAction??>
              <input class="ssc-submit ssc-submit--full" type="submit" value="${msg("doSubmit")}" />
              <button class="ssc-submit ssc-submit--full" type="submit" name="cancel-aia" value="true">${msg("doCancel")}</button>
            <#else>
              <input class="ssc-submit ssc-submit--full" type="submit" value="${msg("doSubmit")}" />
            </#if>
          </div>
        </form>
      </div>
    </div>
  <#elseif section = "info">

  </#if>
</@layout.registrationLayout>
