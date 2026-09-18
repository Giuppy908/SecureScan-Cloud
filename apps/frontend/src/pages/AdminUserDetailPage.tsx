/**
 * Pagina di dettaglio amministrativo di un singolo utente.
 *
 * Consente a un admin di consultare identità, statistiche e analisi associate a
 * un account, oltre a eseguire operazioni gestionali come cambio ruolo,
 * abilitazione, reinvio email e aggiornamento profilo.
 */
import ArrowBackRoundedIcon from '@mui/icons-material/ArrowBackRounded'
import DeleteForeverRoundedIcon from '@mui/icons-material/DeleteForeverRounded'
import EmailRoundedIcon from '@mui/icons-material/EmailRounded'
import EditRoundedIcon from '@mui/icons-material/EditRounded'
import PersonOffRoundedIcon from '@mui/icons-material/PersonOffRounded'
import RefreshRoundedIcon from '@mui/icons-material/RefreshRounded'
import SaveRoundedIcon from '@mui/icons-material/SaveRounded'
import {
  Alert,
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Grid,
  MenuItem,
  Stack,
  TextField,
  Typography,
} from '@mui/material'
// Gli hook React mantengono lo stato visibile, riferimenti alle richieste e callback riutilizzabili tra rendering.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
// I link usano la navigazione React Router, mantenendo l’app caricata quando cambia il percorso.
import { Link as RouterLink, useNavigate, useParams } from 'react-router'
import {
  AnalysisApiError,
  deleteAdminUser,
  getAdminUserDetail,
  resendAdminVerificationEmail,
  updateAdminUserProfile,
  updateAdminUser,
} from '../api/analysisApi'
import { PageHeader } from '../components/PageHeader'
import { RiskChip } from '../components/RiskChip'
import { SectionCard } from '../components/SectionCard'
import { EmptyState, LoadingState } from '../components/StatePanels'
import { StatusChip } from '../components/StatusChip'
// Gli import type descrivono i dati usati dalla pagina e vengono eliminati dal JavaScript prodotto.
import type { AdminUserAnalysesSnapshot } from '../types/domain'
import { formatBytesToLabel, formatDateTime, getPresentationAnalysisStatus } from '../utils/formatters'

// L’interfaccia definisce messaggio e severità dei risultati delle operazioni amministrative.
interface FeedbackState {
  message: string
  severity: 'success' | 'info' | 'warning'
}

// Sceglie il messaggio per gli errori di lettura del dettaglio conservando il testo API quando disponibile.
function getAdminDetailErrorMessage(error: unknown) {
  if (error instanceof AnalysisApiError) {
    // Un 401 produce l’avviso di sessione scaduta nel caricamento del dettaglio.
    if (error.status === 401) {
      return "La sessione non è più valida. Effettua nuovamente l'accesso."
    }
    // Un 403 indica che il server non consente di consultare l’account richiesto.
    if (error.status === 403) {
      return "Non hai i permessi per visualizzare questo utente."
    }
    // Conserva un messaggio API non vuoto invece di sostituirlo con il fallback generico.
    if (error.message.trim()) {
      return error.message
    }
  }

  return "Il dettaglio utente non è temporaneamente disponibile."
}

// Valida i campi del dialog prima della PATCH; la verifica lato browser non sostituisce quella del backend.
function validateAdminProfileForm(payload: {
  first_name: string
  last_name: string
  username: string
  email: string
}) {
  // La regex richiede 3–32 caratteri ammessi per lo username prima della modifica amministrativa.
  const usernamePattern = /^[A-Za-z0-9._-]{3,32}$/

  // Rifiuta nome o cognome assenti anche quando il campo contiene soltanto spazi.
  if (!payload.first_name.trim() || !payload.last_name.trim()) {
    return 'Nome e cognome sono obbligatori.'
  }
  // Applica il limite di 50 caratteri ai nomi controllati nel form.
  if (payload.first_name.trim().length > 50 || payload.last_name.trim().length > 50) {
    return 'Nome e cognome non possono superare 50 caratteri.'
  }
  // Verifica lo username dopo trim, senza modificarne qui il valore nel payload originale.
  if (!usernamePattern.test(payload.username.trim())) {
    return 'Lo username deve contenere da 3 a 32 caratteri e può includere solo lettere, numeri, punto, trattino o underscore.'
  }
  // Il controllo locale dell’email richiede un testo non vuoto e il carattere @.
  if (!payload.email.trim() || !payload.email.includes('@')) {
    return 'Inserisci un indirizzo email valido.'
  }
  // Rifiuta un indirizzo che supera il limite previsto prima di eseguire la PATCH.
  if (payload.email.trim().length > 254) {
    return "L'indirizzo email non può superare 254 caratteri."
  }

  // Segnala al chiamante che i controlli locali non hanno trovato errori e il salvataggio può proseguire.
  return null
}

