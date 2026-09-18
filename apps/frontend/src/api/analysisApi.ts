/**
 * Client HTTP centralizzato del frontend SecureScan Cloud.
 *
 * Le pagine React non costruiscono fetch manuali sparse nel codice: tutte le
 * chiamate verso Kong / Analysis API passano da questo file. In questo modo
 * URL, token JWT, retry dopo 401 e messaggi di errore restano coerenti tra:
 * - Dashboard
 * - Nuova analisi
 * - Cronologia
 * - Dettaglio analisi
 * - Stato del sistema
 * - Profilo
 * - Amministrazione
 *
 * Dal punto di vista architetturale il flusso è:
 * componente React -> funzione di questo file -> Kong su localhost:8000 ->
 * endpoint backend reale -> risposta tipizzata per il frontend.
 */
// La configurazione fornisce l’origine HTTP; i percorsi delle singole risorse vengono aggiunti dai metodi sottostanti.
import { analysisApiUrl } from '../config/api'
// Il modulo auth fornisce il token in memoria e le operazioni di rinnovo/login, senza memorizzarlo in questo client.
import { ensureValidToken, forceRefreshToken, login } from '../auth/keycloak'
// Gli import type descrivono le risposte per il compilatore e non introducono oggetti di validazione nel browser.
import type {
  AnalysisApiPage,
  AnalysisApiRecord,
  AnalysisHealth,
  AdminUser,
  AdminUserAnalysesSnapshot,
  DashboardSnapshot,
  SystemStatusSnapshot,
  UserProfileSnapshot,
} from '../types/domain'

// Il punto interrogativo indica che detail può mancare nel payload di errore.
interface ApiErrorPayload {
  detail?: string
}

// Conserva messaggio e status HTTP; null distingue gli errori di rete senza risposta del server.
export class AnalysisApiError extends Error {
  status: number | null

  constructor(message: string, status: number | null = null) {
    // Inizializza il messaggio della classe Error; name permette di riconoscere questo errore nei log e nei controlli.
    super(message)
    this.name = 'AnalysisApiError'
    // Associa lo status alla stessa eccezione che le pagine catturano per scegliere il feedback.
    this.status = status
  }
}

// Estende le opzioni native di fetch con il controllo del token; AbortSignal consente di annullare la richiesta.
interface RequestOptions extends RequestInit {
  // Il chiamante può passare il segnale di un AbortController, ad esempio nella pulizia di un effetto React.
  signal?: AbortSignal
  // Quando omesso, il client invia il JWT; false è usato dalla lettura pubblica di /health.
  requiresAuth?: boolean
}

async function readResponsePayloadSafely(response: Response): Promise<unknown> {
  /**
   * Legge il corpo senza assumere che tutte le risposte siano JSON validi.
   *
   * È utile soprattutto nei percorsi di errore: gateway, backend o reverse
   * proxy possono restituire sia JSON sia testo semplice.
   */
  // Legge il formato dichiarato dal server; l’header assente viene trattato come stringa vuota.
  const contentType = response.headers.get('content-type') || ''
  // Il ramo JSON viene scelto solo quando il Content-Type contiene application/json.
  if (contentType.includes('application/json')) {
    try {
      // Consuma il corpo e attende il parsing JSON; Promise<unknown> impone ai passaggi successivi di verificarne l’uso.
      return await response.json()
    } catch {
      // Un corpo illeggibile o un parsing fallito viene rappresentato da null, così resta disponibile il messaggio di riserva.
      return null
    }
  }

  try {
    // Per i formati non JSON legge il corpo come testo, utile anche per errori restituiti da un proxy.
    const text = await response.text()
    // Elimina spazi esterni e tratta una risposta testuale vuota come assenza di payload.
    return text.trim() ? text.trim() : null
  } catch {
    // Se fallisce anche la lettura testuale non espone un errore di parsing al chiamante.
    return null
  }
}

