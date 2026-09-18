/**
 * Wrapper minimo attorno al client JavaScript di Keycloak.
 *
 * Questo file centralizza il modo in cui il frontend:
 * - apre il login;
 * - effettua il logout;
 * - inizializza la sessione;
 * - aggiorna il token JWT;
 * - costruisce URL verso Account Console e required actions.
 *
 * Le pagine applicative non parlano direttamente con Keycloak: usano queste
 * funzioni tramite `AuthProvider` o tramite il client API quando serve allegare
 * il token alle richieste verso Kong / Analysis API.
 */
// Importa il client browser che gestisce i passaggi del protocollo di login con il server Keycloak.
import Keycloak from 'keycloak-js'

// Vite espone questi valori al browser durante la build; URL, realm e client identificano il servizio di login.
export const keycloakUrl = import.meta.env.VITE_KEYCLOAK_URL || 'http://localhost:8180'
// Il realm seleziona lo spazio di utenti e ruoli usato dal client SecureScan.
export const keycloakRealm = import.meta.env.VITE_KEYCLOAK_REALM || 'securescan'
// Il client ID identifica questa applicazione presso Keycloak; non è una password o un client secret.
export const keycloakClientId =
  import.meta.env.VITE_KEYCLOAK_CLIENT_ID || 'securescan-frontend'

// Una sola istanza del client mantiene in memoria token e sessione per i moduli che la importano.
const keycloak = new Keycloak({
  // Passa al costruttore l’indirizzo del server; creare l’istanza non equivale ancora a completare il login.
  url: keycloakUrl,
  realm: keycloakRealm,
  clientId: keycloakClientId,
})

// Questo flag di modulo ricorda un’inizializzazione completata; viene condiviso da tutti gli importatori.
let initialized = false

export function getKeycloak() {
  // Restituisce la stessa istanza per leggere token, claim e stato, senza crearne una nuova.
  return keycloak
}

export async function initializeKeycloak() {
  // Se il bootstrap è già terminato, riusa lo stato autenticato corrente senza richiamare init.
  if (initialized) {
    // Restituisce la stessa istanza per leggere token, claim e stato, senza crearne una nuova.
    // Se il client non espone ancora il booleano authenticated restituisce false come fallback.
    return keycloak.authenticated ?? false
  }

  // Avvia il flusso standard con PKCE S256 e login obbligatorio, disabilitando il controllo tramite iframe.
  const authenticated = await keycloak.init({
    // Durante init richiede il login se non esiste già una sessione utilizzabile.
    onLoad: 'login-required',
    // PKCE usa una challenge S256 nel flusso di autorizzazione del client browser.
    pkceMethod: 'S256',
    // Seleziona il flusso standard basato sul codice di autorizzazione, gestito internamente dalla libreria.
    flow: 'standard',
    // Disabilita il controllo periodico della sessione tramite iframe; il provider usa il proprio controllo del token.
    checkLoginIframe: false,
  })

  // Segna il bootstrap come completato solo dopo che la Promise di init si è risolta.
  initialized = true
  // Restituisce al provider l’esito booleano da cui verrà costruito lo stato utente.
  return authenticated
}

export async function ensureValidToken(minValidity = 30) {
  /**
   * Restituisce un token ancora valido per le chiamate API.
   *
   * `minValidity` indica quanti secondi di vita residua vogliamo garantire
   * prima di spedire la richiesta: in questo modo il browser evita di inviare
   * token ormai prossimi alla scadenza alle pagine come Dashboard, Cronologia,
   * Profilo e Dettaglio analisi.
   */
  // Non tenta updateToken prima del completamento del bootstrap del client.
  if (!initialized) {
    throw new Error('Keycloak non inizializzato.')
  }

  // updateToken verifica la scadenza ed eventualmente usa il refresh token; il booleano indica se ha rinnovato il token.
  const refreshed = await keycloak.updateToken(minValidity)
  // L’assenza del token impedisce di preparare una richiesta Bearer anche se updateToken non ha lanciato errori.
  if (!keycloak.token) {
    throw new Error('Token di accesso non disponibile.')
  }

  // Se è avvenuto un rinnovo restituisce il token aggiornato; anche il ramo seguente restituisce il token corrente.
  if (refreshed) {
    // Restituisce la stessa istanza per leggere token, claim e stato, senza crearne una nuova.
    // Consegna la stringa del token al chiamante, senza copiarla in localStorage o sessionStorage.
    return keycloak.token
  }

  // Restituisce la stessa istanza per leggere token, claim e stato, senza crearne una nuova.
  // Consegna la stringa del token al chiamante, senza copiarla in localStorage o sessionStorage.
  return keycloak.token
}

export async function forceRefreshToken(minValidity = -1) {
  /**
   * Forza il refresh del token quando una richiesta API riceve 401.
   *
   * Il frontend lo usa come secondo tentativo automatico prima di rimandare
   * l'utente al login, così una sessione ancora recuperabile non interrompe
   * inutilmente il lavoro sulle pagine protette.
   */
  // Non tenta updateToken prima del completamento del bootstrap del client.
  if (!initialized) {
    throw new Error('Keycloak non inizializzato.')
  }

  // Con -1 richiede un rinnovo forzato; con altri valori controlla la validità residua espressa in secondi.
  await keycloak.updateToken(minValidity)
  // L’assenza del token impedisce di preparare una richiesta Bearer anche se updateToken non ha lanciato errori.
  if (!keycloak.token) {
    throw new Error('Token di accesso non disponibile.')
  }

  // Restituisce la stessa istanza per leggere token, claim e stato, senza crearne una nuova.
  // Consegna la stringa del token al chiamante, senza copiarla in localStorage o sessionStorage.
  return keycloak.token
}

// Restituisce una Promise mentre il client avvia la navigazione verso il login Keycloak.
export async function login() {
  // Delega la navigazione al login alla libreria; non raccoglie username o password in questo modulo.
  await keycloak.login()
}

// Chiude la sessione tramite Keycloak e indica l’origine del frontend come destinazione di ritorno.
export async function logout() {
  // Richiede la chiusura della sessione al server di identità prima del ritorno al frontend.
  await keycloak.logout({
    // Indica soltanto l’origine del sito come destinazione dopo il logout, senza mantenere il percorso della pagina.
    redirectUri: window.location.origin,
  })
}

// Costruisce il collegamento alla console account con ritorno al percorso frontend indicato.
export function getAccountConsoleUrl(redirectPath = '/profile') {
  // Restituisce la stessa istanza per leggere token, claim e stato, senza crearne una nuova.
  // Genera un collegamento alla console account, senza effettuare qui una navigazione.
  return keycloak.createAccountUrl({
    // Combina l’origine del browser con il percorso interno da usare al termine del flusso Keycloak.
    redirectUri: `${window.location.origin}${redirectPath}`,
  })
}

// La union limita le azioni richieste a password, profilo ed email; il parametro imposta anche la lingua italiana.
export async function getRequiredActionUrl(
  action: 'UPDATE_PASSWORD' | 'UPDATE_PROFILE' | 'UPDATE_EMAIL',
  redirectPath = '/profile',
) {
  // Restituisce la stessa istanza per leggere token, claim e stato, senza crearne una nuova.
  // Genera l’URL per la required action selezionata; sarà il chiamante a decidere se aprirlo.
  return keycloak.createLoginUrl({
    action,
    // Richiede la lingua italiana per la schermata gestita dal server di autenticazione.
    locale: 'it',
    // Combina l’origine del browser con il percorso interno da usare al termine del flusso Keycloak.
    redirectUri: `${window.location.origin}${redirectPath}`,
  })
}