export function AdminUserDetailPage() {
  // useParams tipizza ed estrae il subject dalla route; useNavigate permette il ritorno all’elenco dopo la cancellazione.
  const { subject = '' } = useParams<{ subject: string }>()
  const navigate = useNavigate()
  // useRef conserva controller e sequenza di caricamento senza causare rendering.
  // Conserva il controller della lettura corrente per annullarla nel cleanup o prima di una nuova lettura.
  const requestControllerRef = useRef<AbortController | null>(null)
  // Il numero di sequenza identifica l’ultima richiesta avviata senza introdurre uno stato visibile.
  const requestSequenceRef = useRef(0)

  // useState conserva snapshot, ruolo da salvare e dati dei dialog; isActionInFlight coordina i pulsanti delle operazioni.
  // Indica il caricamento dei dati iniziali e governa la vista di attesa al posto del contenuto.
  const [isLoading, setIsLoading] = useState(true)
  // Indica una lettura di aggiornamento, così la UI può mostrare attesa mantenendo i dati già caricati.
  const [isRefreshing, setIsRefreshing] = useState(false)
  // Disabilita le azioni amministrative mentre una modifica è in attesa della risposta.
  const [isActionInFlight, setIsActionInFlight] = useState(false)
  // Conserva lo snapshot API della pagina e viene sostituito quando arriva una lettura valida.
  const [snapshot, setSnapshot] = useState<AdminUserAnalysesSnapshot | null>(null)
  // Conserva il messaggio di errore della lettura per mostrare il pannello o l’avviso della pagina.
  const [error, setError] = useState<string | null>(null)
  // Contiene il risultato delle operazioni utente da mostrare in un Alert, separato dall’errore di lettura.
  const [feedback, setFeedback] = useState<FeedbackState | null>(null)
  // Conserva il ruolo selezionato nel form prima che venga salvato sul backend.
  const [nextRole, setNextRole] = useState<'analyst' | 'admin'>('analyst')
  // Controlla l’apertura del dialog di conferma della cancellazione.
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false)
  // Conserva il testo digitato nel dialog e viene usato per abilitare la conferma.
  const [deleteConfirmation, setDeleteConfirmation] = useState('')
  // Controlla l’apertura del dialog di modifica dei dati anagrafici dell’account.
  const [editDialogOpen, setEditDialogOpen] = useState(false)
  // Conserva i campi modificabili dell’account selezionato, inizializzati all’apertura del dialog.
  const [profileForm, setProfileForm] = useState({
    first_name: '',
    last_name: '',
    username: '',
    email: '',
  })

  // useEffect rimuove i feedback non warning dopo 5 secondi; cambiare feedback riavvia il timer con pulizia del precedente.
  useEffect(() => {
    // Mantiene visibili i warning e pianifica la scomparsa soltanto degli altri tipi di feedback.
    if (!feedback || feedback.severity === 'warning') {
      return
    }

    // Pianifica un’attività cancellabile; un timeout non ripete automaticamente l’operazione come un intervallo.
    const timer = window.setTimeout(() => {
      setFeedback((current) => (current === feedback ? null : current))
    }, 5000)

    return () => window.clearTimeout(timer)
  }, [feedback])

  // useCallback ricrea il caricamento quando cambia subject e legge lo snapshot amministrativo dell’account selezionato.
  const loadDetail = useCallback(async (showLoader: boolean) => {
    // Un parametro assente evita la GET e produce un errore locale di identificativo non valido.
    if (!subject) {
      setError("Identificativo utente non valido.")
      // Termina lo stato di caricamento della lettura in questo ramo, consentendo il rendering dei dati o dell’errore.
      setIsLoading(false)
      return
    }

    // Annulla la lettura ancora in corso, se presente, prima di sostituirla o lasciare la pagina.
    requestControllerRef.current?.abort()
    // Crea il segnale di annullamento da inoltrare attraverso il client API fino alla fetch.
    const controller = new AbortController()
    // Salva il controller della nuova lettura nel riferimento condiviso con la pulizia.
    requestControllerRef.current = controller
    // Assegna un numero alla lettura appena avviata: le risposte precedenti saranno riconosciute come obsolete.
    const requestId = ++requestSequenceRef.current

    // Il primo caricamento può sostituire la vista; gli aggiornamenti successivi usano un indicatore meno invasivo.
    if (showLoader) {
      setIsLoading(true)
    } else {
      setIsRefreshing(true)
    }

    try {
      // GET amministrativa autenticata per subject: riceve account, statistiche e analisi da mostrare nella pagina.
      const nextSnapshot = await getAdminUserDetail(subject, controller.signal)
      // Non applica un risultato ormai superato da una lettura più recente.
      if (requestId !== requestSequenceRef.current) {
        return
      }
      // Sostituisce i dati del dettaglio con la risposta del backend.
      setSnapshot(nextSnapshot)
      // Inizializza il selettore con il ruolo corrente dell’account, dando priorità ad admin.
      setNextRole((nextSnapshot.user.roles ?? []).includes('admin') ? 'admin' : 'analyst')
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
      setError(getAdminDetailErrorMessage(nextError))
    } finally {
      // Il finally aggiorna gli indicatori solo per la richiesta corrente, senza interferire con una lettura successiva.
      if (requestId === requestSequenceRef.current) {
        // Termina lo stato di caricamento della lettura in questo ramo, consentendo il rendering dei dati o dell’errore.
        setIsLoading(false)
        // Spegne l’indicatore di aggiornamento dopo il completamento della richiesta corrente.
        setIsRefreshing(false)
      }
    }
  }, [subject])

  // Carica il dettaglio al montaggio e al cambio di loadDetail; la pulizia cancella timer e richiesta precedenti.
  useEffect(() => {
    // Pianifica un’attività cancellabile; un timeout non ripete automaticamente l’operazione come un intervallo.
    const timer = window.setTimeout(() => {
      // Avvia la lettura iniziale per il subject corrente tramite il timeout cancellabile dell’effetto.
      void loadDetail(true)
    }, 0)

    // React esegue questa pulizia prima di ripetere l’effetto al cambio delle dipendenze e quando smonta il componente.
    return () => {
      window.clearTimeout(timer)
      // Annulla la lettura ancora in corso, se presente, prima di sostituirla o lasciare la pagina.
      requestControllerRef.current?.abort()
    }
  }, [loadDetail])

  // useMemo deriva il ruolo dai dati ricevuti; optional chaining e ?? gestiscono snapshot o ruoli assenti.
  const currentRole = useMemo<'analyst' | 'admin'>(() => {
    // Deriva admin dai ruoli dello snapshot; la lista vuota gestisce i dati non ancora disponibili.
    if ((snapshot?.user.roles ?? []).includes('admin')) {
      return 'admin'
    }
    return 'analyst'
  }, [snapshot?.user.roles])

  // La conferma accetta ELIMINA o l’identificativo visualizzato; è un controllo di intenzione nella UI.
  const deleteTargetLabel = snapshot?.user.username ?? snapshot?.user.email ?? subject
  // Confronta la conferma ripulita dagli spazi con ELIMINA o con l’etichetta del destinatario.
  const deleteConfirmValid =
    deleteConfirmation.trim() === 'ELIMINA' || deleteConfirmation.trim() === deleteTargetLabel

  // Le callback impostano la severità del feedback indipendentemente dal testo del messaggio.
  const setSuccess = useCallback((message: string) => setFeedback({ message, severity: 'success' }), [])
  const setWarning = useCallback((message: string) => setFeedback({ message, severity: 'warning' }), [])

  // Copia i dati dello snapshot nei campi controllati del dialog prima di aprirlo.
  const handleOpenEditDialog = useCallback(() => {
    // Non apre il form di modifica senza un account da cui copiare i dati iniziali.
    if (!snapshot) {
      return
    }
    // Inizializza gli input con lo snapshot e usa stringhe vuote per i campi anagrafici assenti.
    setProfileForm({
      first_name: snapshot.user.first_name ?? '',
      last_name: snapshot.user.last_name ?? '',
      username: snapshot.user.username ?? '',
      email: snapshot.user.email ?? '',
    })
    // Apre il dialog soltanto dopo aver preparato i valori controllati del form.
    setEditDialogOpen(true)
  }, [snapshot])

  // Invia la PATCH del ruolo e sostituisce solo user nello snapshot con lo spread, conservando statistiche e analisi.
  const handleRoleSave = useCallback(async () => {
    // Non invia il cambio ruolo se mancano dati, un’azione è in corso o il ruolo selezionato è già quello attivo.
    if (!snapshot || isActionInFlight || nextRole === currentRole) {
      return
    }
    // Disabilita le azioni della pagina prima di attendere la richiesta amministrativa.
    setIsActionInFlight(true)
    try {
      // PATCH autenticata: invia soltanto il nuovo ruolo dell’account identificato dal subject.
      const updatedUser = await updateAdminUser(subject, { role: nextRole })
      // Sostituisce solo user nella copia dello snapshot, mantenendo statistiche e analisi già caricate.
      setSnapshot((current) => (current ? { ...current, user: updatedUser } : current))
      // Riallinea il selettore al ruolo effettivamente restituito dal backend dopo il salvataggio.
      setNextRole((updatedUser.roles ?? []).includes('admin') ? 'admin' : 'analyst')
      setSuccess('Ruolo aggiornato correttamente')
    } catch (nextError) {
      setWarning(nextError instanceof Error ? nextError.message : 'Aggiornamento ruolo non riuscito.')
    } finally {
      // Il finally riabilita le operazioni anche quando il server rifiuta la modifica.
      setIsActionInFlight(false)
    }
  }, [currentRole, isActionInFlight, nextRole, setSuccess, setWarning, snapshot, subject])

  // Invia l’opposto dello stato enabled corrente e mostra il valore restituito dal backend.
  const handleEnabledToggle = useCallback(async () => {
    // Non modifica l’abilitazione senza account o mentre è già in corso un’altra operazione.
    if (!snapshot || isActionInFlight) {
      return
    }
    // Disabilita le azioni della pagina prima di attendere la richiesta amministrativa.
    setIsActionInFlight(true)
    try {
      // PATCH autenticata: invia il booleano opposto allo stato enabled attualmente mostrato.
      const updatedUser = await updateAdminUser(subject, { enabled: !snapshot.user.enabled })
      // Sostituisce solo user nella copia dello snapshot, mantenendo statistiche e analisi già caricate.
      setSnapshot((current) => (current ? { ...current, user: updatedUser } : current))
      setSuccess(updatedUser.enabled ? 'Account abilitato correttamente' : 'Account disabilitato correttamente')
    } catch (nextError) {
      setWarning(nextError instanceof Error ? nextError.message : 'Aggiornamento account non riuscito.')
    } finally {
      // Il finally riabilita le operazioni anche quando il server rifiuta la modifica.
      setIsActionInFlight(false)
    }
  }, [isActionInFlight, setSuccess, setWarning, snapshot, subject])

  // Richiede l’email per il subject selezionato e mostra detail dopo la risposta.
  const handleResendVerification = useCallback(async () => {
    // Interrompe il tentativo quando un’altra azione amministrativa risulta ancora in attesa.
    if (isActionInFlight) {
      return
    }
    // Disabilita le azioni della pagina prima di attendere la richiesta amministrativa.
    setIsActionInFlight(true)
    try {
      // POST autenticata di reinvio della verifica email per l’account selezionato.
      const response = await resendAdminVerificationEmail(subject)
      // Mostra come feedback il messaggio restituito dal backend per la richiesta di reinvio.
      setSuccess(response.detail)
    } catch (nextError) {
      setWarning(nextError instanceof Error ? nextError.message : "Invio dell'email non riuscito.")
    } finally {
      // Il finally riabilita le operazioni anche quando il server rifiuta la modifica.
      setIsActionInFlight(false)
    }
  }, [isActionInFlight, setSuccess, setWarning, subject])

  // Dopo DELETE torna all’elenco con replace, sostituendo la voce corrente nella cronologia del browser.
  const handleDelete = useCallback(async () => {
    // La callback ricontrolla conferma e operazioni pendenti prima della DELETE, oltre al pulsante disabilitato.
    if (!deleteConfirmValid || isActionInFlight) {
      return
    }
    // Disabilita le azioni della pagina prima di attendere la richiesta amministrativa.
    setIsActionInFlight(true)
    try {
      // Attende la cancellazione amministrativa dell’account prima di lasciare il dettaglio.
      await deleteAdminUser(subject)
      // Torna all’elenco sostituendo la voce corrente nella cronologia di navigazione del browser.
      navigate('/admin', { replace: true })
    } catch (nextError) {
      setWarning(nextError instanceof Error ? nextError.message : 'Eliminazione account non riuscita.')
    } finally {
      // Il finally riabilita le operazioni anche quando il server rifiuta la modifica.
      setIsActionInFlight(false)
      // Il finally chiude il dialog al termine del tentativo di eliminazione.
      setDeleteDialogOpen(false)
      // Svuota la conferma testuale per evitare di conservarla in una successiva apertura.
      setDeleteConfirmation('')
    }
  }, [deleteConfirmValid, isActionInFlight, navigate, setWarning, subject])

  // Valida il form, invia i dati anagrafici e aggiorna l’utente nello snapshot dopo il successo.
  const handleAdminProfileSave = useCallback(async () => {
    // Interrompe il tentativo quando un’altra azione amministrativa risulta ancora in attesa.
    if (isActionInFlight) {
      return
    }

    // Controlla i campi del dialog prima di inviarli, senza normalizzare qui l’oggetto profileForm.
    const validationError = validateAdminProfileForm(profileForm)
    // Mostra un warning e termina il salvataggio prima di effettuare richieste HTTP.
    if (validationError) {
      setWarning(validationError)
      return
    }

    // Disabilita le azioni della pagina prima di attendere la richiesta amministrativa.
    setIsActionInFlight(true)
    try {
      // PATCH autenticata dei dati anagrafici per subject: attende l’utente aggiornato dal server.
      const updatedUser = await updateAdminUserProfile(subject, profileForm)
      // Sostituisce solo user nella copia dello snapshot, mantenendo statistiche e analisi già caricate.
      setSnapshot((current) => (current ? { ...current, user: updatedUser } : current))
      // Chiude il form soltanto dopo il successo della modifica anagrafica.
      setEditDialogOpen(false)
      setSuccess('Dati utente aggiornati correttamente')
    } catch (nextError) {
      setWarning(nextError instanceof Error ? nextError.message : 'Aggiornamento dati utente non riuscito.')
    } finally {
      // Il finally riabilita le operazioni anche quando il server rifiuta la modifica.
      setIsActionInFlight(false)
    }
  }, [isActionInFlight, profileForm, setSuccess, setWarning, subject])

  // Mostra il caricamento a pagina intera soltanto finché manca anche il primo insieme di dati.
  if (isLoading && snapshot === null) {
    return (
      <LoadingState
        title="Preparazione del dettaglio utente"
        description="Sto caricando identità, statistiche e analisi dell'account selezionato."
      />
    )
  }

  // Senza dati rende disponibile un retry del caricamento al posto delle azioni dell’account.
  if (snapshot === null) {
    return (
      <EmptyState
        title="Dettaglio utente non disponibile"
        description={error ?? "I dati dell'utente non sono disponibili."}
        action={
          <Button variant="contained" onClick={() => void loadDetail(true)}>
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
        title="Dettaglio utente"
        description="Consulta identità, statistiche e analisi storiche dell'account selezionato."
        action={
          <Stack direction="row" spacing={1.25}>
            <Button
              variant="outlined"
              startIcon={<RefreshRoundedIcon />}
              disabled={isRefreshing}
              onClick={() => void loadDetail(false)}
            >
              Aggiorna
            </Button>
            <Button
              component={RouterLink}
              to="/admin"
              variant="outlined"
              color="inherit"
              startIcon={<ArrowBackRoundedIcon />}
            >
              Torna agli utenti
            </Button>
          </Stack>
        }
        highlight={snapshot.user.enabled ? 'Account attivo' : 'Account disabilitato'}
      />

      {/* Un errore successivo al caricamento viene mostrato insieme ai dati già disponibili. */}
      {error ? <Alert severity="warning">{error}</Alert> : null}
      {/* Il feedback visualizza l’esito dell’azione dell’utente quando lo stato contiene un messaggio. */}
      {feedback ? <Alert severity={feedback.severity}>{feedback.message}</Alert> : null}

      <Grid container spacing={3}>
        <Grid size={{ xs: 12, lg: 8 }}>
          <SectionCard
            title="Identità"
            action={
              <Button
                variant="outlined"
                startIcon={<EditRoundedIcon />}
                disabled={isActionInFlight}
                onClick={() => handleOpenEditDialog()}
              >
                Modifica dati
              </Button>
            }
          >
            <Grid container spacing={2}>
              {[
                { label: 'Nome', value: snapshot.user.first_name ?? 'Non disponibile' },
                { label: 'Cognome', value: snapshot.user.last_name ?? 'Non disponibile' },
                { label: 'Username', value: snapshot.user.username ?? 'Non disponibile' },
                { label: 'Email', value: snapshot.user.email ?? 'Non disponibile' },
                { label: 'Verifica email', value: snapshot.user.email_verified ? 'Verificata' : 'Non verificata' },
                { label: 'Ruolo', value: currentRole === 'admin' ? 'Amministratore' : 'Analista' },
                { label: 'Stato account', value: snapshot.user.enabled ? 'Attivo' : 'Disabilitato' },
                { label: 'Creazione account', value: snapshot.user.created_at ? formatDateTime(snapshot.user.created_at) : 'Non disponibile' },
              ].map((item) => (
                <Grid key={item.label} size={{ xs: 12, sm: 6 }}>
                  <Box
                    sx={{
                      p: 2,
                      borderRadius: 2.5,
                      border: '1px solid',
                      borderColor: 'divider',
                      bgcolor: 'rgba(255,255,255,0.48)',
                    }}
                  >
                    <Typography variant="body2" color="text.secondary" sx={{ mb: 0.5 }}>
                      {item.label}
                    </Typography>
                    <Typography sx={{ fontWeight: 700, overflowWrap: 'anywhere' }}>{item.value}</Typography>
                  </Box>
                </Grid>
              ))}
            </Grid>
          </SectionCard>
        </Grid>

        <Grid size={{ xs: 12, lg: 4 }}>
          {/* I pulsanti richiamano callback separate per ruolo, abilitazione, email e cancellazione. */}
          <SectionCard title="Azioni amministrative">
            <Stack spacing={2}>
              <TextField
                select
                fullWidth
                label="Ruolo"
                value={nextRole}
                onChange={(event) => setNextRole(event.target.value as 'analyst' | 'admin')}
              >
                <MenuItem value="analyst">Analista</MenuItem>
                <MenuItem value="admin">Amministratore</MenuItem>
              </TextField>
              <Button
                variant="contained"
                startIcon={<SaveRoundedIcon />}
                disabled={isActionInFlight || nextRole === currentRole}
                onClick={() => void handleRoleSave()}
              >
                Salva ruolo
              </Button>
              <Button
                variant="outlined"
                startIcon={<PersonOffRoundedIcon />}
                disabled={isActionInFlight}
                onClick={() => void handleEnabledToggle()}
              >
                {snapshot.user.enabled ? 'Disabilita account' : 'Abilita account'}
              </Button>
              <Button
                variant="outlined"
                startIcon={<EmailRoundedIcon />}
                disabled={isActionInFlight || !snapshot.user.email_verification_available || snapshot.user.email_verified}
                onClick={() => void handleResendVerification()}
              >
                Invia nuovamente email di verifica
              </Button>
              <Button
                variant="outlined"
                color="error"
                startIcon={<DeleteForeverRoundedIcon />}
                disabled={isActionInFlight}
                onClick={() => setDeleteDialogOpen(true)}
              >
                Elimina account
              </Button>
              <Typography variant="body2" color="text.secondary">
                Le analisi effettuate resteranno archiviate per auditabilità anche dopo l'eliminazione dell'account.
              </Typography>
            </Stack>
          </SectionCard>
        </Grid>

        <Grid size={{ xs: 12 }}>
          {/* Mostra i conteggi aggregati dello snapshot e la distribuzione dei rischi dell’account selezionato. */}
          <SectionCard title="Statistiche">
            <Grid container spacing={2}>
              {[
                { label: 'Analisi totali', value: snapshot.statistics.total_analyses },
                { label: 'Completate', value: snapshot.statistics.completed },
                { label: 'In coda o in elaborazione', value: snapshot.statistics.queued_or_processing },
                { label: 'Fallite', value: snapshot.statistics.failed },
              ].map((item) => (
                <Grid key={item.label} size={{ xs: 12, sm: 6, xl: 3 }}>
                  <Box
                    sx={{
                      p: 2,
                      borderRadius: 2.5,
                      border: '1px solid',
                      borderColor: 'divider',
                      bgcolor: 'rgba(255,255,255,0.48)',
                    }}
                  >
                    <Typography variant="body2" color="text.secondary" sx={{ mb: 0.5 }}>
                      {item.label}
                    </Typography>
                    <Typography variant="h4" sx={{ fontWeight: 700 }}>{item.value}</Typography>
                  </Box>
                </Grid>
              ))}
            </Grid>
            <Stack direction="row" spacing={1} sx={{ mt: 2, flexWrap: 'wrap', gap: 1, alignItems: 'center' }}>
              {/* Ogni livello produce un badge del rischio e un badge con il conteggio ricevuto. */}
              {snapshot.risk_distribution.map((entry) => (
                <Stack key={entry.risk_level} direction="row" spacing={1} sx={{ alignItems: 'center' }}>
                  <RiskChip risk={entry.risk_level} />
                  <Chip size="small" variant="outlined" label={entry.count} />
                </Stack>
              ))}
            </Stack>
          </SectionCard>
        </Grid>

        <Grid size={{ xs: 12 }}>
          {/* La lista contiene i record già inclusi nello snapshot, con collegamenti al dettaglio delle scansioni. */}
          <SectionCard title="Analisi dell'utente">
            {/* La condizione distingue un account senza analisi da uno snapshot non ancora caricato. */}
            {snapshot.analyses.length === 0 ? (
              <EmptyState
                title="Nessuna analisi disponibile"
                description="Questo account non ha ancora analisi associate."
              />
            ) : (
              <Stack spacing={1.5}>
                {/* map visualizza le analisi associate allo snapshot dell’utente con un collegamento al dettaglio della scansione. */}
                {snapshot.analyses.map((analysis) => (
                  <Box
                    key={analysis.id}
                    sx={{
                      p: 2,
                      borderRadius: 2.5,
                      border: '1px solid',
                      borderColor: 'divider',
                      bgcolor: 'background.paper',
                    }}
                  >
                    <Stack
                      direction={{ xs: 'column', lg: 'row' }}
                      spacing={2}
                      sx={{ justifyContent: 'space-between', alignItems: { xs: 'flex-start', lg: 'center' } }}
                    >
                      <Box sx={{ minWidth: 0, flex: 1 }}>
                        <Typography sx={{ fontWeight: 700, overflowWrap: 'anywhere' }}>
                          {analysis.file_name}
                        </Typography>
                        <Typography variant="body2" color="text.secondary">
                          ID {analysis.id} · {formatDateTime(analysis.created_at)} · {formatBytesToLabel(analysis.size_bytes)}
                        </Typography>
                      </Box>
                      <Stack direction="row" spacing={1} sx={{ flexWrap: 'wrap', gap: 1, alignItems: 'center' }}>
                        <StatusChip status={getPresentationAnalysisStatus(analysis)} />
                        <RiskChip risk={analysis.risk_level} />
                        <Button
                          component={RouterLink}
                          to={`/analyses/${analysis.id}`}
                          variant="outlined"
                          size="small"
                        >
                          Apri dettaglio
                        </Button>
                      </Stack>
                    </Stack>
                  </Box>
                ))}
              </Stack>
            )}
          </SectionCard>
        </Grid>
      </Grid>

      {/* Il dialog di eliminazione richiede una conferma valida e disabilita l’azione mentre un’operazione è in corso. */}
      <Dialog open={deleteDialogOpen} onClose={() => setDeleteDialogOpen(false)} fullWidth maxWidth="sm">
        {/* Il titolo identifica l’operazione del dialog, distinta dal contenuto della pagina sottostante. */}
        <DialogTitle>Conferma eliminazione account</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ pt: 1 }}>
            <Typography>
              Stai per eliminare definitivamente l'account <strong>{deleteTargetLabel}</strong>.
            </Typography>
            <Typography color="text.secondary">
              Per confermare, digita <strong>ELIMINA</strong> oppure lo username dell'account.
            </Typography>
            <TextField
              fullWidth
              label="Conferma"
              value={deleteConfirmation}
              onChange={(event) => setDeleteConfirmation(event.target.value)}
            />
          </Stack>
        </DialogContent>
        {/* Raggruppa conferma e annullamento; le condizioni dei pulsanti decidono quando l’operazione è disponibile. */}
        <DialogActions sx={{ px: 3, pb: 2.5 }}>
          <Button onClick={() => setDeleteDialogOpen(false)} color="inherit">
            Annulla
          </Button>
          <Button
            color="error"
            variant="contained"
            disabled={!deleteConfirmValid || isActionInFlight}
            onClick={() => void handleDelete()}
          >
            Elimina account
          </Button>
        </DialogActions>
      </Dialog>

      {/* Il dialog di modifica collega value e onChange allo stato; lo spread aggiorna un campo preservando gli altri. */}
      <Dialog open={editDialogOpen} onClose={() => setEditDialogOpen(false)} fullWidth maxWidth="sm">
        {/* Il titolo identifica l’operazione del dialog, distinta dal contenuto della pagina sottostante. */}
        <DialogTitle>Modifica dati utente</DialogTitle>
        <DialogContent>
          <Grid container spacing={2} sx={{ pt: 1 }}>
            <Grid size={{ xs: 12, sm: 6 }}>
              <TextField
                fullWidth
                label="Nome"
                value={profileForm.first_name}
                onChange={(event) => setProfileForm((current) => ({ ...current, first_name: event.target.value }))}
              />
            </Grid>
            <Grid size={{ xs: 12, sm: 6 }}>
              <TextField
                fullWidth
                label="Cognome"
                value={profileForm.last_name}
                onChange={(event) => setProfileForm((current) => ({ ...current, last_name: event.target.value }))}
              />
            </Grid>
            <Grid size={{ xs: 12, sm: 6 }}>
              <TextField
                fullWidth
                label="Username"
                value={profileForm.username}
                onChange={(event) => setProfileForm((current) => ({ ...current, username: event.target.value }))}
              />
            </Grid>
            <Grid size={{ xs: 12, sm: 6 }}>
              <TextField
                fullWidth
                label="Email"
                type="email"
                value={profileForm.email}
                onChange={(event) => setProfileForm((current) => ({ ...current, email: event.target.value }))}
              />
            </Grid>
          </Grid>
        </DialogContent>
        {/* Raggruppa conferma e annullamento; le condizioni dei pulsanti decidono quando l’operazione è disponibile. */}
        <DialogActions sx={{ px: 3, pb: 2.5 }}>
          <Button onClick={() => setEditDialogOpen(false)} color="inherit">
            Annulla
          </Button>
          <Button
            variant="contained"
            startIcon={<SaveRoundedIcon />}
            disabled={isActionInFlight}
            onClick={() => void handleAdminProfileSave()}
          >
            Salva
          </Button>
        </DialogActions>
      </Dialog>
    </Stack>
  )
}