function extractErrorMessage(payload: unknown, fallbackMessage: string): string {
  // Usa direttamente un messaggio testuale non vuoto, prima di provare la struttura degli errori FastAPI.
  if (typeof payload === 'string' && payload.trim()) {
    return payload
  }

  // Esclude null e valori primitivi prima di cercare la proprietà detail nel corpo ricevuto.
  if (payload && typeof payload === 'object' && 'detail' in payload) {
    // Il cast consente l’accesso TypeScript a detail; il successivo typeof controlla comunque il valore a runtime.
    const detail = (payload as ApiErrorPayload).detail
    // Accetta detail soltanto come stringa non vuota; altri formati ricadono sul fallback.
    if (typeof detail === 'string' && detail.trim()) {
      return detail
    }
  }

  // Restituisce il testo scelto in base allo status quando il server non fornisce un messaggio utilizzabile.
  return fallbackMessage
}

// Il generico T descrive il risultato atteso dal chiamante ma non valida a runtime la struttura del JSON.
async function requestJson<T>(path: string, init?: RequestOptions, retryAfterUnauthorized = true): Promise<T> {
  /**
   * Richiesta JSON standard con token JWT e recupero sessione minimo.
   *
   * Se l'Analysis API risponde 401, il frontend prova una sola volta a
   * rinnovare il token tramite Keycloak. Se il refresh fallisce, l'utente viene
   * rimandato al login invece di proseguire con una sessione incoerente.
   */
  // Conserva la risposta HTTP per separare l’invio della richiesta dalla gestione del suo esito.
  let response: Response
  // Il destructuring separa l’opzione interna dalle opzioni fetch; lo spread inoltra metodo, corpo e signal.
  const { requiresAuth = true, headers, ...restInit } = init ?? {}
  // Crea una raccolta Headers modificabile conservando eventuali header passati dal chiamante.
  const requestHeaders = new Headers(headers)

  // La richiesta è autenticata per default; solo l’opzione esplicita false evita la preparazione del Bearer.
  if (requiresAuth) {
    // Attende il controllo della validità residua con soglia di 30 secondi prima di contattare la API.
    const accessToken = await ensureValidToken(30)
    // Invia il JWT come credenziale Bearer nell’header HTTP, senza inserirlo nell’URL.
    requestHeaders.set('Authorization', `Bearer ${accessToken}`)
  }

  try {
    // await attende la risposta senza bloccare il browser; fetch segnala gli errori HTTP tramite status e ok.
    response = await fetch(`${analysisApiUrl}${path}`, {
      // Inoltra anche AbortSignal e corpo originali: annullare il controller del chiamante interrompe la fetch.
      ...restInit,
      headers: requestHeaders,
    })
  } catch (error) {
    // Riconosce l’annullamento richiesto dal chiamante e lo ripropaga, senza trasformarlo in errore di rete.
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw error
    }
    // Per gli altri errori della fetch restituisce un messaggio uniforme senza uno status HTTP disponibile.
    throw new AnalysisApiError('Impossibile contattare la Analysis API locale.', null)
  }

  // Legge il corpo una sola volta, ottenendo il JSON, il testo oppure null da usare nel ramo di risposta.
  const payload = await readResponsePayloadSafely(response)

  // Il parametro false nel secondo tentativo limita il retry a una sola ripetizione della richiesta.
  if (response.status === 401 && requiresAuth && retryAfterUnauthorized) {
    try {
      // Sul primo 401 richiama updateToken con soglia 0; il nome della funzione non implica sempre un rinnovo forzato.
      const refreshedToken = await forceRefreshToken(0)
      // Prepara il Bearer restituito da Keycloak per il nuovo tentativo sulla stessa risorsa.
      requestHeaders.set('Authorization', `Bearer ${refreshedToken}`)
      // Ripete metodo e payload originali; false disabilita un ulteriore retry e il risultato resta tipizzato come T.
      return await requestJson<T>(
        path,
        {
          // Inoltra anche AbortSignal e corpo originali: annullare il controller del chiamante interrompe la fetch.
          ...restInit,
          headers: requestHeaders,
          requiresAuth,
        },
        false,
      )
    } catch {
      // Questo catch intercetta sia errori del rinnovo sia del secondo tentativo e avvia il login Keycloak.
      await login()
      // Se la chiamata al login termina normalmente, segnala al chiamante la sessione scaduta con status 401.
      throw new AnalysisApiError("Sessione scaduta. Effettua nuovamente l'accesso.", 401)
    }
  }

  // Gli status fuori dall’intervallo 200–299 entrano nella gestione degli errori HTTP, anche se fetch è riuscita.
  if (!response.ok) {
    // Se detail manca, sceglie un messaggio locale in base allo status HTTP ricevuto.
    const fallbackMessage =
      // 404 indica una risorsa non trovata; i rami successivi distinguono limiti, permessi e problemi del servizio.
      response.status === 404
        ? 'Risorsa non trovata.'
        : response.status === 429
          ? 'Hai inviato troppe richieste in poco tempo. Attendi qualche secondo e riprova.'
        : response.status === 413
          ? 'Il file supera la dimensione massima consentita.'
          : response.status === 422
            ? 'La richiesta non è valida.'
          : response.status === 503
            ? 'Il servizio di analisi non è temporaneamente disponibile.'
          : response.status === 502 || response.status === 504
            ? 'Il gateway locale non riesce a raggiungere la Analysis API.'
          : response.status >= 500
            ? 'La Analysis API ha restituito un errore interno.'
          : response.status === 403
            ? 'Non hai i permessi per eseguire questa operazione.'
            : 'La richiesta verso la Analysis API non è andata a buon fine.'

    // Propaga un errore con messaggio e status originali affinché la pagina possa distinguere errore iniziale e di polling.
    throw new AnalysisApiError(extractErrorMessage(payload, fallbackMessage), response.status)
  }

  // L’asserzione attribuisce il tipo atteso al payload già letto, senza modificarlo né controllarne i campi.
  return payload as T
}

