/**
 * Pagina "Modifica profilo".
 *
 * Permette all'utente autenticato di aggiornare i dati del proprio account e di
 * avviare il cambio password autenticato. Le modifiche vengono confermate dal
 * backend prima di essere riflesse nel contesto condiviso dell'utente.
 */
import ArrowBackRoundedIcon from '@mui/icons-material/ArrowBackRounded'
import LockRoundedIcon from '@mui/icons-material/LockRounded'
import SaveRoundedIcon from '@mui/icons-material/SaveRounded'
import {
  Alert,
  Box,
  Button,
  Checkbox,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControlLabel,
  Grid,
  IconButton,
  InputAdornment,
  Stack,
  TextField,
  Typography,
} from '@mui/material'
import VisibilityOffRoundedIcon from '@mui/icons-material/VisibilityOffRounded'
import VisibilityRoundedIcon from '@mui/icons-material/VisibilityRounded'
// Gli hook React mantengono lo stato visibile, riferimenti alle richieste e callback riutilizzabili tra rendering.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
// L’hook permette alla callback di scegliere il percorso successivo dopo un’azione dell’utente.
import { useNavigate } from 'react-router'
import {
  AnalysisApiError,
  changeOwnPassword,
  getUserProfile,
  updateUserProfile,
} from '../api/analysisApi'
import { useAuth } from '../auth/useAuth'
import { PageHeader } from '../components/PageHeader'
import { SectionCard } from '../components/SectionCard'
import { EmptyState, LoadingState } from '../components/StatePanels'
// Gli import type descrivono i dati usati dalla pagina e vengono eliminati dal JavaScript prodotto.
import type { UserProfileSnapshot } from '../types/domain'

// Il type lega testo e severità del messaggio; autoHideMs è opzionale e controlla la sua durata.
type FeedbackState = {
  message: string
  severity: 'success' | 'warning' | 'info'
  autoHideMs?: number
}

// Seleziona il messaggio per gli errori di lettura del profilo, mantenendo il dettaglio API quando disponibile.
function getProfileErrorMessage(error: unknown) {
  if (error instanceof AnalysisApiError) {
    // Distingue la sessione non valida dagli errori sui dati del profilo.
    if (error.status === 401) {
      return "La sessione non è più valida. Effettua nuovamente l'accesso."
    }
    // Un accesso autenticato può essere privo del permesso richiesto: mostra il messaggio specifico.
    if (error.status === 403) {
      return 'Non hai i permessi per modificare il profilo.'
    }
    // Per gli altri errori HTTP mantiene il messaggio del backend, se non è vuoto.
    if (error.status !== null && error.message.trim()) {
      return error.message
    }
  }

  return 'Le informazioni del profilo non sono temporaneamente disponibili.'
}

// Riconosce alcuni messaggi di conflitto email e li presenta in italiano, senza modificare la risposta API.
function getProfileSaveErrorMessage(error: unknown) {
  if (error instanceof AnalysisApiError) {
    // Distingue la sessione non valida dagli errori sui dati del profilo.
    if (error.status === 401) {
      return "La sessione non è più valida. Effettua nuovamente l'accesso."
    }
    // Un accesso autenticato può essere privo del permesso richiesto: mostra il messaggio specifico.
    if (error.status === 403) {
      return 'Non hai i permessi per modificare il profilo.'
    }

    // Normalizza il testo dell’errore per riconoscere alcune varianti di conflitto sull’indirizzo email.
    const normalizedMessage = error.message.trim().toLowerCase()
    if (
      normalizedMessage.includes('esiste già un account con questa email') ||
      normalizedMessage.includes('already exists') && normalizedMessage.includes('email')
    ) {
      return 'Questo indirizzo email è già associato a un altro account.'
    }

    // Per gli altri errori HTTP mantiene il messaggio del backend, se non è vuoto.
    if (error.status !== null && error.message.trim()) {
      return error.message
    }
  }

  return 'Aggiornamento profilo non riuscito.'
}

