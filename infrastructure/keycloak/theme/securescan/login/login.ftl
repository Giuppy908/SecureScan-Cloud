<#--
  Pagina "Accedi" del theme SecureScan.

  Keycloak mostra questo template quando l'utente deve autenticarsi nel realm
  `securescan`. Il frontend React non replica il form: delega login, sessione,
  credenziali e gestione errori di autenticazione a Keycloak.
-->
<#import "template.ftl" as layout>
<@layout.registrationLayout displayMessage=!messagesPerField.existsError('username','password') displayInfo=false; section>
  <#if section = "header">
    
  <#elseif section = "form">
    <div class="ssc-auth-shell ssc-auth-shell--login">
      <div class="ssc-auth-card ssc-auth-card--login">
        <div class="ssc-auth-card__header">
          <h1 class="ssc-auth-card__title ssc-auth-card__title--icon">${msg("loginTitle")}</h1>
          <p class="ssc-auth-card__subtitle">Accedi al tuo account SecureScan Cloud.</p>
        </div>

        <form id="kc-form-login" class="ssc-form-stack" onsubmit="login.disabled = true; return true;" action="${url.loginAction}" method="post">
          <div class="ssc-field">
            <label for="username">${msg("usernameOrEmail")}</label>
            <input
              id="username"
              name="username"
              type="text"
              value="${(login.username!'')}"
              autocomplete="username"
              autofocus
              aria-invalid="<#if messagesPerField.existsError('username','password')>true</#if>"
              placeholder="${msg("usernameOrEmail")}"
            />
            <#if messagesPerField.existsError('username','password')>
              <span class="ssc-field-error">${kcSanitize(messagesPerField.getFirstError('username','password'))?no_esc}</span>
            </#if>
          </div>

          <div class="ssc-field">
            <label for="password">${msg("password")}</label>
            <div class="ssc-password-field">
              <input
                id="password"
                name="password"
                type="password"
                autocomplete="current-password"
                aria-invalid="<#if messagesPerField.existsError('username','password')>true</#if>"
                placeholder="${msg("password")}"
              />
              <button
                class="ssc-password-toggle"
                type="button"
                data-password-toggle
                data-target="password"
                aria-label="Mostra o nascondi password"
                aria-pressed="false"
              >
                <span class="ssc-password-toggle__icon" aria-hidden="true"></span>
              </button>
            </div>
            <#if realm.resetPasswordAllowed>
              <a class="ssc-inline-link ssc-inline-link--right" href="${url.loginResetCredentialsUrl}">${msg("doForgotPassword")}</a>
            </#if>
          </div>

          <#if realm.rememberMe && !usernameHidden??>
            <label class="ssc-checkbox">
              <input id="rememberMe" name="rememberMe" type="checkbox" <#if login.rememberMe??>checked</#if> />
              <span>${msg("rememberMe")}</span>
            </label>
          </#if>

          <button id="kc-login" class="ssc-submit" name="login" type="submit">${msg("doLogIn")}</button>

          <div class="ssc-auth-footer">
            <span>Non hai ancora un account?</span>
            <#if realm.password && realm.registrationAllowed && !registrationDisabled??>
              <a href="${url.registrationUrl}">${msg("doRegister")}</a>
            </#if>
          </div>
        </form>
      </div>
    </div>
  <#elseif section = "info">
    
  </#if>
</@layout.registrationLayout>