async function requestVoid(path: string, init?: RequestOptions, retryAfterUnauthorized = true): Promise<void> {
  /**
   * Variante per endpoint che non restituiscono un payload utile al browser.
   *
   * È usata per operazioni come delete o cambio password, dove il successo è
   * rappresentato dallo status HTTP e non da un oggetto JSON da renderizzare.
   */
  // Conserva la risposta HTTP per separare l’invio della richiesta dalla gestione del suo esito.
  let response: Response
  // Il destructuring separa l’opzione interna dalle opzioni fetch; lo spread inoltra metodo, corpo e signal.
  const { requiresAuth = true, headers, ...restInit } = init ?? {}
  // Crea una raccolta Headers modificabile conservando eventuali header passati dal chiamante.
  const requestHeaders = new Headers(headers)

  // La richiesta è autenticata per default; solo l’opzione esplicita false evita la preparazione del Bearer.
  if (requiresAuth) {
    // Attende il controllo della validità residua con soglia di 30 secondi prima di contattare la API.
    const accessToken = await ensureValidToken(30)
    // Invia il JWT come credenziale Bearer nell’header HTTP, senza inserirlo nell’URL.
    requestHeaders.set('Authorization', `Bearer ${accessToken}`)
  }

  try {
    // await attende la risposta senza bloccare il browser; fetch segnala gli errori HTTP tramite status e ok.
    response = await fetch(`${analysisApiUrl}${path}`, {
      // Inoltra anche AbortSignal e corpo originali: annullare il controller del chiamante interrompe la fetch.
      ...restInit,
      headers: requestHeaders,
    })
  } catch (error) {
    // Riconosce l’annullamento richiesto dal chiamante e lo ripropaga, senza trasformarlo in errore di rete.
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw error
    }
    // Per gli altri errori della fetch restituisce un messaggio uniforme senza uno status HTTP disponibile.
    throw new AnalysisApiError('Impossibile contattare la Analysis API locale.', null)
  }

  // 204 indica successo senza corpo: questa variante termina senza tentare di leggere JSON.
  if (response.status === 204) {
    return
  }

  // Legge il corpo una sola volta, ottenendo il JSON, il testo oppure null da usare nel ramo di risposta.
  const payload = await readResponsePayloadSafely(response)

  // Il parametro false nel secondo tentativo limita il retry a una sola ripetizione della richiesta.
  if (response.status === 401 && requiresAuth && retryAfterUnauthorized) {
    try {
      // Sul primo 401 richiama updateToken con soglia 0; il nome della funzione non implica sempre un rinnovo forzato.
      const refreshedToken = await forceRefreshToken(0)
      // Prepara il Bearer restituito da Keycloak per il nuovo tentativo sulla stessa risorsa.
      requestHeaders.set('Authorization', `Bearer ${refreshedToken}`)
      // Attende il secondo tentativo senza valore di ritorno; anche questa ricorsione è limitata a una ripetizione.
      return await requestVoid(
        path,
        {
          // Inoltra anche AbortSignal e corpo originali: annullare il controller del chiamante interrompe la fetch.
          ...restInit,
          headers: requestHeaders,
          requiresAuth,
        },
        false,
      )
    } catch {
      // Questo catch intercetta sia errori del rinnovo sia del secondo tentativo e avvia il login Keycloak.
      await login()
      // Se la chiamata al login termina normalmente, segnala al chiamante la sessione scaduta con status 401.
      throw new AnalysisApiError("Sessione scaduta. Effettua nuovamente l'accesso.", 401)
    }
  }

  // Gli status fuori dall’intervallo 200–299 entrano nella gestione degli errori HTTP, anche se fetch è riuscita.
  if (!response.ok) {
    throw new AnalysisApiError(
      extractErrorMessage(
        payload,
        response.status === 403
          ? 'Non hai i permessi per eseguire questa operazione.'
          : response.status === 429
            ? 'Hai inviato troppe richieste in poco tempo. Attendi qualche secondo e riprova.'
            : response.status === 502 || response.status === 504
              ? 'Il gateway locale non riesce a raggiungere la Analysis API.'
          : 'La richiesta verso la Analysis API non è andata a buon fine.',
      ),
      response.status,
    )
  }
}

