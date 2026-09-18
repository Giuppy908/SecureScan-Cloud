/**
 * Provider che mette in relazione Keycloak, profilo applicativo e interfaccia.
 *
 * È il punto in cui il frontend traduce il token JWT ricevuto da Keycloak in
 * uno stato React riutilizzabile da tutte le pagine. Oltre ai ruoli, qui viene
 * sincronizzato anche il profilo proveniente dall'Analysis API
 * (`/api/v1/me/profile`), così header, Profilo e Modifica profilo condividono
 * una sola fonte di verità.
 *
 * In assenza di questo provider ogni pagina dovrebbe reinizializzare Keycloak e
 * recuperare il profilo da sola, con più complessità e più richieste duplicate.
 */
// I componenti MUI mostrano attesa e recupero dagli errori prima di rendere disponibili le pagine.
import { Button, CircularProgress, Stack, Typography } from '@mui/material'
// Il tipo descrive i claim decodificati dal client Keycloak; qui non avviene la verifica server della firma JWT.
import type { KeycloakTokenParsed } from 'keycloak-js'
import type { ReactNode } from 'react'
// Gli hook conservano stato e riferimenti e coordinano inizializzazione, timer e valore del context.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
// Queste richieste autenticate recuperano il profilo applicativo e il file avatar tramite il client HTTP.
import { getUserAvatarPreviewUrl, getUserProfile } from '../api/analysisApi'
import { ErrorState } from '../components/StatePanels'
// Il provider produce il valore condiviso; i tipi ne descrivono il contratto letto dai consumer con useAuth.
import { AuthContext, type AuthContextValue, type AuthRole, type AuthUser } from './authContext'
import { forceRefreshToken, getKeycloak, initializeKeycloak, logout } from './keycloak'

function parseRoles(tokenParsed: KeycloakTokenParsed | undefined): AuthRole[] {
  /**
   * Estrae soltanto i ruoli che il frontend conosce davvero.
   *
   * Il token Keycloak può contenere anche ruoli non usati dalla GUI. Qui li
   * filtriamo per ottenere una vista semplice: analyst e admin.
   *
   * L'admin viene considerato implicitamente anche analyst perché, dal punto di
   * vista dell'interfaccia, deve poter entrare in tutte le sezioni normali oltre
   * a quelle amministrative.
   */
  // L’optional chaining restituisce undefined se il token manca, senza accedere a proprietà di un valore assente.
  const realmAccess = tokenParsed?.realm_access
  // Accetta realm_access.roles solo quando è un array; altrimenti parte da una lista vuota.
  const roles = Array.isArray(realmAccess?.roles) ? realmAccess.roles : []

  // filter elimina i ruoli estranei; il predicato role is AuthRole restringe il tipo agli identificativi accettati.
  const normalizedRoles = roles.filter((role): role is AuthRole => role === 'analyst' || role === 'admin')
  // Se admin non è accompagnato da analyst, costruisce una lista che abilita anche le viste ordinarie della UI.
  if (normalizedRoles.includes('admin') && !normalizedRoles.includes('analyst')) {
    return ['admin', 'analyst']
  }

  // Restituisce i soli ruoli riconosciuti quando non occorre aggiungere analyst.
  return normalizedRoles
}