// Controlla campi obbligatori, lunghezze, username ed email nel browser prima dell’invio; non sostituisce i controlli server.
function validateProfileForm(payload: {
  first_name: string
  last_name: string
  username: string
  email: string
}) {
  // La regex limita lo username a 3–32 caratteri tra lettere ASCII, cifre, punto, trattino e underscore.
  const usernamePattern = /^[A-Za-z0-9._-]{3,32}$/

  // Il primo controllo rifiuta nome o cognome vuoti anche quando contengono solo spazi.
  if (!payload.first_name.trim() || !payload.last_name.trim()) {
    return 'Nome e cognome sono obbligatori.'
  }
  // Limita la lunghezza dei nomi prima di inviare il payload al backend.
  if (payload.first_name.trim().length > 50 || payload.last_name.trim().length > 50) {
    return 'Nome e cognome non possono superare 50 caratteri.'
  }
  // Controlla lo username dopo la rimozione degli spazi esterni e restituisce il primo errore trovato.
  if (!usernamePattern.test(payload.username.trim())) {
    return 'Lo username deve contenere da 3 a 32 caratteri e può includere solo lettere, numeri, punto, trattino o underscore.'
  }
  // Questo controllo locale verifica presenza dell’email e carattere @, senza una validazione completa dell’indirizzo.
  if (!payload.email.trim() || !payload.email.includes('@')) {
    return 'Inserisci un indirizzo email valido.'
  }
  // Evita l’invio di un indirizzo oltre il limite di lunghezza previsto dal form.
  if (payload.email.trim().length > 254) {
    return "L'indirizzo email non può superare 254 caratteri."
  }

  // null indica che i controlli locali sono passati e la callback può procedere alla richiesta.
  return null
}

// Verifica localmente lunghezza, categorie di caratteri e conferma della password, restituendo il primo errore.
function validatePasswordForm(payload: {
  current_password: string
  new_password: string
  confirm_new_password: string
}) {
  // Richiede la password attuale perché il cambio è un’operazione autenticata con conferma delle credenziali.
  if (!payload.current_password) {
    return 'Inserisci la password attuale.'
  }
  // La nuova password deve rispettare entrambi i limiti di lunghezza prima dei controlli sui caratteri.
  if (payload.new_password.length < 8 || payload.new_password.length > 24) {
    return 'La nuova password deve contenere da 8 a 24 caratteri.'
  }
  // Richiede almeno una maiuscola, restituendo un avviso se il requisito non è rispettato.
  if (!/[A-Z]/.test(payload.new_password)) {
    return 'La nuova password deve contenere almeno una lettera maiuscola.'
  }
  // Richiede almeno una minuscola nella nuova password.
  if (!/[a-z]/.test(payload.new_password)) {
    return 'La nuova password deve contenere almeno una lettera minuscola.'
  }
  // Richiede almeno una cifra nella nuova password.
  if (!/[0-9]/.test(payload.new_password)) {
    return 'La nuova password deve contenere almeno una cifra.'
  }
  // Richiede almeno un carattere fuori da lettere ASCII e cifre, secondo la regex locale del form.
  if (!/[^A-Za-z0-9]/.test(payload.new_password)) {
    return 'La nuova password deve contenere almeno un carattere speciale.'
  }
  // La conferma deve coincidere esattamente con la nuova password prima dell’invio.
  if (payload.new_password !== payload.confirm_new_password) {
    return 'Le due nuove password non coincidono.'
  }
  // Impedisce localmente di riutilizzare come nuova password quella appena inserita come attuale.
  if (payload.current_password === payload.new_password) {
    return 'La nuova password deve essere diversa da quella attuale.'
  }
  // null indica che i controlli locali sono passati e la callback può procedere alla richiesta.
  return null
}