async function requestBlob(path: string, init?: RequestOptions, retryAfterUnauthorized = true): Promise<Blob> {
  /**
   * Variante per risorse binarie, usata attualmente soprattutto dagli avatar.
   *
   * Il backend espone il file, il browser lo trasforma in Blob e poi in URL
   * locale temporaneo da assegnare ai componenti `<Avatar>`.
   */
  // Conserva la risposta HTTP per separare l’invio della richiesta dalla gestione del suo esito.
  let response: Response
  // Il destructuring separa l’opzione interna dalle opzioni fetch; lo spread inoltra metodo, corpo e signal.
  const { requiresAuth = true, headers, ...restInit } = init ?? {}
  // Crea una raccolta Headers modificabile conservando eventuali header passati dal chiamante.
  const requestHeaders = new Headers(headers)

  // La richiesta è autenticata per default; solo l’opzione esplicita false evita la preparazione del Bearer.
  if (requiresAuth) {
    // Attende il controllo della validità residua con soglia di 30 secondi prima di contattare la API.
    const accessToken = await ensureValidToken(30)
    // Invia il JWT come credenziale Bearer nell’header HTTP, senza inserirlo nell’URL.
    requestHeaders.set('Authorization', `Bearer ${accessToken}`)
  }

  try {
    // await attende la risposta senza bloccare il browser; fetch segnala gli errori HTTP tramite status e ok.
    response = await fetch(`${analysisApiUrl}${path}`, {
      // Inoltra anche AbortSignal e corpo originali: annullare il controller del chiamante interrompe la fetch.
      ...restInit,
      // Per gli avatar chiede a fetch di non riutilizzare né aggiornare la cache HTTP del browser.
      cache: 'no-store',
      headers: requestHeaders,
    })
  } catch (error) {
    // Riconosce l’annullamento richiesto dal chiamante e lo ripropaga, senza trasformarlo in errore di rete.
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw error
    }
    // Per gli altri errori della fetch restituisce un messaggio uniforme senza uno status HTTP disponibile.
    throw new AnalysisApiError('Impossibile contattare la Analysis API locale.', null)
  }

  // Il parametro false nel secondo tentativo limita il retry a una sola ripetizione della richiesta.
  if (response.status === 401 && requiresAuth && retryAfterUnauthorized) {
    try {
      // Sul primo 401 richiama updateToken con soglia 0; il nome della funzione non implica sempre un rinnovo forzato.
      const refreshedToken = await forceRefreshToken(0)
      // Prepara il Bearer restituito da Keycloak per il nuovo tentativo sulla stessa risorsa.
      requestHeaders.set('Authorization', `Bearer ${refreshedToken}`)
      // Ripete il download autenticato con le opzioni originali e restituisce il Blob se riesce.
      return await requestBlob(
        path,
        {
          // Inoltra anche AbortSignal e corpo originali: annullare il controller del chiamante interrompe la fetch.
          ...restInit,
          headers: requestHeaders,
          requiresAuth,
        },
        false,
      )
    } catch {
      // Questo catch intercetta sia errori del rinnovo sia del secondo tentativo e avvia il login Keycloak.
      await login()
      // Se la chiamata al login termina normalmente, segnala al chiamante la sessione scaduta con status 401.
      throw new AnalysisApiError("Sessione scaduta. Effettua nuovamente l'accesso.", 401)
    }
  }

  // Gli status fuori dall’intervallo 200–299 entrano nella gestione degli errori HTTP, anche se fetch è riuscita.
  if (!response.ok) {
    // Legge il corpo una sola volta, ottenendo il JSON, il testo oppure null da usare nel ramo di risposta.
    const payload = await readResponsePayloadSafely(response)
    // Se detail manca, sceglie un messaggio locale in base allo status HTTP ricevuto.
    const fallbackMessage =
      // 404 indica una risorsa non trovata; i rami successivi distinguono limiti, permessi e problemi del servizio.
      response.status === 404
        ? 'Risorsa non trovata.'
        : response.status === 403
          ? 'Non hai i permessi per eseguire questa operazione.'
          : response.status === 429
            ? 'Hai inviato troppe richieste in poco tempo. Attendi qualche secondo e riprova.'
            : response.status === 502 || response.status === 504
              ? 'Il gateway locale non riesce a raggiungere la Analysis API.'
              : response.status >= 500
                ? 'La Analysis API ha restituito un errore interno.'
                : 'La richiesta verso la Analysis API non è andata a buon fine.'

    // Propaga un errore con messaggio e status originali affinché la pagina possa distinguere errore iniziale e di polling.
    throw new AnalysisApiError(extractErrorMessage(payload, fallbackMessage), response.status)
  }

  // Legge il corpo binario dell’avatar; la Promise si risolve quando il Blob è disponibile nel browser.
  return response.blob()
}

