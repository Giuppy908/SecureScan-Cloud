<#--
  Pagina "Reimposta password" mostrata dopo il click sul link email.

  È diversa dalla semplice richiesta "Password dimenticata?": qui l'utente è già
  entrato nel flow corretto e può impostare nuova password e conferma. La
  validazione finale resta di Keycloak; il template personalizza solo la resa
  grafica del modulo e del box "Requisiti password".
-->
<#import "template.ftl" as layout>
<@layout.registrationLayout displayMessage=false displayInfo=false; section>
  <#if section = "header">
    
  <#elseif section = "form">
    <div class="ssc-auth-shell ssc-auth-shell--action">
      <div class="ssc-auth-card">
        <div class="ssc-auth-card__header">
          <h1 class="ssc-auth-card__title ssc-auth-card__title--icon">${msg("resetPasswordActionTitle")}</h1>
          <p class="ssc-auth-card__subtitle">${msg("resetPasswordActionSubtitle")}</p>
        </div>

        <form id="kc-passwd-update-form" class="ssc-form-grid ssc-form-grid--compact ssc-form-grid--password-reset" action="${url.loginAction}" method="post">
          <div class="ssc-field">
            <label for="password-new">${msg("passwordNew")}</label>
            <div class="ssc-password-field">
              <input id="password-new" name="password-new" type="password" autocomplete="new-password" minlength="8" maxlength="24" autofocus required data-password-source />
              <button class="ssc-password-toggle" type="button" data-password-toggle data-target="password-new" aria-label="Mostra o nascondi password" aria-pressed="false">
                <span class="ssc-password-toggle__icon" aria-hidden="true"></span>
              </button>
            </div>
            <div class="ssc-field__messages" aria-live="polite">
              <#if messagesPerField.existsError('password')>
                <span class="ssc-field-error">${kcSanitize(messagesPerField.getFirstError('password'))?no_esc}</span>
              </#if>
            </div>
          </div>

          <div class="ssc-field">
            <label for="password-confirm">${msg("passwordConfirm")}</label>
            <div class="ssc-password-field">
              <input id="password-confirm" name="password-confirm" type="password" autocomplete="new-password" minlength="8" maxlength="24" required />
              <button class="ssc-password-toggle" type="button" data-password-toggle data-target="password-confirm" aria-label="Mostra o nascondi password" aria-pressed="false">
                <span class="ssc-password-toggle__icon" aria-hidden="true"></span>
              </button>
            </div>
            <div class="ssc-field__messages" aria-live="polite">
              <#if messagesPerField.existsError('password-confirm')>
                <span class="ssc-field-error">${kcSanitize(messagesPerField.getFirstError('password-confirm'))?no_esc}</span>
              </#if>
            </div>
          </div>

          <div class="ssc-password-policy ssc-password-policy--compact">
            <p class="ssc-password-policy__title">Requisiti password</p>
            <ul class="ssc-helper-list">
              <li data-password-rule="length">Da 8 a 24 caratteri</li>
              <li data-password-rule="upper">Almeno una lettera maiuscola (A-Z)</li>
              <li data-password-rule="special">Almeno un carattere speciale (! @ # $ % ...)</li>
              <li data-password-rule="lower">Almeno una lettera minuscola (a-z)</li>
              <li data-password-rule="digit">Almeno una cifra (0-9)</li>
            </ul>
          </div>

          <button id="kc-passwd-update-submit" class="ssc-submit ssc-submit--full" type="submit">${msg("doReset")}</button>

          <#if isAppInitiatedAction?? && isAppInitiatedAction>
            <button class="ssc-submit ssc-submit--full" type="submit" name="cancel-aia" value="true">${msg("doCancel")}</button>
          </#if>
        </form>
      </div>
    </div>
  <#elseif section = "info">
    
  </#if>
</@layout.registrationLayout>
