<#--
  Pagina "Password dimenticata?".

  Questo template raccoglie username o email e avvia il flow di reset credenziali
  gestito da Keycloak. Non cambia direttamente la password: serve solo a far
  partire l'invio dell'email con il link di reset, se l'account esiste.
-->
<#import "template.ftl" as layout>
<@layout.registrationLayout displayMessage=!messagesPerField.existsError('username') displayInfo=false; section>
  <#if section = "header">
    
  <#elseif section = "form">
    <div class="ssc-auth-shell ssc-auth-shell--login">
      <div class="ssc-auth-card ssc-auth-card--login">
        <div class="ssc-auth-card__header">
          <h1 class="ssc-auth-card__title ssc-auth-card__title--icon">${msg("resetPasswordTitle")}</h1>
          <p class="ssc-auth-card__subtitle">${msg("emailInstruction")}</p>
        </div>

        <form id="kc-reset-password-form" class="ssc-form-stack" action="${url.loginAction}" method="post">
          <div class="ssc-field">
            <label for="username">${msg("usernameOrEmail")}</label>
            <input id="username" name="username" type="text" value="${(auth.attemptedUsername!'')}" autocomplete="username" autofocus required />
            <#if messagesPerField.existsError('username')>
              <span class="ssc-field-error">${kcSanitize(messagesPerField.getFirstError('username'))?no_esc}</span>
            </#if>
          </div>

          <button id="kc-reset-password-submit" class="ssc-submit" type="submit">${msg("doReset")}</button>
          <a class="ssc-inline-link ssc-inline-link--center" href="${url.loginUrl}">${msg("backToLogin")}</a>
        </form>
      </div>
    </div>
  <#elseif section = "info">
    
  </#if>
</@layout.registrationLayout>