export async function createAnalysis(file: File, signal?: AbortSignal): Promise<AnalysisApiRecord> {
  /**
   * Carica un file dalla pagina "Nuova analisi" e crea il record iniziale.
   *
   * Il backend restituisce subito l'analisi accodata; il completamento reale
   * avviene poi in modo asincrono nel Worker e viene osservato dal frontend con
   * polling.
   */
  // FormData produce multipart/form-data; il browser imposta il Content-Type con il boundary, senza header manuale.
  const formData = new FormData()
  // Il campo multipart si chiama file, come atteso dall’upload di analisi del backend.
  formData.append('file', file)

  // POST autenticata: il record accettato contiene l’ID del job; il client non attende qui il completamento della scansione.
  return requestJson<AnalysisApiRecord>('/api/v1/analyses', {
    method: 'POST',
    body: formData,
    signal,
  })
}

// I filtri sono opzionali; i tipi indicizzati riusano status e risk_level del record API.
interface ListAnalysesParams {
  // Numero di pagina facoltativo, distinto dal numero di elementi richiesti in ogni pagina.
  page?: number
  pageSize?: number
  search?: string
  // Il tipo indicizzato permette solo gli stati del contratto API; la traduzione italiana resta nella UI.
  status?: AnalysisApiRecord['status']
  risk?: AnalysisApiRecord['risk_level']
  owner?: string
}

export async function listAnalyses(
  params: ListAnalysesParams = {},
  // Il chiamante può passare il segnale di un AbortController, ad esempio nella pulizia di un effetto React.
  signal?: AbortSignal,
): Promise<AnalysisApiPage> {
  /**
   * Recupera una singola pagina della Cronologia con filtri server-side.
   *
   * Il browser non scarica più l'intera cronologia: invia pagina, page size e
   * filtri al backend, che applica RBAC, ricerca e count prima di restituire
   * solo gli elementi richiesti.
   */
  // URLSearchParams codifica filtri e paginazione nella query; ?? usa il default solo per valori null o undefined.
  const searchParams = new URLSearchParams()
  // Converte i numeri in stringhe della query usando pagina 1 e dimensione 5 se non specificate.
  searchParams.set('page', String(params.page ?? 1))
  searchParams.set('page_size', String(params.pageSize ?? 5))

  // Non invia il filtro testuale quando la ricerca è assente o contiene soltanto spazi.
  if (params.search?.trim()) {
    searchParams.set('search', params.search.trim())
  }
  // Aggiunge il filtro sullo stato tecnico del job solo se il chiamante lo ha selezionato.
  if (params.status) {
    searchParams.set('status', params.status)
  }
  // Aggiunge il livello di rischio alla query mantenendo l’identificativo del contratto API.
  if (params.risk) {
    searchParams.set('risk', params.risk)
  }
  // Aggiunge il proprietario richiesto; l’effettiva visibilità dei suoi dati dipende dall’autorizzazione server.
  if (params.owner) {
    searchParams.set('owner', params.owner)
  }

  // GET autenticata: la risposta contiene items e totali, usati per tabella e pulsanti di paginazione.
  return requestJson<AnalysisApiPage>(`/api/v1/analyses?${searchParams.toString()}`, { signal })
}