function parseUser(tokenParsed: KeycloakTokenParsed | undefined): AuthUser | null {
  /**
   * Traduce i claim del token in un oggetto comodo per il frontend.
   *
   * Le pagine non devono conoscere il dettaglio dei campi Keycloak:
   * `preferred_username`, `given_name`, `family_name`, `email` e `sub` vengono
   * convertiti qui in una struttura più leggibile per layout, profilo e menu.
   */
  // Senza claim disponibili non costruisce un utente, quindi il context potrà indicare assenza di autenticazione.
  if (!tokenParsed) {
    return null
  }

  // Preferisce il nome completo del token, poi lo username e infine un’etichetta neutra.
  const displayName =
    typeof tokenParsed.name === 'string' && tokenParsed.name.trim()
      ? tokenParsed.name
      : typeof tokenParsed.preferred_username === 'string' && tokenParsed.preferred_username.trim()
        ? tokenParsed.preferred_username
        : 'Utente'

  // Usa preferred_username solo se è una stringa non vuota; in caso contrario riusa il nome visualizzato.
  const username =
    typeof tokenParsed.preferred_username === 'string' && tokenParsed.preferred_username.trim()
      ? tokenParsed.preferred_username
      : displayName

  return {
    username,
    displayName,
    // Traduce given_name e family_name nei campi del frontend, mantenendo null per claim assenti o vuoti.
    firstName:
      typeof tokenParsed.given_name === 'string' && tokenParsed.given_name.trim()
        ? tokenParsed.given_name
        : null,
    lastName:
      typeof tokenParsed.family_name === 'string' && tokenParsed.family_name.trim()
        ? tokenParsed.family_name
        : null,
    email:
      typeof tokenParsed.email === 'string' && tokenParsed.email.trim()
        ? tokenParsed.email
        : null,
    // Considera verificata l’email soltanto quando il claim è esattamente il booleano true.
    emailVerified: tokenParsed.email_verified === true,
    // Usa sub come identificativo dell’identità; il fallback allo username serve quando quel claim non è disponibile.
    subject: typeof tokenParsed.sub === 'string' && tokenParsed.sub.trim() ? tokenParsed.sub : username,
    // Normalizza i ruoli prima di esporli alle guardie delle route e alla navigazione.
    roles: parseRoles(tokenParsed),
    // Il token non fornisce qui l’anteprima: l’avatar sarà caricato separatamente tramite le API del profilo.
    avatarDataUrl: null,
  }
}

function getAvatarDataUrlForAuthenticatedSubject(
  currentUser: AuthUser | null,
  nextUser: AuthUser | null,
): string | null {
  /**
   * Riutilizza l'avatar solo se il subject autenticato non cambia.
   *
   * Questo evita che, dopo logout/login con un altro account, la shell mostri
   * ancora il blob URL del profilo precedente mentre il bootstrap del nuovo
   * profilo è ancora in corso.
   */
  // Se manca una delle due identità, non riutilizza l’immagine di un utente precedente.
  if (!currentUser || !nextUser) {
    return null
  }

  // Confronta gli identificativi, non i nomi visualizzati, per decidere se conservare l’avatar.
  return currentUser.subject === nextUser.subject ? currentUser.avatarDataUrl : null
}

