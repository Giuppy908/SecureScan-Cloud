<#--
  Pagina errore del login theme SecureScan.

  Keycloak usa `error.ftl` per vari errori generici. In SecureScan Cloud
  personalizziamo soltanto il caso in cui l'utente apre un action token
  sensibile (per esempio verifica email) mentre nel browser è già presente una
  sessione autenticata con un altro account.

  Il controllo di sicurezza resta quello nativo di Keycloak: qui cambiamo solo
  la presentazione visuale del ramo "sessione già attiva". Tutti gli altri
  errori continuano a usare il fallback minimale compatibile con il template
  base.
-->
<#import "template.ftl" as layout>
<#assign summaryText = kcSanitize(message.summary!'')?no_esc>
<#assign summaryLower = (message.summary!'')?lower_case>
<#assign isAlreadyAuthenticatedState = summaryLower?contains("hai già effettuato l'accesso con un altro account")
  || summaryLower?contains("sei già autenticato con l'utente")
  || summaryLower?contains("you are already authenticated as different user")
  || summaryLower?contains("you are already logged in")>
<#assign isExpiredVerifyEmailState = summaryLower?contains("azione è scaduta")
  || summaryLower?contains("action expired")
  || summaryLower?contains("stale link")
  || summaryLower?contains("no longer valid")
  || summaryLower?contains("email verification has been cancelled")>

<@layout.registrationLayout displayMessage=false displayInfo=false; section>
<#if section = "header">
    <#if !isAlreadyAuthenticatedState && !isExpiredVerifyEmailState>
      ${kcSanitize(msg("errorTitle"))?no_esc}
    </#if>
  <#elseif section = "form">
    <#if isAlreadyAuthenticatedState>
      <div class="ssc-auth-shell ssc-auth-shell--action">
        <div class="ssc-auth-card ssc-info-card ssc-info-card--session-state">
          <div class="ssc-auth-card__header">
            <div class="ssc-session-state-icon" aria-hidden="true">
              <span class="ssc-session-state-icon__ring"></span>
              <span class="ssc-session-state-icon__glyph"></span>
              <span class="ssc-session-state-icon__badge ssc-session-state-icon__badge--shield"></span>
            </div>
            <h1 class="ssc-auth-card__title ssc-auth-card__title--centered">${msg("alreadyAuthenticatedTitle")}</h1>
          </div>

          <div class="ssc-info-card__body ssc-info-card__body--session-state">
            <p class="ssc-info-card__body-lead">${msg("alreadyAuthenticatedLead")}</p>
          </div>

          <div class="ssc-info-card__notice" role="note">
            <span class="ssc-info-card__notice-icon ssc-info-card__notice-icon--shield" aria-hidden="true"></span>
            <div class="ssc-info-card__notice-copy">
              <p>${msg("alreadyAuthenticatedNoticeTitle")}</p>
              <p>${msg("alreadyAuthenticatedNoticeBody")}</p>
            </div>
          </div>

          <#if skipLink??>
          <#else>
            <#if client?? && client.baseUrl?has_content>
              <div class="ssc-info-card__actions">
                <a
                  id="backToApplication"
                  class="ssc-info-card__button"
                  href="${client.baseUrl}"
                >
                  <span>${msg("returnToSecureScan")}</span>
                </a>
              </div>
            </#if>
          </#if>

          <p class="ssc-info-card__footer">
            <span class="ssc-info-card__footer-icon" aria-hidden="true"></span>
            <span>${msg("protectedConnectionLabel")}</span>
          </p>
        </div>
      </div>
    <#elseif isExpiredVerifyEmailState>
      <div class="ssc-auth-shell ssc-auth-shell--action">
        <div class="ssc-auth-card ssc-info-card ssc-info-card--session-state">
          <div class="ssc-auth-card__header">
            <div class="ssc-session-state-icon" aria-hidden="true">
              <span class="ssc-session-state-icon__ring"></span>
              <span class="ssc-session-state-icon__glyph"></span>
              <span class="ssc-session-state-icon__badge ssc-session-state-icon__badge--alert"></span>
            </div>
            <h1 class="ssc-auth-card__title ssc-auth-card__title--centered">${msg("expiredVerifyEmailTitle")}</h1>
          </div>

          <div class="ssc-info-card__body ssc-info-card__body--session-state">
            <p class="ssc-info-card__body-lead">${msg("expiredVerifyEmailLead")}</p>
          </div>

          <div class="ssc-info-card__notice" role="note">
            <span class="ssc-info-card__notice-icon" aria-hidden="true"></span>
            <div class="ssc-info-card__notice-copy">
              <p>${msg("expiredVerifyEmailNoticeTitle")}</p>
              <p>${msg("expiredVerifyEmailNoticeBody")}</p>
            </div>
          </div>

          <#if skipLink??>
          <#else>
            <#if client?? && client.baseUrl?has_content>
              <div class="ssc-info-card__actions">
                <a
                  id="backToApplication"
                  class="ssc-info-card__button"
                  href="${client.baseUrl}"
                >
                  <span>${msg("returnToSecureScan")}</span>
                </a>
              </div>
            </#if>
          </#if>

          <p class="ssc-info-card__footer">
            <span class="ssc-info-card__footer-icon" aria-hidden="true"></span>
            <span>${msg("protectedConnectionLabel")}</span>
          </p>
        </div>
      </div>
    <#else>
      <div id="kc-error-message">
        <p class="instruction">${summaryText}</p>
        <#if traceId??>
          <p class="instruction" id="traceId">${msg("traceIdSupportMessage", traceId)}</p>
        </#if>
        <#if skipLink??>
        <#else>
          <#if client?? && client.baseUrl?has_content>
            <p><a id="backToApplication" href="${client.baseUrl}">${msg("backToApplication")}</a></p>
          </#if>
        </#if>
      </div>
    </#if>
  </#if>
</@layout.registrationLayout>