// Codifica l’ID nel percorso e restituisce il record usato dalle pagine per aggiornare stato e risultati.
export async function getAnalysis(id: string, signal?: AbortSignal): Promise<AnalysisApiRecord> {
  /** Recupera il dettaglio di una singola analisi per la pagina "Dettaglio analisi". */
  // GET autenticata per ID: il signal permette alle pagine di interrompere una lettura iniziale o di polling.
  return requestJson<AnalysisApiRecord>(`/api/v1/analyses/${encodeURIComponent(id)}`, { signal })
}

// Richiede la cancellazione della raccolta di analisi; il perimetro effettivo dipende dai controlli del backend.
export async function deleteAnalyses(): Promise<void> {
  // DELETE autenticata sulla raccolta; il chiamante attende soltanto il successo HTTP.
  return requestVoid('/api/v1/analyses', { method: 'DELETE' })
}

// Legge /health senza Bearer e restituisce lo stato identificativo dell’istanza API.
export async function getHealth(): Promise<AnalysisHealth> {
  // GET senza JWT: il risultato descrive servizio, versione e istanza secondo AnalysisHealth.
  return requestJson<AnalysisHealth>('/health', { requiresAuth: false })
}

export async function getSystemStatus(signal?: AbortSignal): Promise<SystemStatusSnapshot> {
  /** Fornisce lo snapshot usato dalla pagina "Stato del sistema" e da parte della Dashboard. */
  // GET autenticata dello stato aggregato: la pagina visualizza overall_status e la lista dei servizi.
  return requestJson<SystemStatusSnapshot>('/api/v1/system/status', { signal })
}

export async function getDashboardSnapshot(signal?: AbortSignal): Promise<DashboardSnapshot> {
  /** Recupera i riepiloghi reali mostrati nella Dashboard. */
  // GET autenticata dei riepiloghi: la risposta alimenta conteggi, rischio, andamento e analisi recenti.
  return requestJson<DashboardSnapshot>('/api/v1/dashboard', { signal })
}

export async function getUserProfile(signal?: AbortSignal): Promise<UserProfileSnapshot> {
  /** Recupera il profilo applicativo mostrato in "Profilo" e "Modifica profilo". */
  // Usa l’identità del Bearer per selezionare il proprio profilo; il metodo esplicito distingue aggiornamento e lettura.
  return requestJson<UserProfileSnapshot>('/api/v1/me/profile', { signal })
}

// Scarica l’avatar autenticato e crea un URL blob locale che il chiamante dovrà poi revocare.
export async function getUserAvatarPreviewUrl(path: string, signal?: AbortSignal): Promise<string> {
  // Esegue un GET binario autenticato sul percorso avatar ricevuto dal backend, con annullamento opzionale.
  const avatarBlob = await requestBlob(path, { signal })
  // Genera un URL blob locale utilizzabile da Avatar: non è il percorso remoto né una conversione in base64.
  return URL.createObjectURL(avatarBlob)
}