// Il componente riceve children come prop e rende disponibile alle pagine lo stato dell’autenticazione.
export function AuthProvider({ children }: { children: ReactNode }) {
  // useState conserva i dati tra i rendering; i setter aggiornano caricamento, errori e identità mostrata dalla UI.
  // Indica se il bootstrap auth è terminato: false mantiene visibile l’attesa invece delle pagine.
  const [isReady, setIsReady] = useState(false)
  // Conserva l’errore di inizializzazione o rinnovo che attiva il pannello Accesso non disponibile.
  const [error, setError] = useState<string | null>(null)
  // Il contatore non è mostrato: incrementarlo fa ripartire l’effetto di inizializzazione tramite le sue dipendenze.
  const [reloadKey, setReloadKey] = useState(0)
  // Contiene l’identità condivisa; impostare un nuovo oggetto aggiorna menu utente e consumer del context.
  const [user, setUser] = useState<AuthUser | null>(null)
  // useRef conserva URL e controller tra i rendering senza provocare nuovi rendering quando cambia current.
  // Ricorda l’URL blob da revocare anche dentro cleanup e callback, senza dipendere da un nuovo rendering.
  const avatarPreviewUrlRef = useRef<string | null>(null)
  // Conserva il controller della lettura profilo/avatar per interromperla da altri blocchi del provider.
  const profileBootstrapAbortControllerRef = useRef<AbortController | null>(null)
  // Ricorda quale subject è già stato sincronizzato, senza aggiungere uno stato visibile alla UI.
  const profileBootstrapSubjectRef = useRef<string | null>(null)

  // useCallback mantiene stabile la funzione; le dipendenze vuote evitano di ricrearla a ogni rendering.
  const applyAvatarPreviewUrl = useCallback((payload: string | null) => {
    // Legge l’anteprima precedente prima di sostituirla con quella appena scaricata.
    const previousAvatarPreviewUrl = avatarPreviewUrlRef.current
    if (
      previousAvatarPreviewUrl &&
      previousAvatarPreviewUrl !== payload &&
      previousAvatarPreviewUrl.startsWith('blob:')
    ) {
      // Libera la risorsa locale solo quando è un blob diverso dal nuovo URL.
      URL.revokeObjectURL(previousAvatarPreviewUrl)
    }

    // Aggiorna il riferimento da usare nella prossima sostituzione o nella pulizia del provider.
    avatarPreviewUrlRef.current = payload
    setUser((currentUser) => {
      // Una risposta del profilo non crea da sola una sessione: se manca l’utente, lascia lo stato invariato.
      if (!currentUser) {
        return currentUser
      }

      return {
        ...currentUser,
        // Sostituisce soltanto l’avatar nell’oggetto copiato, lasciando invariati ruoli e dati personali.
        avatarDataUrl: payload,
      }
    })
  }, [])

  // Aggiorna lo stato con una callback sul valore precedente; lo spread conserva i campi non modificati.
  const applyProfileSnapshot = useCallback(
    (payload: {
      username: string
      first_name: string | null
      last_name: string | null
      email: string | null
      email_verified: boolean
      avatar_url: string | null
    }) => {
      setUser((currentUser) => {
        // Una risposta del profilo non crea da sola una sessione: se manca l’utente, lascia lo stato invariato.
        if (!currentUser) {
          return currentUser
        }

        // Estrae dal profilo i nomi aggiornati, che possono differire dai claim già presenti nel token.
        const firstName = payload.first_name
        const lastName = payload.last_name
        // Unisce i nomi disponibili; se sono entrambi assenti conserva il nome visualizzato precedente.
        const displayName =
          [firstName, lastName].filter(Boolean).join(' ').trim() || currentUser.displayName

        return {
          ...currentUser,
          username: payload.username,
          displayName,
          firstName,
          lastName,
          email: payload.email,
          // Allinea lo stato visualizzato di verifica email al profilo restituito dal backend.
          emailVerified: payload.email_verified,
          // Sostituisce soltanto l’avatar nell’oggetto copiato, lasciando invariati ruoli e dati personali.
          // Se il backend non segnala più un avatar, rimuove l’anteprima; altrimenti conserva quella già caricata.
          avatarDataUrl: payload.avatar_url ? currentUser.avatarDataUrl : null,
        }
      })
    },
    [],
  )

  const refreshAuthenticatedProfile = useCallback(async () => {
    /**
     * Ricarica il profilo applicativo dell'utente autenticato.
     *
     * Il token JWT serve a identificare utente e ruoli, ma dati come avatar,
     * username aggiornato ed email verificata vengono mantenuti
     * nell'Analysis API / PostgreSQL e quindi vanno letti dal backend.
     */
    // Evita la richiesta di profilo se il client non espone una sessione autenticata e un token.
    if (!getKeycloak().authenticated || !getKeycloak().token) {
      return
    }

    // Profile and avatar bootstrap is centralized here so the header, profile page
    // and admin flows share one coherent source of truth without reintroducing the
    // previous request storm on /api/v1/me/profile.
    // Interrompe l’eventuale caricamento precedente prima di richiedere profilo e avatar aggiornati.
    profileBootstrapAbortControllerRef.current?.abort()
    // Crea un segnale condiviso dalle richieste di profilo e avatar di questo caricamento.
    const controller = new AbortController()
    profileBootstrapAbortControllerRef.current = controller

    try {
      // GET autenticata del proprio profilo: attende lo snapshot prima di decidere se richiedere anche l’immagine.
      const snapshot = await getUserProfile(controller.signal)
      // Parte senza immagine; l’eventuale mancato download non impedisce di applicare gli altri dati del profilo.
      let avatarPreviewUrl: string | null = null

      // Scarica il file solo se il backend ha restituito un percorso avatar.
      if (snapshot.avatar_url) {
        try {
          // Il client scarica il Blob con Bearer e restituisce un URL temporaneo usabile dal componente Avatar.
          avatarPreviewUrl = await getUserAvatarPreviewUrl(snapshot.avatar_url, controller.signal)
        } catch (avatarError) {
          // Propaga l’annullamento per fermare l’intero caricamento, invece di trattarlo come semplice immagine assente.
          if (avatarError instanceof DOMException && avatarError.name === 'AbortError') {
            throw avatarError
          }
          // Per un errore dell’immagine mantiene comunque utilizzabile il profilo senza avatar.
          avatarPreviewUrl = null
        }
      }

      // Controlla anche un annullamento arrivato dopo la risposta, prima di aggiornare il context.
      if (controller.signal.aborted) {
        if (avatarPreviewUrl?.startsWith('blob:')) {
          // Scarta e libera un’anteprima già creata da una richiesta ormai annullata.
          URL.revokeObjectURL(avatarPreviewUrl)
        }
        return
      }

      // Segna il subject sincronizzato soltanto dopo avere completato il percorso di caricamento.
      profileBootstrapSubjectRef.current = snapshot.subject
      // Applica l’immagine e poi i dati anagrafici al valore condiviso con le pagine.
      applyAvatarPreviewUrl(avatarPreviewUrl)
      applyProfileSnapshot(snapshot)
    } catch (nextError) {
      // Un annullamento del bootstrap termina silenziosamente; anche gli altri errori non impostano qui un feedback.
      if (nextError instanceof DOMException && nextError.name === 'AbortError') {
        return
      }
    }
  }, [applyAvatarPreviewUrl, applyProfileSnapshot])

  // useEffect inizializza Keycloak dopo il rendering; reloadKey riavvia il ciclo e il return pulisce timer, richieste e avatar.
  useEffect(() => {
    // Questa variabile appartiene al singolo effetto: il cleanup la rende false per ignorare continuazioni asincrone tardive.
    let isMounted = true
    // Conserva l’identificativo dell’intervallo creato da questa esecuzione per poterlo cancellare nel cleanup.
    let refreshTimer: number | null = null

    const startRefreshLoop = () => {
      // Token refresh updates identity claims in memory but intentionally does not
      // poll the profile endpoint: profile/avatar refreshes happen only when a real
      // profile mutation occurs or when the authenticated subject changes.
      // Ogni 20 secondi controlla il token con soglia di 30 secondi e ricostruisce l’identità dai claim.
      refreshTimer = window.setInterval(() => {
        // Avvia il controllo asincrono del token senza restituirne la Promise al timer; then e catch ne gestiscono l’esito.
        void forceRefreshToken(30)
          .then(() => {
            // Se l’effetto è già terminato, evita di applicare il risultato asincrono allo stato del provider.
            if (!isMounted) {
              return
            }

            setUser((currentUser) => {
              // Ricostruisce i dati dell’utente dai claim correnti, che possono essere stati aggiornati dal rinnovo.
              const parsedUser = parseUser(getKeycloak().tokenParsed)
              // Senza un’identità ricostruibile restituisce null e rimuove l’utente dallo stato React.
              if (!parsedUser) {
                return null
              }

              return {
                ...parsedUser,
                // Mantiene l’anteprima soltanto se il nuovo token appartiene allo stesso subject.
                avatarDataUrl: getAvatarDataUrlForAuthenticatedSubject(currentUser, parsedUser),
              }
            })
          })
          .catch(() => {
            // Se l’effetto è già terminato, evita di applicare il risultato asincrono allo stato del provider.
            if (!isMounted) {
              return
            }

            // Il fallimento del controllo periodico attiva un errore della sessione e nasconde le pagine protette.
            setError("La sessione non è più valida. Effettua nuovamente l'accesso.")
            setIsReady(false)
          })
      }, 20000)
    }

    const initialize = async () => {
      try {
        // Attende l’inizializzazione del client prima di leggere tokenParsed e attivare il ciclo di rinnovo.
        const authenticated = await initializeKeycloak()
        // Se l’effetto è già terminato, evita di applicare il risultato asincrono allo stato del provider.
        if (!isMounted) {
          return
        }

        // Recupera la stessa istanza condivisa inizializzata dal modulo keycloak.
        const keycloak = getKeycloak()
        setUser((currentUser) => {
          // Se l’inizializzazione non conferma il login, elimina il subject sincronizzato e l’utente corrente.
          if (!authenticated) {
            profileBootstrapSubjectRef.current = null
            return null
          }

          // Ricostruisce i dati dell’utente dai claim correnti, che possono essere stati aggiornati dal rinnovo.
          const parsedUser = parseUser(keycloak.tokenParsed)
          // Senza un’identità ricostruibile restituisce null e rimuove l’utente dallo stato React.
          if (!parsedUser) {
            return null
          }

          return {
            ...parsedUser,
            // Mantiene l’anteprima soltanto se il nuovo token appartiene allo stesso subject.
            avatarDataUrl: getAvatarDataUrlForAuthenticatedSubject(currentUser, parsedUser),
          }
        })
        // Cancella un precedente errore quando l’inizializzazione riesce, poi abilita la vista e il timer.
        setError(null)
        setIsReady(true)
        startRefreshLoop()
      } catch (nextError) {
        // Se l’effetto è già terminato, evita di applicare il risultato asincrono allo stato del provider.
        if (!isMounted) {
          return
        }

        setError(
          // Usa il messaggio dell’eccezione quando disponibile; per altri valori mostra l’indisponibilità dell’autenticazione.
          nextError instanceof Error
            ? nextError.message
            : 'Il servizio di autenticazione non è disponibile al momento.',
        )
        setIsReady(false)
      }
    }

    // Avvia il bootstrap; l’effetto restituisce subito il cleanup e lascia alla funzione asincrona la gestione degli errori.
    void initialize()

    return () => {
      // Marca l’effetto come concluso prima di annullare richiesta e intervallo.
      isMounted = false
      profileBootstrapAbortControllerRef.current?.abort()
      // Cancella soltanto un intervallo effettivamente creato, evitando controlli token dopo la pulizia.
      if (refreshTimer !== null) {
        window.clearInterval(refreshTimer)
      }
      // Revoca l’eventuale URL blob posseduto dal provider, poi svuota il riferimento.
      if (avatarPreviewUrlRef.current?.startsWith('blob:')) {
        URL.revokeObjectURL(avatarPreviewUrlRef.current)
        avatarPreviewUrlRef.current = null
      }
    }
  }, [reloadKey])

  // Quando sessione e subject sono pronti, carica il profilo se quel subject non è già stato sincronizzato.
  useEffect(() => {
    // La sincronizzazione profilo attende sia la disponibilità dell’autenticazione sia un’identità non vuota.
    if (!isReady || !user?.subject) {
      return
    }

    // StrictMode can replay effects in development; the subject guard ensures the
    // initial profile bootstrap runs once per authenticated user session.
    // Se quel subject è già stato applicato, evita una nuova lettura del profilo in questo effetto.
    if (profileBootstrapSubjectRef.current === user.subject) {
      return
    }

    // Avvia la lettura senza bloccare il rendering; la callback mantiene al proprio interno try/catch e aggiornamenti.
    void refreshAuthenticatedProfile()

    return () => {
      profileBootstrapAbortControllerRef.current?.abort()
    }
  }, [isReady, refreshAuthenticatedProfile, user?.subject])

  // useMemo riutilizza l’oggetto del contesto finché le dipendenze non cambiano; ?? fornisce fallback per null o undefined.
  const contextValue = useMemo<AuthContextValue>(
    () => ({
      isReady,
      // Il flag client deriva dalla presenza di user, non da una nuova validazione server a ogni rendering.
      isAuthenticated: user !== null,
      // Le guardie e la shell leggono questi booleani derivati dai ruoli normalizzati del token.
      isAdmin: user?.roles.includes('admin') ?? false,
      isAnalyst: user?.roles.includes('analyst') ?? false,
      hasRecognizedRole: (user?.roles.length ?? 0) > 0,
      user,
      // Espone ai consumer la funzione di logout senza far loro importare direttamente il client Keycloak.
      logoutUser: logout,
      applyProfileSnapshot,
      applyAvatarPreviewUrl,
      refreshAuthenticatedProfile,
    }),
    // Il valore memoizzato cambia quando cambia uno di questi dati o callback e viene propagato ai consumer.
    [applyAvatarPreviewUrl, applyProfileSnapshot, isReady, refreshAuthenticatedProfile, user],
  )

  // I return anticipati mostrano errore o attesa al posto dell’albero di pagine finché il provider non è pronto.
  // Il pulsante Riprova incrementa reloadKey e richiede una nuova inizializzazione.
  if (error) {
    return (
      <ErrorState
        title="Accesso non disponibile"
        description={error}
        actionLabel="Riprova"
        onRetry={() => setReloadKey((currentValue) => currentValue + 1)}
      />
    )
  }

  // Finché il bootstrap non termina, restituisce soltanto la schermata di attesa.
  if (!isReady) {
    return (
      <Stack spacing={2} sx={{ minHeight: '100vh', alignItems: 'center', justifyContent: 'center' }}>
        {/* L’indicatore circolare segnala attesa senza stimare una percentuale del processo di login. */}
        <CircularProgress />
        <Typography color="text.secondary">Verifica dell'accesso protetto in corso.</Typography>
        <Button variant="text" onClick={() => setReloadKey((currentValue) => currentValue + 1)}>
          Riprova
        </Button>
      </Stack>
    )
  }

  // Il provider consegna contextValue ai discendenti; children contiene il router e le pagine, senza aggiungere un elemento DOM.
  return <AuthContext.Provider value={contextValue}>{children}</AuthContext.Provider>
}
