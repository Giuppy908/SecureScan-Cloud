/**
 * Comportamenti UI del theme di login Keycloak.
 *
 * Questo script non autentica l'utente e non prende decisioni di sicurezza.
 * Serve invece a rifinire il comportamento dell'interfaccia nelle pagine
 * Keycloak personalizzate di SecureScan Cloud.
 *
 * In particolare gestisce:
 * - visibilità password nei form login/registrazione/reset;
 * - indicatori live dei requisiti password;
 * - auto-dismiss di alcuni alert temporanei;
 * - auto-redirect solo nei flow che lo richiedono ancora.
 *
 * La pagina finale "Password aggiornata" non usa più auto-redirect: quindi quel
 * caso non riceve attributi `data-auto-redirect-*` e questo script non forza
 * nessuna navigazione automatica.
 */
document.addEventListener("DOMContentLoaded", () => {
  const scheduleVisualDismiss = (node, delay, dismissClass) => {
    if (!(node instanceof HTMLElement)) {
      return;
    }

    window.setTimeout(() => {
      node.classList.add(dismissClass);
      window.setTimeout(() => {
        node.remove();
      }, 260);
    }, delay);
  };

  const getClientLoginDestination = (loginUrl, explicitDestination) => {
    if (explicitDestination) {
      return explicitDestination;
    }

    try {
      const parsedLoginUrl = new URL(loginUrl, window.location.origin);
      const redirectUri = parsedLoginUrl.searchParams.get("redirect_uri");

      if (redirectUri) {
        const parsedRedirectUri = new URL(redirectUri, window.location.origin);
        return `${parsedRedirectUri.origin}/`;
      }

      return `${window.location.origin}/`;
    } catch {
      return `${window.location.origin}/`;
    }
  };

  const buildLogoutRedirectUrl = (loginUrl, explicitDestination) => {
    try {
      const parsedLoginUrl = new URL(loginUrl, window.location.origin);
      const realmMatch = window.location.pathname.match(/\/realms\/([^/]+)\//);
      const realm = realmMatch?.[1];
      const clientId = parsedLoginUrl.searchParams.get("client_id");
      const postLogoutRedirectUri = getClientLoginDestination(loginUrl, explicitDestination);

      if (!realm || !clientId) {
        return postLogoutRedirectUri;
      }

      const logoutUrl = new URL(`/realms/${encodeURIComponent(realm)}/protocol/openid-connect/logout`, window.location.origin);
      logoutUrl.searchParams.set("client_id", clientId);
      logoutUrl.searchParams.set("post_logout_redirect_uri", postLogoutRedirectUri);
      return logoutUrl.toString();
    } catch {
      return getClientLoginDestination(loginUrl, explicitDestination);
    }
  };

  const redirectNode = document.querySelector("[data-auto-redirect-url]");
  if (redirectNode instanceof HTMLElement) {
    // Il redirect automatico è opzionale e dipende solo dagli attributi del template.
    // Se il template finale del reset password non li espone, questa sezione non interviene.
    const redirectUrl = redirectNode.getAttribute("data-auto-redirect-url");
    const delay = Number.parseInt(redirectNode.getAttribute("data-auto-redirect-delay") || "0", 10);
    const shouldClearSession = redirectNode.getAttribute("data-clear-session-before-redirect") === "true";
    const explicitDestination = redirectNode.getAttribute("data-client-login-destination");
    const finalRedirectUrl =
      redirectUrl && shouldClearSession
        ? buildLogoutRedirectUrl(
            redirectNode.getAttribute("data-login-url") || redirectUrl,
            explicitDestination,
          )
        : redirectUrl;

    if (redirectNode instanceof HTMLAnchorElement) {
      const manualLoginUrl =
        redirectNode.getAttribute("data-client-login-destination") ||
        redirectNode.getAttribute("data-login-url") ||
        redirectNode.href;
      redirectNode.href =
        shouldClearSession && manualLoginUrl
          ? buildLogoutRedirectUrl(
              redirectNode.getAttribute("data-login-url") || manualLoginUrl,
              explicitDestination || manualLoginUrl,
            )
          : manualLoginUrl;
    }

    if (finalRedirectUrl && Number.isFinite(delay) && delay > 0) {
      window.setTimeout(() => {
        window.location.assign(finalRedirectUrl);
      }, delay);
    }
  }

  document.querySelectorAll(".pf-v5-c-alert.pf-m-success, .alert-success").forEach((alertNode) => {
    // Alcuni messaggi di successo del login possono essere transitori; il dismiss
    // automatico è puramente visuale e non cambia il risultato del flow.
    window.setTimeout(() => {
      if (!(alertNode instanceof HTMLElement)) {
        return;
      }

      alertNode.style.transition = "opacity 180ms ease";
      alertNode.style.opacity = "0";
      window.setTimeout(() => {
        alertNode.remove();
      }, 220);
    }, 5000);
  });

  const registerForm = document.querySelector("#kc-register-form[data-inline-error-dismiss-delay]");
  if (registerForm instanceof HTMLFormElement) {
    // Gli errori inline della registrazione restano visibili per alcuni secondi,
    // poi vengono rimossi solo dal punto di vista visuale. La validazione
    // Keycloak, i valori del form e gli attributi dei campi non vengono alterati.
    const dismissDelay = Number.parseInt(
      registerForm.getAttribute("data-inline-error-dismiss-delay") || "5000",
      10,
    );

    if (Number.isFinite(dismissDelay) && dismissDelay > 0) {
      registerForm.querySelectorAll("[data-inline-field-error]").forEach((errorNode) => {
        scheduleVisualDismiss(errorNode, dismissDelay, "ssc-field-error--dismissing");
      });
    }
  }

  document.querySelectorAll("[data-password-toggle]").forEach((button) => {
    // Mostra/nascondi password per login, registrazione e reset senza toccare la validazione server-side.
    button.addEventListener("click", () => {
      const targetId = button.getAttribute("data-target");
      if (!targetId) {
        return;
      }

      const input = document.getElementById(targetId);
      if (!(input instanceof HTMLInputElement)) {
        return;
      }

      const nextType = input.type === "password" ? "text" : "password";
      input.type = nextType;
      button.setAttribute("aria-pressed", nextType === "text" ? "true" : "false");
    });
  });

  const passwordSource = document.querySelector("[data-password-source]");
  const rules = {
    length: document.querySelector("[data-password-rule='length']"),
    upper: document.querySelector("[data-password-rule='upper']"),
    lower: document.querySelector("[data-password-rule='lower']"),
    digit: document.querySelector("[data-password-rule='digit']"),
    special: document.querySelector("[data-password-rule='special']"),
  };

  if (passwordSource instanceof HTMLInputElement) {
    // Feedback locale sui requisiti password: aiuta la UX, ma il controllo definitivo
    // resta quello applicato da Keycloak secondo la password policy del realm.
    const evaluateRules = () => {
      const value = passwordSource.value;
      const states = {
        length: value.length >= 8 && value.length <= 24,
        upper: /[A-Z]/.test(value),
        lower: /[a-z]/.test(value),
        digit: /[0-9]/.test(value),
        special: /[^A-Za-z0-9]/.test(value),
      };

      Object.entries(rules).forEach(([key, node]) => {
        if (!node) {
          return;
        }
        node.classList.toggle("is-satisfied", Boolean(states[key]));
      });
    };

    passwordSource.addEventListener("input", evaluateRules);
    evaluateRules();
  }
});
