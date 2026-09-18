<#--
  Pagina "Registrazione".

  Qui il theme personalizzato raccoglie nome, cognome, username, email e
  password direttamente in Keycloak. Il frontend SecureScan Cloud apre questo
  flow, ma non salva credenziali in proprio: creazione account e password
  restano interamente di competenza di Keycloak.
-->
<#import "template.ftl" as layout>
<@layout.registrationLayout displayMessage=!messagesPerField.existsError('username','email','firstName','lastName','password','password-confirm') displayInfo=false; section>
  <#if section = "header">
    
  <#elseif section = "form">
    <div class="ssc-auth-shell ssc-auth-shell--register">
      <div class="ssc-auth-card ssc-auth-card--register">
        <div class="ssc-auth-card__header">
          <h1 class="ssc-auth-card__title ssc-auth-card__title--icon">Crea il tuo account</h1>
          <p class="ssc-auth-card__subtitle">Registrati a SecureScan Cloud.</p>
        </div>

        <form
          id="kc-register-form"
          class="ssc-form-grid"
          action="${url.registrationAction}"
          method="post"
          data-inline-error-dismiss-delay="5000"
        >
          <div class="ssc-field">
            <label for="firstName">${msg("firstName")}</label>
            <input id="firstName" name="firstName" type="text" value="${(register.formData.firstName!'')}" autocomplete="given-name" maxlength="50" required />
            <div class="ssc-field__messages" aria-live="polite">
              <#if messagesPerField.existsError('firstName')>
                <span class="ssc-field-error" data-inline-field-error>${kcSanitize(messagesPerField.getFirstError('firstName'))?no_esc}</span>
              </#if>
            </div>
          </div>

          <div class="ssc-field">
            <label for="lastName">${msg("lastName")}</label>
            <input id="lastName" name="lastName" type="text" value="${(register.formData.lastName!'')}" autocomplete="family-name" maxlength="50" required />
            <div class="ssc-field__messages" aria-live="polite">
              <#if messagesPerField.existsError('lastName')>
                <span class="ssc-field-error" data-inline-field-error>${kcSanitize(messagesPerField.getFirstError('lastName'))?no_esc}</span>
              </#if>
            </div>
          </div>

          <div class="ssc-field">
            <label for="username">${msg("username")}</label>
            <input id="username" name="username" type="text" value="${(register.formData.username!'')}" autocomplete="username" minlength="3" maxlength="32" pattern="[A-Za-z0-9._-]{3,32}" required />
            <div class="ssc-field__messages ssc-field__messages--with-note" aria-live="polite">
              <span class="ssc-field-note">Da 3 a 32 caratteri. Lettere, numeri, punto, trattino e underscore.</span>
              <#if messagesPerField.existsError('username')>
                <span class="ssc-field-error" data-inline-field-error>${kcSanitize(messagesPerField.getFirstError('username'))?no_esc}</span>
              </#if>
            </div>
          </div>

          <div class="ssc-field">
            <label for="email">${msg("email")}</label>
            <input id="email" name="email" type="email" value="${(register.formData.email!'')}" autocomplete="email" maxlength="254" required />
            <div class="ssc-field__messages ssc-field__messages--with-note" aria-live="polite">
              <span class="ssc-field-note ssc-field-note--spacer" aria-hidden="true">Da 3 a 32 caratteri. Lettere, numeri, punto, trattino e underscore.</span>
              <#if messagesPerField.existsError('email')>
                <span class="ssc-field-error" data-inline-field-error>${kcSanitize(messagesPerField.getFirstError('email'))?no_esc}</span>
              </#if>
            </div>
          </div>

          <div class="ssc-field">
            <label for="password">${msg("password")}</label>
            <div class="ssc-password-field">
              <input id="password" name="password" type="password" autocomplete="new-password" minlength="8" maxlength="24" required data-password-source />
              <button class="ssc-password-toggle" type="button" data-password-toggle data-target="password" aria-label="Mostra o nascondi password" aria-pressed="false">
                <span class="ssc-password-toggle__icon" aria-hidden="true"></span>
              </button>
            </div>
            <div class="ssc-field__messages" aria-live="polite">
              <#if messagesPerField.existsError('password')>
                <span class="ssc-field-error" data-inline-field-error>${kcSanitize(messagesPerField.getFirstError('password'))?no_esc}</span>
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
                <span class="ssc-field-error" data-inline-field-error>${kcSanitize(messagesPerField.getFirstError('password-confirm'))?no_esc}</span>
              </#if>
            </div>
          </div>

          <div class="ssc-password-policy">
            <p class="ssc-password-policy__title">Requisiti password</p>
            <ul class="ssc-helper-list">
              <li data-password-rule="length">Da 8 a 24 caratteri</li>
              <li data-password-rule="upper">Almeno una lettera maiuscola (A-Z)</li>
              <li data-password-rule="special">Almeno un carattere speciale (! @ # $ % ...)</li>
              <li data-password-rule="lower">Almeno una lettera minuscola (a-z)</li>
              <li data-password-rule="digit">Almeno una cifra (0-9)</li>
            </ul>
          </div>

          <button id="kc-register" class="ssc-submit ssc-submit--full" type="submit">${msg("doRegister")}</button>

          <div class="ssc-auth-footer ssc-auth-footer--wide">
            <span>Hai già un account?</span>
            <a href="${url.loginUrl}">${msg("doLogIn")}</a>
          </div>
        </form>
      </div>
    </div>
  <#elseif section = "info">
    
  </#if>
</@layout.registrationLayout>