export function ProfileEditPage() {
  // useRef mantiene richiesta e blocchi di salvataggio senza provocare rendering; useNavigate gestisce il ritorno al profilo.
  // Conserva il controller della lettura corrente per annullarla nel cleanup o prima di una nuova lettura.
  const requestControllerRef = useRef<AbortController | null>(null)
  // Il numero di sequenza identifica l’ultima richiesta avviata senza introdurre uno stato visibile.
  const requestSequenceRef = useRef(0)
  // Blocca un secondo salvataggio già nella callback, prima che il rendering aggiorni il pulsante.
  const saveInFlightRef = useRef(false)
  // Mantiene separato il blocco della richiesta password da quello del salvataggio anagrafico.
  const passwordChangeInFlightRef = useRef(false)
  const navigate = useNavigate()
  // Il custom hook recupera dal context la funzione che riallinea l’identità mostrata dalle altre viste.
  const { applyProfileSnapshot } = useAuth()

  // useState separa dati ricevuti, campi modificabili e feedback: gli input controllati riflettono questi valori.
  // Indica il caricamento dei dati iniziali e governa la vista di attesa al posto del contenuto.
  const [isLoading, setIsLoading] = useState(true)
  // Indica il salvataggio del profilo e disabilita il pulsante per evitare nuovi invii dalla UI.
  const [isSaving, setIsSaving] = useState(false)
  // Indica la richiesta di cambio password e disabilita il relativo pulsante durante l’attesa.
  const [isChangingPassword, setIsChangingPassword] = useState(false)
  // Conserva il messaggio di errore della lettura per mostrare il pannello o l’avviso della pagina.
  const [error, setError] = useState<string | null>(null)
  // Contiene il risultato delle operazioni utente da mostrare in un Alert, separato dall’errore di lettura.
  const [feedback, setFeedback] = useState<FeedbackState | null>(null)
  // Conserva gli errori o gli avvisi del cambio password separatamente dal salvataggio anagrafico.
  const [passwordFeedback, setPasswordFeedback] = useState<string | null>(null)
  // Conserva i dati del profilo confermati dalla API, distinti dai campi eventualmente in modifica.
  const [profile, setProfile] = useState<UserProfileSnapshot | null>(null)
  // Conserva i valori modificabili degli input; il salvataggio invia questi campi e non modifica direttamente lo snapshot.
  const [formState, setFormState] = useState({
    first_name: '',
    last_name: '',
    username: '',
    email: '',
  })
  // Controlla la visibilità del dialog per il cambio password.
  const [isPasswordDialogOpen, setIsPasswordDialogOpen] = useState(false)
  // Conserva temporaneamente password attuale, nuova, conferma e scelta sulle altre sessioni.
  const [passwordState, setPasswordState] = useState({
    current_password: '',
    new_password: '',
    confirm_new_password: '',
    logout_other_sessions: true,
  })
  // Conserva per ciascun campo la scelta di mostrare il testo oppure mascherarlo come password.
  const [showPasswords, setShowPasswords] = useState({
    current: false,
    next: false,
    confirm: false,
  })

  // useCallback stabilizza il reset, che svuota le password nello stato e ripristina mascheramento e opzioni del dialog.
  const resetPasswordDialogState = useCallback(() => {
    // Svuota le password nello stato e ripristina la scelta predefinita sulle altre sessioni.
    setPasswordState({
      current_password: '',
      new_password: '',
      confirm_new_password: '',
      logout_other_sessions: true,
    })
    // Riporta i tre campi alla visualizzazione mascherata quando il dialog viene azzerato.
    setShowPasswords({
      current: false,
      next: false,
      confirm: false,
    })
    // Rimuove un avviso del precedente tentativo prima di usare nuovamente il dialog.
    setPasswordFeedback(null)
  }, [])

  // Apre il dialog con campi vuoti per non riutilizzare password inserite in una precedente apertura.
  const openPasswordDialog = useCallback(() => {
    // Riutilizza lo stesso reset all’apertura e alla chiusura, evitando di mantenere i valori del tentativo precedente.
    resetPasswordDialogState()
    setIsPasswordDialogOpen(true)
  }, [resetPasswordDialogState])

  // Chiude il dialog e richiama il reset dei dati sensibili conservati nello stato React.
  const closePasswordDialog = useCallback(() => {
    setIsPasswordDialogOpen(false)
    // Riutilizza lo stesso reset all’apertura e alla chiusura, evitando di mantenere i valori del tentativo precedente.
    resetPasswordDialogState()
  }, [resetPasswordDialogState])

  // Carica il profilo autenticato, inizializza il form con fallback per i campi null e aggiorna il context.
  const loadProfile = useCallback(async () => {
    // Annulla la lettura ancora in corso, se presente, prima di sostituirla o lasciare la pagina.
    requestControllerRef.current?.abort()
    // Crea il segnale di annullamento da inoltrare attraverso il client API fino alla fetch.
    const controller = new AbortController()
    // Salva il controller della nuova lettura nel riferimento condiviso con la pulizia.
    requestControllerRef.current = controller
    // Assegna un numero alla lettura appena avviata: le risposte precedenti saranno riconosciute come obsolete.
    const requestId = ++requestSequenceRef.current

    setIsLoading(true)
    try {
      // GET autenticata del proprio profilo: inizializza gli input con i dati confermati dalla API.
      const snapshot = await getUserProfile(controller.signal)
      // Non applica un risultato ormai superato da una lettura più recente.
      if (requestId !== requestSequenceRef.current) {
        return
      }

      // Conserva il nuovo snapshot per mostrare anche l’eventuale email in attesa di verifica.
      setProfile(snapshot)
      // Riallinea i campi del form alla risposta backend; i valori null diventano stringhe vuote per gli input controllati.
      setFormState({
        first_name: snapshot.first_name ?? '',
        last_name: snapshot.last_name ?? '',
        username: snapshot.username,
        email: snapshot.email ?? '',
      })
      // Aggiorna il context condiviso, così le altre viste possono riflettere i nuovi dati personali.
      applyProfileSnapshot(snapshot)
      // Rimuove il precedente errore dopo il buon esito o la preparazione di un nuovo tentativo.
      setError(null)
    } catch (nextError) {
      // L’annullamento volontario non viene mostrato come errore del servizio.
      if (nextError instanceof DOMException && nextError.name === 'AbortError') {
        return
      }
      // Non applica un risultato ormai superato da una lettura più recente.
      if (requestId !== requestSequenceRef.current) {
        return
      }
      setError(getProfileErrorMessage(nextError))
    } finally {
      // Il finally aggiorna gli indicatori solo per la richiesta corrente, senza interferire con una lettura successiva.
      if (requestId === requestSequenceRef.current) {
        // Termina lo stato di caricamento della lettura in questo ramo, consentendo il rendering dei dati o dell’errore.
        setIsLoading(false)
      }
    }
  }, [applyProfileSnapshot])

  // useEffect avvia loadProfile dopo il rendering; il return annulla timer e richiesta quando la pagina viene smontata.
  useEffect(() => {
    // Pianifica un’attività cancellabile; un timeout non ripete automaticamente l’operazione come un intervallo.
    const timer = window.setTimeout(() => {
      // Avvia la lettura iniziale dal timeout cancellabile predisposto dall’effetto.
      void loadProfile()
    }, 0)

    // React esegue questa pulizia prima di ripetere l’effetto al cambio delle dipendenze e quando smonta il componente.
    return () => {
      window.clearTimeout(timer)
      // Annulla la lettura ancora in corso, se presente, prima di sostituirla o lasciare la pagina.
      requestControllerRef.current?.abort()
    }
  }, [loadProfile])

  // Al cambio di feedback programma la sua rimozione dopo autoHideMs o 6 secondi e cancella il timer precedente.
  useEffect(() => {
    // Non crea un timer di rimozione se non esiste un messaggio da mostrare.
    if (!feedback) {
      return
    }

    // Pianifica un’attività cancellabile; un timeout non ripete automaticamente l’operazione come un intervallo.
    const timer = window.setTimeout(() => {
      setFeedback((current) => (current === feedback ? null : current))
    }, feedback.autoHideMs ?? 6000)

    return () => window.clearTimeout(timer)
  }, [feedback])

  // Al cambio di passwordFeedback programma la sua rimozione dopo 6 secondi senza cancellare un messaggio più recente.
  useEffect(() => {
    // Evita il timer quando il dialog non contiene un avviso relativo alla password.
    if (!passwordFeedback) {
      return
    }

    // Pianifica un’attività cancellabile; un timeout non ripete automaticamente l’operazione come un intervallo.
    const timer = window.setTimeout(() => {
      setPasswordFeedback((current) =>
        current === passwordFeedback ? null : current,
      )
    }, 6000)

    return () => window.clearTimeout(timer)
  }, [passwordFeedback])

  // useMemo conserva la lista descrittiva dei requisiti; le dipendenze vuote la mantengono stabile.
  const passwordRequirements = useMemo(
    () => [
      'Da 8 a 24 caratteri',
      'Almeno una lettera minuscola (a-z)',
      'Almeno una lettera maiuscola (A-Z)',
      'Almeno una cifra (0-9)',
      'Almeno un carattere speciale (! @ # $ % ...)',
    ],
    [],
  )

  // Normalizza i campi, valida il form e attende PUT del profilo prima di applicare lo snapshot ricevuto.
  const handleSave = useCallback(async () => {
    // Interrompe la callback se un salvataggio anagrafico è già in attesa della risposta.
    if (saveInFlightRef.current) {
      return
    }

    // Crea un nuovo oggetto per l’invio: elimina spazi esterni e converte l’email in minuscolo.
    const normalizedPayload = {
      first_name: formState.first_name.trim(),
      last_name: formState.last_name.trim(),
      username: formState.username.trim(),
      email: formState.email.trim().toLowerCase(),
    }
    // Valida il payload normalizzato prima di impostare lo stato di invio o eseguire una fetch.
    const validationError = validateProfileForm(normalizedPayload)
    // Mostra il primo errore di validazione e termina senza contattare il backend.
    if (validationError) {
      setFeedback({ message: validationError, severity: 'warning' })
      return
    }

    // Blocca subito gli altri salvataggi, mentre isSaving rende visibile l’attesa nella UI.
    saveInFlightRef.current = true
    setIsSaving(true)
    setFeedback(null)
    try {
      // PUT autenticata dei dati anagrafici: soltanto la risposta determina quali valori risultano applicati.
      const snapshot = await updateUserProfile(normalizedPayload)
      // Conserva il nuovo snapshot per mostrare anche l’eventuale email in attesa di verifica.
      setProfile(snapshot)
      // Riallinea i campi del form alla risposta backend; i valori null diventano stringhe vuote per gli input controllati.
      setFormState({
        first_name: snapshot.first_name ?? '',
        last_name: snapshot.last_name ?? '',
        username: snapshot.username,
        email: snapshot.email ?? '',
      })
      // Aggiorna il context condiviso, così le altre viste possono riflettere i nuovi dati personali.
      applyProfileSnapshot(snapshot)
      if (
        // La risposta distingue una nuova email in attesa di verifica dall’aggiornamento già applicato.
        snapshot.email_change_pending &&
        snapshot.pending_email &&
        // Verifica che la modifica pendente riguardi proprio l’indirizzo richiesto in questo salvataggio.
        snapshot.pending_email === normalizedPayload.email &&
        // Se l’indirizzo attivo è ancora diverso, comunica l’attesa della verifica invece di considerare il cambio concluso.
        snapshot.email !== normalizedPayload.email
      ) {
        setFeedback({
          message:
            "Link di verifica inviato al nuovo indirizzo email. L'indirizzo attuale resta attivo finché non completi la conferma.",
          severity: 'success',
          autoHideMs: 6000,
        })
      } else {
        setFeedback({
          message: 'Profilo aggiornato correttamente.',
          severity: 'success',
          autoHideMs: 6000,
        })
      }
    } catch (nextError) {
      setFeedback({
        // Il fallimento del salvataggio viene convertito in feedback warning vicino al form.
        message: getProfileSaveErrorMessage(nextError),
        severity: 'warning',
      })
    } finally {
      // Il finally rilascia sempre il blocco del salvataggio, anche dopo una risposta di errore.
      saveInFlightRef.current = false
      // Riabilita il pulsante Salva e rimuove il suo indicatore di attesa.
      setIsSaving(false)
    }
  }, [applyProfileSnapshot, formState])

  // Valida e invia le password con la scelta sulle altre sessioni; al successo chiude e svuota il dialog.
  const handlePasswordChange = useCallback(async () => {
    // Non invia un’altra richiesta di cambio password mentre la precedente è ancora in corso.
    if (passwordChangeInFlightRef.current) {
      return
    }

    // Rimuove un avviso del precedente tentativo prima di usare nuovamente il dialog.
    setPasswordFeedback(null)

    // Controlla tutti i campi password nello stato prima della POST autenticata.
    const validationError = validatePasswordForm(passwordState)
    // Mostra il primo errore di validazione e termina senza contattare il backend.
    if (validationError) {
      setPasswordFeedback(validationError)
      return
    }

    // Blocca ulteriori richieste password prima di attendere la API.
    passwordChangeInFlightRef.current = true
    setIsChangingPassword(true)
    setFeedback(null)

    try {
      // Invia password attuale, nuova, conferma e logout_other_sessions; attende il successo HTTP senza un payload utile.
      await changeOwnPassword(passwordState)

      // Al successo chiude il dialog e richiama il reset dei valori password conservati nello stato.
      closePasswordDialog()

      setFeedback({
        message: 'Password aggiornata correttamente.',
        severity: 'success',
        autoHideMs: 6000,
      })
    } catch (nextError) {
      setPasswordFeedback(
        nextError instanceof Error
          ? nextError.message
          : 'Cambio password non riuscito.',
      )
    } finally {
      // Il finally permette un nuovo tentativo quando la richiesta è terminata, anche in caso di errore.
      passwordChangeInFlightRef.current = false
      // Riabilita il comando di aggiornamento password dopo la conclusione della Promise.
      setIsChangingPassword(false)
    }
  }, [closePasswordDialog, passwordState])

  // La funzione restituisce JSX riutilizzabile: visible sceglie l’icona e onToggle è la callback del pulsante.
  const passwordFieldAdornment = (
    visible: boolean,
    onToggle: () => void,
  ) => (
    <InputAdornment position="end">
      <IconButton onClick={onToggle} edge="end" aria-label="Mostra o nascondi password">
        {visible ? <VisibilityOffRoundedIcon /> : <VisibilityRoundedIcon />}
      </IconButton>
    </InputAdornment>
  )

  // Mostra il caricamento a pagina intera soltanto finché manca anche il primo insieme di dati.
  if (isLoading && profile === null) {
    return (
      <LoadingState
        title="Preparazione della modifica profilo"
        description="Sto recuperando i dati reali del tuo account."
      />
    )
  }

  // Senza dati iniziali mostra un pannello con retry e non rende il form vuoto come se fosse il profilo reale.
  if (profile === null) {
    return (
      <EmptyState
        title="Modifica profilo non disponibile"
        description={error ?? 'I dati del profilo non sono disponibili.'}
        action={
          <Button variant="contained" onClick={() => void loadProfile()}>
            Riprova
          </Button>
        }
      />
    )
  }

  return (
    <Stack spacing={3}>
      {/* L’intestazione presenta il contesto della pagina e le eventuali azioni passate attraverso le props. */}
      <PageHeader
        title="Modifica profilo"
        description="Aggiorna le informazioni del tuo account senza uscire da SecureScan Cloud."
        action={
          <Button variant="outlined" startIcon={<ArrowBackRoundedIcon />} onClick={() => navigate('/profile')}>
            Torna al profilo
          </Button>
        }
      />

      {/* Il feedback visualizza l’esito dell’azione dell’utente quando lo stato contiene un messaggio. */}
      {feedback ? (
        <Alert severity={feedback.severity}>
          {feedback.message}
        </Alert>
      ) : null}
      {/* Un errore successivo al caricamento viene mostrato insieme ai dati già disponibili. */}
      {error ? <Alert severity="warning">{error}</Alert> : null}

      {/* value e onChange collegano i campi allo stato; lo spread conserva gli altri valori durante la modifica di un campo. */}
      <SectionCard title="Informazioni account" subtitle="Le modifiche verranno applicate al tuo account SecureScan Cloud.">
        <Grid container spacing={2}>
          <Grid size={{ xs: 12, md: 6 }}>
            <TextField
              label="Nome"
              value={formState.first_name}
              onChange={(event) => setFormState((current) => ({ ...current, first_name: event.target.value }))}
              fullWidth
              slotProps={{ htmlInput: { maxLength: 50 } }}
            />
          </Grid>
          <Grid size={{ xs: 12, md: 6 }}>
            <TextField
              label="Cognome"
              value={formState.last_name}
              onChange={(event) => setFormState((current) => ({ ...current, last_name: event.target.value }))}
              fullWidth
              slotProps={{ htmlInput: { maxLength: 50 } }}
            />
          </Grid>
          <Grid size={{ xs: 12, md: 6 }}>
            <TextField
              label="Username"
              value={formState.username}
              onChange={(event) => setFormState((current) => ({ ...current, username: event.target.value }))}
              fullWidth
              helperText="Da 3 a 32 caratteri. Sono ammessi lettere, numeri, punto, trattino e underscore."
              slotProps={{ htmlInput: { minLength: 3, maxLength: 32, pattern: '[A-Za-z0-9._-]{3,32}' } }}
            />
          </Grid>
          <Grid size={{ xs: 12, md: 6 }}>
            <TextField
              label="Email"
              type="email"
              value={formState.email}
              onChange={(event) => setFormState((current) => ({ ...current, email: event.target.value }))}
              fullWidth
              slotProps={{ htmlInput: { maxLength: 254 } }}
            />
          </Grid>
        </Grid>

        {/* L’avviso distingue l’indirizzo nuovo in verifica dall’email attiva già confermata. */}
        {profile.email_change_pending && profile.pending_email ? (
          <Alert severity="info" sx={{ mt: 2.5 }}>
            Nuova email in attesa di verifica: {profile.pending_email}. Finché non confermi il link ricevuto,
            SecureScan Cloud continuerà a usare l&apos;indirizzo attuale.
          </Alert>
        ) : null}

        <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.25} sx={{ mt: 3 }}>
          <Button
            variant="contained"
            startIcon={isSaving ? <CircularProgress size={18} color="inherit" /> : <SaveRoundedIcon />}
            onClick={() => void handleSave()}
            disabled={isSaving}
          >
            {isSaving ? 'Salvataggio...' : 'Salva modifiche'}
          </Button>
          <Button variant="outlined" color="inherit" onClick={() => navigate('/profile')}>
            Annulla
          </Button>
        </Stack>
      </SectionCard>

      {/* La sezione apre un dialog separato, così il cambio password non viene incluso nel salvataggio anagrafico. */}
      <SectionCard title="Password">
        <Stack spacing={2}>
          <Typography color="text.secondary">
            Per cambiare la password è necessario confermare quella attuale e crearne una nuova che soddisfi i requisiti di sicurezza.
          </Typography>
          <Box>
            <Button
              variant="outlined"
              startIcon={<LockRoundedIcon />}
              onClick={openPasswordDialog}
            >
              Cambia password
            </Button>
          </Box>
        </Stack>
      </SectionCard>

      {/* Il dialog MUI separa il cambio password dal salvataggio anagrafico e mostra il feedback dell’operazione. */}
      <Dialog
        open={isPasswordDialogOpen}
        onClose={closePasswordDialog}
        fullWidth
        maxWidth="sm"
      >
        {/* Il titolo identifica l’operazione del dialog, distinta dal contenuto della pagina sottostante. */}
        <DialogTitle>Cambia password</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ pt: 1 }}>
            <TextField
              label="Password attuale"
              type={showPasswords.current ? 'text' : 'password'}
              value={passwordState.current_password}
              onChange={(event) =>
                setPasswordState((current) => ({ ...current, current_password: event.target.value }))
              }
              fullWidth
              slotProps={{
                input: {
                  endAdornment: passwordFieldAdornment(showPasswords.current, () =>
                    setShowPasswords((current) => ({ ...current, current: !current.current })),
                  ),
                },
              }}
            />
            <TextField
              label="Nuova password"
              type={showPasswords.next ? 'text' : 'password'}
              value={passwordState.new_password}
              onChange={(event) =>
                setPasswordState((current) => ({ ...current, new_password: event.target.value }))
              }
              fullWidth
              slotProps={{
                input: {
                  endAdornment: passwordFieldAdornment(showPasswords.next, () =>
                    setShowPasswords((current) => ({ ...current, next: !current.next })),
                  ),
                },
              }}
            />
            <TextField
              label="Conferma nuova password"
              type={showPasswords.confirm ? 'text' : 'password'}
              value={passwordState.confirm_new_password}
              onChange={(event) =>
                setPasswordState((current) => ({ ...current, confirm_new_password: event.target.value }))
              }
              fullWidth
              slotProps={{
                input: {
                  endAdornment: passwordFieldAdornment(showPasswords.confirm, () =>
                    setShowPasswords((current) => ({ ...current, confirm: !current.confirm })),
                  ),
                },
              }}
            />
            <Box
              sx={{
                p: 2,
                borderRadius: 2.5,
                border: '1px solid',
                borderColor: 'divider',
                bgcolor: 'rgba(255,255,255,0.48)',
              }}
            >
              <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
                Requisiti password
              </Typography>
              <Stack spacing={0.75}>
                {/* Ogni requisito diventa una riga informativa; i controlli effettivi sono nella funzione di validazione. */}
                {passwordRequirements.map((requirement) => (
                  <Typography key={requirement} variant="body2">
                    • {requirement}
                  </Typography>
                ))}
              </Stack>
            </Box>

            {/* L’Alert del dialog mostra errori di validazione o della richiesta password senza chiudere il form. */}
            {passwordFeedback ? (
              <Alert
                severity="warning"
                sx={{ alignItems: 'center' }}
              >
                {passwordFeedback}
              </Alert>
            ) : null}

            <Box sx={{ px: 0.5, py: 0.25 }}>
              {/* Associa un testo alla checkbox che trasmette la scelta di disconnettere le altre sessioni. */}
              <FormControlLabel
                control={
                  <Checkbox
                    checked={passwordState.logout_other_sessions}
                    onChange={(event) =>
                      setPasswordState((current) => ({
                        // Lo spread mantiene gli altri campi mentre viene aggiornato il valore controllato dalla checkbox.
                        ...current,
                        logout_other_sessions: event.target.checked,
                      }))
                    }
                    sx={{ mt: -0.5 }}
                  />
                }
                label={
                  <Box sx={{ pt: 0.25 }}>
                    <Typography variant="body1">
                      Disconnetti le altre sessioni attive
                    </Typography>

                    <Typography
                      variant="body2"
                      color="text.secondary"
                      sx={{ mt: 0.25, lineHeight: 1.45 }}
                    >
                      Gli altri dispositivi collegati a questo account dovranno effettuare
                      nuovamente l&apos;accesso.
                    </Typography>
                  </Box>
                }
                sx={{
                  alignItems: 'flex-start',
                  m: 0,
                  width: '100%',
                  '& .MuiFormControlLabel-label': {
                    flex: 1,
                  },
                }}
              />
            </Box>
          </Stack>
        </DialogContent>
        {/* Raggruppa conferma e annullamento; le condizioni dei pulsanti decidono quando l’operazione è disponibile. */}
        <DialogActions sx={{ px: 3, pb: 2.5 }}>
          <Button onClick={closePasswordDialog} color="inherit">
            Annulla
          </Button>
          <Button
            onClick={() => void handlePasswordChange()}
            variant="contained"
            startIcon={<SaveRoundedIcon />}
            disabled={isChangingPassword}
          >
            Aggiorna password
          </Button>
        </DialogActions>
      </Dialog>
    </Stack>
  )
}