// Invia i campi del form come JSON con PUT e restituisce il profilo aggiornato per riallineare la UI.
export async function updateUserProfile(
  payload: { first_name: string; last_name: string; username: string; email: string },
  // Il chiamante può passare il segnale di un AbortController, ad esempio nella pulizia di un effetto React.
  signal?: AbortSignal,
): Promise<UserProfileSnapshot> {
  // Usa l’identità del Bearer per selezionare il proprio profilo; il metodo esplicito distingue aggiornamento e lettura.
  return requestJson<UserProfileSnapshot>('/api/v1/me/profile', {
    method: 'PUT',
    signal,
    // Dichiara un corpo JSON per i campi applicativi; il Bearer viene aggiunto dal metodo di richiesta condiviso.
    headers: { 'Content-Type': 'application/json' },
    // Serializza l’oggetto dei campi in testo JSON da inviare nel corpo HTTP.
    body: JSON.stringify(payload),
  })
}

// Invia l’immagine nel campo multipart avatar e riceve lo snapshot del profilo.
export async function uploadUserAvatar(file: File, signal?: AbortSignal): Promise<UserProfileSnapshot> {
  // FormData produce multipart/form-data; il browser imposta il Content-Type con il boundary, senza header manuale.
  const formData = new FormData()
  // Per il profilo il nome multipart è avatar, distinto dal campo file dell’upload di analisi.
  formData.append('avatar', file)

  // La risposta aggiornata permette al chiamante di riallineare avatar e profilo dopo POST o DELETE.
  return requestJson<UserProfileSnapshot>('/api/v1/me/avatar', {
    method: 'POST',
    body: formData,
    signal,
  })
}

// Elimina l’avatar sul backend e riceve il profilo da usare per aggiornare l’interfaccia.
export async function deleteUserAvatar(signal?: AbortSignal): Promise<UserProfileSnapshot> {
  // La risposta aggiornata permette al chiamante di riallineare avatar e profilo dopo POST o DELETE.
  return requestJson<UserProfileSnapshot>('/api/v1/me/avatar', {
    method: 'DELETE',
    signal,
  })
}

// Chiede al backend un nuovo invio di verifica email e restituisce il messaggio detail.
export async function resendOwnVerificationEmail(signal?: AbortSignal): Promise<{ detail: string }> {
  // POST autenticata senza corpo: il messaggio detail descrive l’esito della richiesta di reinvio.
  // POST amministrativa autenticata: il subject nel percorso seleziona il destinatario della verifica email.
  return requestJson<{ detail: string }>('/api/v1/me/verification-email', {
    method: 'POST',
    signal,
  })
}

// Richiede l’eliminazione del profilo autenticato; il successo non richiede un payload di risposta.
export async function deleteOwnAccount(signal?: AbortSignal): Promise<void> {
  // DELETE autenticata del proprio account: l’eventuale logout successivo è gestito dalla pagina.
  return requestVoid('/api/v1/me/profile', {
    method: 'DELETE',
    signal,
  })
}

// Invia password attuale, nuova password, conferma e scelta sulle altre sessioni tramite JSON.
export async function changeOwnPassword(
  payload: {
    // La password attuale accompagna nuova password e conferma nel payload del cambio autenticato.
    current_password: string
    new_password: string
    confirm_new_password: string
    // La scelta del form viene trasmessa al backend, che gestisce l’eventuale chiusura delle altre sessioni.
    logout_other_sessions: boolean
  },
  // Il chiamante può passare il segnale di un AbortController, ad esempio nella pulizia di un effetto React.
  signal?: AbortSignal,
): Promise<void> {
  // POST autenticata con JSON: il successo non richiede un oggetto di risposta da visualizzare.
  return requestVoid('/api/v1/me/password', {
    method: 'POST',
    signal,
    // Dichiara un corpo JSON per i campi applicativi; il Bearer viene aggiunto dal metodo di richiesta condiviso.
    headers: { 'Content-Type': 'application/json' },
    // Serializza l’oggetto dei campi in testo JSON da inviare nel corpo HTTP.
    body: JSON.stringify(payload),
  })
}

export async function listAdminUsers(signal?: AbortSignal): Promise<AdminUser[]> {
  /**
   * Elenca gli utenti reali per la pagina "Amministrazione".
   *
   * Questa API viene usata anche indirettamente dalla Cronologia admin per
   * popolare il filtro utente senza caricare tutte le analisi.
   */
  // GET autenticata degli utenti: AdminUser[] indica un array, usato anche dal filtro proprietario della cronologia admin.
  return requestJson<AdminUser[]>('/api/v1/admin/users', { signal })
}

// Invia una PATCH con ruolo e/o abilitazione dell’utente identificato dal subject.
export async function updateAdminUser(
  subject: string,
  payload: { role?: 'analyst' | 'admin'; enabled?: boolean },
  // Il chiamante può passare il segnale di un AbortController, ad esempio nella pulizia di un effetto React.
  signal?: AbortSignal,
): Promise<AdminUser> {
  // PATCH autenticata per subject: encodeURIComponent evita che caratteri del subject alterino la struttura del percorso.
  return requestJson<AdminUser>(`/api/v1/admin/users/${encodeURIComponent(subject)}`, {
    method: 'PATCH',
    signal,
    // Dichiara un corpo JSON per i campi applicativi; il Bearer viene aggiunto dal metodo di richiesta condiviso.
    headers: { 'Content-Type': 'application/json' },
    // Serializza l’oggetto dei campi in testo JSON da inviare nel corpo HTTP.
    body: JSON.stringify(payload),
  })
}

// Invia i dati anagrafici modificati dall’admin e restituisce l’utente aggiornato.
export async function updateAdminUserProfile(
  subject: string,
  payload: { first_name: string; last_name: string; username: string; email: string },
  // Il chiamante può passare il segnale di un AbortController, ad esempio nella pulizia di un effetto React.
  signal?: AbortSignal,
): Promise<AdminUser> {
  // PATCH autenticata per subject: encodeURIComponent evita che caratteri del subject alterino la struttura del percorso.
  return requestJson<AdminUser>(`/api/v1/admin/users/${encodeURIComponent(subject)}/profile`, {
    method: 'PATCH',
    signal,
    // Dichiara un corpo JSON per i campi applicativi; il Bearer viene aggiunto dal metodo di richiesta condiviso.
    headers: { 'Content-Type': 'application/json' },
    // Serializza l’oggetto dei campi in testo JSON da inviare nel corpo HTTP.
    body: JSON.stringify(payload),
  })
}

// Recupera lo snapshot amministrativo del subject, comprensivo di utente, statistiche e analisi.
export async function getAdminUserDetail(
  subject: string,
  // Il chiamante può passare il segnale di un AbortController, ad esempio nella pulizia di un effetto React.
  signal?: AbortSignal,
): Promise<AdminUserAnalysesSnapshot> {
  // GET autenticata per subject: restituisce utente, statistiche, distribuzione del rischio e analisi associate.
  return requestJson<AdminUserAnalysesSnapshot>(
    `/api/v1/admin/users/${encodeURIComponent(subject)}`,
    { signal },
  )
}

// Recupera lo snapshot delle analisi dell’utente dal percorso amministrativo dedicato.
export async function getAdminUserAnalyses(
  subject: string,
  // Il chiamante può passare il segnale di un AbortController, ad esempio nella pulizia di un effetto React.
  signal?: AbortSignal,
): Promise<AdminUserAnalysesSnapshot> {
  // GET autenticata per subject: restituisce utente, statistiche, distribuzione del rischio e analisi associate.
  return requestJson<AdminUserAnalysesSnapshot>(
    `/api/v1/admin/users/${encodeURIComponent(subject)}/analyses`,
    { signal },
  )
}

// Richiede l’invio della verifica email per il subject selezionato dall’amministratore.
export async function resendAdminVerificationEmail(
  subject: string,
  // Il chiamante può passare il segnale di un AbortController, ad esempio nella pulizia di un effetto React.
  signal?: AbortSignal,
): Promise<{ detail: string }> {
  // POST amministrativa autenticata: il subject nel percorso seleziona il destinatario della verifica email.
  return requestJson<{ detail: string }>(
    `/api/v1/admin/users/${encodeURIComponent(subject)}/verification-email`,
    {
      method: 'POST',
      signal,
    },
  )
}

// Invia DELETE per il subject selezionato; il backend decide se l’amministratore può eliminarlo.
export async function deleteAdminUser(subject: string, signal?: AbortSignal): Promise<void> {
  // DELETE amministrativa autenticata: la pagina potrà tornare all’elenco solo dopo il successo della Promise.
  return requestVoid(`/api/v1/admin/users/${encodeURIComponent(subject)}`, {
    method: 'DELETE',
    signal,
  })
}
