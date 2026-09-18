/**
 * Pagina "Profilo".
 *
 * Riassume i dati del proprio account SecureScan Cloud: identità, stato email,
 * ruolo, statistiche personali e avatar. Il frontend combina qui i claim del
 * token con i dati applicativi recuperati dall'Analysis API.
 */
import CameraAltRoundedIcon from '@mui/icons-material/CameraAltRounded'
import DeleteOutlineRoundedIcon from '@mui/icons-material/DeleteOutlineRounded'
import DeleteForeverRoundedIcon from '@mui/icons-material/DeleteForeverRounded'
import EditRoundedIcon from '@mui/icons-material/EditRounded'
import {
  Alert,
  Avatar,
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Grid,
  Stack,
  TextField,
  Typography,
} from '@mui/material'
// Gli hook React mantengono lo stato visibile, riferimenti alle richieste e callback riutilizzabili tra rendering.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
// L’hook permette alla callback di scegliere il percorso successivo dopo un’azione dell’utente.
import { useNavigate } from 'react-router'
import {
  AnalysisApiError,
  deleteOwnAccount,
  deleteUserAvatar,
  getUserProfile,
  getUserAvatarPreviewUrl,
  resendOwnVerificationEmail,
  uploadUserAvatar,
} from '../api/analysisApi'
// Il context espone identità, aggiornamento dell’avatar, applicazione del profilo e logout condivisi con la shell.
import { useAuth } from '../auth/useAuth'
import { PageHeader } from '../components/PageHeader'
import { SectionCard } from '../components/SectionCard'
import { EmptyState, LoadingState } from '../components/StatePanels'
// Gli import type descrivono i dati usati dalla pagina e vengono eliminati dal JavaScript prodotto.
import type { UserProfileSnapshot } from '../types/domain'
import { getRoleLabel } from '../utils/labels'

// Mantiene il messaggio applicativo quando disponibile e distingue errori di autenticazione e autorizzazione.
function getProfileErrorMessage(error: unknown) {
  if (error instanceof AnalysisApiError) {
    if (error.status === 401) {
      return "La sessione non è più valida. Effettua nuovamente l'accesso."
    }
    if (error.status === 403) {
      return 'Non hai i permessi per visualizzare il profilo.'
    }
    // Mantiene il dettaglio applicativo del backend quando è disponibile uno status e un messaggio non vuoto.
    if (error.status !== null && error.message.trim()) {
      return error.message
    }
  }

  return 'Il profilo non è temporaneamente disponibile.'
}

// filter elimina i nomi assenti e join compone il nome visualizzato, con fallback se il profilo è incompleto.
function getDisplayName(profile: UserProfileSnapshot | null, fallbackName: string) {
  // Prima del caricamento usa il nome di riserva passato dal componente.
  if (!profile) {
    return fallbackName
  }

  // Unisce soltanto i nomi presenti e ricade sul fallback se il risultato è vuoto.
  return [profile.first_name, profile.last_name].filter(Boolean).join(' ').trim() || fallbackName
}

export function ProfilePage() {
  // useRef conserva input, controller e blocchi delle operazioni tra rendering senza causare aggiornamenti visivi.
  // Conserva il controllo file nascosto per aprirlo dal pulsante e svuotarlo dopo il caricamento.
  const avatarInputRef = useRef<HTMLInputElement | null>(null)
  // Conserva il controller della lettura corrente per annullarla nel cleanup o prima di una nuova lettura.
  const requestControllerRef = useRef<AbortController | null>(null)
  // Il numero di sequenza identifica l’ultima richiesta avviata senza introdurre uno stato visibile.
  const requestSequenceRef = useRef(0)
  // Blocca sincronicamente una seconda operazione avatar, senza attendere l’aggiornamento dello stato visibile.
  const avatarOperationInFlightRef = useRef(false)
  // Ricorda una cancellazione account in corso per non avviarne un’altra dalla callback.
  const accountDeletionInFlightRef = useRef(false)
  // useNavigate cambia la pagina nel router; useAuth legge dal context utente e funzioni di sincronizzazione.
  const navigate = useNavigate()
  const { applyAvatarPreviewUrl, applyProfileSnapshot, logoutUser, user } = useAuth()

  // useState mantiene profilo, feedback e conferma del dialog; i setter aggiornano la vista.
  // Indica il caricamento dei dati iniziali e governa la vista di attesa al posto del contenuto.
  const [isLoading, setIsLoading] = useState(true)
  // Disabilita i pulsanti dell’immagine mentre il caricamento o la rimozione sono in corso.
  const [isUploadingAvatar, setIsUploadingAvatar] = useState(false)
  // Conserva i dati del profilo confermati dalla API, distinti dai campi eventualmente in modifica.
  const [profile, setProfile] = useState<UserProfileSnapshot | null>(null)
  // Conserva il messaggio di errore della lettura per mostrare il pannello o l’avviso della pagina.
  const [error, setError] = useState<string | null>(null)
  // Contiene il risultato delle operazioni utente da mostrare in un Alert, separato dall’errore di lettura.
  const [feedback, setFeedback] = useState<string | null>(null)
  // Controlla l’apertura del dialog di conferma della cancellazione.
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false)
  // Conserva il testo digitato nel dialog e viene usato per abilitare la conferma.
  const [deleteConfirmation, setDeleteConfirmation] = useState('')

  // useEffect nasconde dopo 5 secondi i feedback con le parole previste; cambiare feedback cancella e ricrea il timer.
  useEffect(() => {
    // Pianifica la scomparsa del messaggio solo per i testi che contengono le parole previste dal controllo.
    if (!feedback || !feedback.includes('correttamente') && !feedback.includes('riceverai')) {
      return
    }

    // Pianifica un’attività cancellabile; un timeout non ripete automaticamente l’operazione come un intervallo.
    const timer = window.setTimeout(() => {
      // Il timer cancella soltanto il messaggio per cui era stato creato, conservando un eventuale feedback più recente.
      setFeedback((current) => (current === feedback ? null : current))
    }, 5000)

    return () => window.clearTimeout(timer)
  }, [feedback])

  // useCallback memoizza il caricamento asincrono in base alle funzioni del context, evitando dipendenze instabili.
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
      // Recupera i dati applicativi e, se presente, scarica l’avatar autenticato prima di aggiornare pagina e context.
      // GET autenticata del proprio profilo: i dati servono a campi personali, verifica email e statistiche.
      const snapshot = await getUserProfile(controller.signal)
      // Inizializza l’anteprima come assente prima di tentare il download opzionale.
      let avatarPreviewUrl: string | null = null
      // La presenza del percorso remoto abilita una seconda GET autenticata per leggere l’immagine.
      if (snapshot.avatar_url) {
        try {
          // Scarica il Blob e ottiene il riferimento temporaneo da mostrare negli Avatar del frontend.
          avatarPreviewUrl = await getUserAvatarPreviewUrl(snapshot.avatar_url, controller.signal)
        } catch (avatarError) {
          // Un annullamento interrompe anche il caricamento del profilo; gli altri errori avatar lasciano l’immagine assente.
          if (avatarError instanceof DOMException && avatarError.name === 'AbortError') {
            throw avatarError
          }
          // Se il download dell’immagine fallisce, conserva il profilo ricevuto ma non imposta un’anteprima.
          avatarPreviewUrl = null
        }
      }
      // Ignora il risultato se nel frattempo è stata avviata una richiesta con un identificativo più recente.
      // Non applica un risultato ormai superato da una lettura più recente.
      if (requestId !== requestSequenceRef.current) {
        // Se la risposta è superata, libera l’URL temporaneo invece di mantenerlo senza mostrarlo.
        if (avatarPreviewUrl?.startsWith('blob:')) {
          URL.revokeObjectURL(avatarPreviewUrl)
        }
        return
      }

      // Aggiorna i dati della pagina usando la risposta confermata dal backend.
      setProfile(snapshot)
      // Sincronizza l’immagine della shell con quella del profilo attraverso la callback del provider.
      applyAvatarPreviewUrl(avatarPreviewUrl)
      // Allinea anche nome, username ed email nel context condiviso con gli altri componenti.
      applyProfileSnapshot(snapshot)
      // Rimuove il precedente errore dopo il buon esito o la preparazione di un nuovo tentativo.
      setError(null)
    } catch (nextError) {
      // L’annullamento volontario non viene mostrato come errore del servizio.
      if (nextError instanceof DOMException && nextError.name === 'AbortError') {
        return
      }
      // Ignora il risultato se nel frattempo è stata avviata una richiesta con un identificativo più recente.
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
  }, [applyAvatarPreviewUrl, applyProfileSnapshot])

  // Al montaggio avvia loadProfile; la pulizia annulla il timer iniziale e la richiesta quando l’effetto termina.
  useEffect(() => {
    // Pianifica un’attività cancellabile; un timeout non ripete automaticamente l’operazione come un intervallo.
    const timer = window.setTimeout(() => {
      void loadProfile()
    }, 0)

    // React esegue questa pulizia prima di ripetere l’effetto al cambio delle dipendenze e quando smonta il componente.
    return () => {
      window.clearTimeout(timer)
      // Annulla la lettura ancora in corso, se presente, prima di sostituirla o lasciare la pagina.
      requestControllerRef.current?.abort()
    }
  }, [loadProfile])

  // useMemo ricalcola il ruolo visualizzato quando cambiano i ruoli; ?. e ?? usano il token come fallback del profilo.
  const primaryRole = useMemo(() => {
    // Preferisce i ruoli dello snapshot, poi quelli del context, usando una lista vuota se entrambi mancano.
    const roles = profile?.roles ?? user?.roles ?? []
    // Mostra il ruolo amministratore se presente; il ramo restante usa l’etichetta analista.
    return roles.includes('admin') ? 'admin' : 'analyst'
  }, [profile?.roles, user?.roles])

  // Deriva il nome dalla risposta applicativa e usa l’identità del context durante l’attesa.
  const displayName = getDisplayName(profile, user?.displayName ?? 'Utente')
  // Usa lo username dello snapshot quando disponibile, poi il context e infine un testo di riserva.
  const username = profile?.username ?? user?.username ?? 'utente'

  // Carica il file scelto, scarica l’anteprima e sincronizza il profilo; il ref impedisce operazioni avatar sovrapposte.
  const handleAvatarChange = useCallback(
    async (file: File | null) => {
      // Senza file o durante un’altra operazione sull’immagine termina prima di inviare richieste.
      if (!file || avatarOperationInFlightRef.current) {
        return
      }

      // Blocca subito altre operazioni avatar, mentre lo stato isUploadingAvatar aggiorna i pulsanti.
      avatarOperationInFlightRef.current = true
      // Disabilita i controlli di caricamento/rimozione fino alla conclusione dell’operazione.
      setIsUploadingAvatar(true)
      // Rimuove l’esito della precedente operazione prima di iniziare un nuovo intervento sul profilo.
      setFeedback(null)
      try {
        // POST multipart autenticata nel campo avatar; lo snapshot restituito contiene il percorso dell’immagine aggiornata.
        const snapshot = await uploadUserAvatar(file)
        // Inizializza l’anteprima come assente prima di tentare il download opzionale.
        let avatarPreviewUrl: string | null = null
        // La presenza del percorso remoto abilita una seconda GET autenticata per leggere l’immagine.
        if (snapshot.avatar_url) {
          try {
            // Scarica il Blob e ottiene il riferimento temporaneo da mostrare negli Avatar del frontend.
            avatarPreviewUrl = await getUserAvatarPreviewUrl(snapshot.avatar_url)
          } catch {
            // Se il download dell’immagine fallisce, conserva il profilo ricevuto ma non imposta un’anteprima.
            avatarPreviewUrl = null
          }
        }
        // Aggiorna i dati della pagina usando la risposta confermata dal backend.
        setProfile(snapshot)
        // Sincronizza l’immagine della shell con quella del profilo attraverso la callback del provider.
        applyAvatarPreviewUrl(avatarPreviewUrl)
        // Allinea anche nome, username ed email nel context condiviso con gli altri componenti.
        applyProfileSnapshot(snapshot)
        setFeedback('Immagine profilo aggiornata correttamente.')
      } catch (nextError) {
        setFeedback(
          nextError instanceof Error ? nextError.message : 'Caricamento immagine non riuscito.',
        )
      } finally {
        // Il finally sblocca l’operazione anche quando upload o rimozione falliscono.
        avatarOperationInFlightRef.current = false
        // Riabilita i pulsanti dell’immagine al termine della richiesta.
        setIsUploadingAvatar(false)
        // Se l’input è ancora montato, ne azzera il valore per consentire di selezionare nuovamente lo stesso file.
        if (avatarInputRef.current) {
          avatarInputRef.current.value = ''
        }
      }
    },
    [applyAvatarPreviewUrl, applyProfileSnapshot],
  )

  // Richiede la rimozione dell’avatar e azzera l’anteprima nel context dopo la risposta del backend.
  const handleAvatarDelete = useCallback(async () => {
    // Ignora una richiesta di rimozione mentre un’altra modifica dell’avatar è in corso.
    if (avatarOperationInFlightRef.current) {
      return
    }

    // Blocca subito altre operazioni avatar, mentre lo stato isUploadingAvatar aggiorna i pulsanti.
    avatarOperationInFlightRef.current = true
    // Disabilita i controlli di caricamento/rimozione fino alla conclusione dell’operazione.
    setIsUploadingAvatar(true)
    // Rimuove l’esito della precedente operazione prima di iniziare un nuovo intervento sul profilo.
    setFeedback(null)
    try {
      // DELETE autenticata dell’avatar: attende il profilo aggiornato prima di rimuovere l’immagine dalla UI.
      const snapshot = await deleteUserAvatar()
      // Aggiorna i dati della pagina usando la risposta confermata dal backend.
      setProfile(snapshot)
      // La callback del provider azzera l’immagine condivisa e gestisce la revoca dell’URL precedente.
      applyAvatarPreviewUrl(null)
      // Allinea anche nome, username ed email nel context condiviso con gli altri componenti.
      applyProfileSnapshot(snapshot)
      setFeedback('Immagine profilo rimossa correttamente.')
    } catch (nextError) {
      setFeedback(nextError instanceof Error ? nextError.message : 'Rimozione immagine non riuscita.')
    } finally {
      // Il finally sblocca l’operazione anche quando upload o rimozione falliscono.
      avatarOperationInFlightRef.current = false
      // Riabilita i pulsanti dell’immagine al termine della richiesta.
      setIsUploadingAvatar(false)
    }
  }, [applyAvatarPreviewUrl, applyProfileSnapshot])

  // Chiede al backend di reinviare l’email di verifica e visualizza detail come feedback.
  const handleResendVerification = useCallback(async () => {
    // Rimuove l’esito della precedente operazione prima di iniziare un nuovo intervento sul profilo.
    setFeedback(null)
    try {
      // POST autenticata di reinvio email; il backend sceglie il destinatario associato all’identità corrente.
      const response = await resendOwnVerificationEmail()
      // Mostra il messaggio restituito dalla API per l’operazione di verifica.
      setFeedback(response.detail)
    } catch (nextError) {
      setFeedback(nextError instanceof Error ? nextError.message : "Invio dell'email non riuscito.")
    }
  }, [])

  // Dopo la cancellazione del proprio account richiede il logout; finally chiude e azzera il dialog di conferma.
  const handleDeleteAccount = useCallback(async () => {
    // Evita un secondo invio di cancellazione mentre la prima richiesta è ancora in corso.
    if (accountDeletionInFlightRef.current) {
      return
    }

    accountDeletionInFlightRef.current = true
    // Rimuove l’esito della precedente operazione prima di iniziare un nuovo intervento sul profilo.
    setFeedback(null)
    try {
      // DELETE del proprio profilo autenticato; il passo successivo parte soltanto se questa richiesta riesce.
      await deleteOwnAccount()
      // Dopo la cancellazione avvia il logout Keycloak tramite il context condiviso.
      await logoutUser()
    } catch (nextError) {
      setFeedback(nextError instanceof Error ? nextError.message : 'Eliminazione account non riuscita.')
    } finally {
      // Il finally sblocca la callback e chiude il dialog anche se cancellazione o logout producono un errore.
      accountDeletionInFlightRef.current = false
      setDeleteDialogOpen(false)
      // Elimina il testo di conferma per non riutilizzarlo alla successiva apertura del dialog.
      setDeleteConfirmation('')
    }
  }, [logoutUser])

  // Mostra il caricamento a pagina intera soltanto finché manca anche il primo insieme di dati.
  if (isLoading && profile === null) {
    return (
      <LoadingState
        title="Caricamento del profilo"
        description="Sto recuperando identità, avatar e statistiche personali."
      />
    )
  }

  // Senza dati di profilo mostra il messaggio e un pulsante di nuova lettura invece della scheda account.
  if (profile === null) {
    return (
      <EmptyState
        title="Profilo non disponibile"
        description={error ?? 'Le informazioni del profilo non sono disponibili.'}
        action={
          <Button variant="contained" onClick={() => void loadProfile()}>
            Riprova
          </Button>
        }
      />
    )
  }

  // Trasforma i campi anagrafici in coppie etichetta/valore che il JSX può visualizzare con un map.
  const personalItems = [
    { label: 'Nome', value: profile.first_name ?? 'Non disponibile' },
    { label: 'Cognome', value: profile.last_name ?? 'Non disponibile' },
    { label: 'Username', value: profile.username },
    { label: 'Email', value: profile.email ?? 'Non disponibile' },
  ]
  // Le informazioni dello snapshot decidono se mostrare verifica email, indirizzo pendente e pulsante di reinvio.
  const showEmailVerificationStatus = profile.email_verification_available
  // Richiede sia la segnalazione di modifica pendente sia un nuovo indirizzo valorizzato.
  const showPendingEmailChange = Boolean(profile.email_change_pending && profile.pending_email)
  // Il reinvio ordinario compare solo quando la verifica è disponibile, l’email non è verificata e non c’è una modifica pendente.
  const showResendVerificationButton =
    showEmailVerificationStatus && !profile.email_verified && !showPendingEmailChange

  return (
    <Stack spacing={3}>
      {/* L’intestazione presenta il contesto della pagina e le eventuali azioni passate attraverso le props. */}
      <PageHeader
        title="Profilo"
        description="Gestisci le informazioni del tuo account e consulta le statistiche delle tue analisi."
      />

      {/* Il feedback visualizza l’esito dell’azione dell’utente quando lo stato contiene un messaggio. */}
      {feedback ? (
        <Alert severity={feedback.includes('correttamente') ? 'success' : 'warning'}>{feedback}</Alert>
      ) : null}
      {/* Un errore successivo al caricamento viene mostrato insieme ai dati già disponibili. */}
      {error ? <Alert severity="warning">{error}</Alert> : null}

      {/* La panoramica mostra identità e ruolo e offre navigazione alla modifica o apertura del dialog di cancellazione. */}
      <SectionCard title="Panoramica account">
        <Stack
          direction={{ xs: 'column', md: 'row' }}
          spacing={3}
          sx={{ alignItems: { xs: 'flex-start', md: 'flex-start' } }}
        >
          <Avatar
            src={user?.avatarDataUrl ?? undefined}
            sx={{ width: 88, height: 88, bgcolor: 'secondary.main', fontSize: '2rem' }}
          >
            {displayName.charAt(0).toUpperCase()}
          </Avatar>
          <Box sx={{ minWidth: 0, flex: 1 }}>
            <Stack
              direction={{ xs: 'column', md: 'row' }}
              spacing={{ xs: 2, md: 3 }}
              sx={{
                alignItems: { xs: 'flex-start', md: 'flex-start' },
                justifyContent: 'space-between',
              }}
            >
              <Box sx={{ minWidth: 0, flex: 1 }}>
                <Typography variant="h4" sx={{ fontWeight: 700, overflowWrap: 'anywhere' }}>
                  {displayName}
                </Typography>
                <Typography color="text.secondary" sx={{ mt: 0.5 }}>
                  @{username}
                </Typography>
                <Box
                  sx={{
                    mt: 1.25,
                    display: 'inline-flex',
                    px: 1.5,
                    py: 0.5,
                    borderRadius: 999,
                    border: '1px solid',
                    borderColor: 'divider',
                    bgcolor: 'rgba(15, 108, 120, 0.08)',
                    fontWeight: 700,
                  }}
                >
                  {getRoleLabel(primaryRole)}
                </Box>
              </Box>
              <Stack
                direction="row"
                spacing={1.5}
                sx={{
                  alignSelf: { xs: 'flex-start', md: 'flex-start' },
                  flexWrap: 'wrap',
                  pt: { xs: 0, md: 0.25 },
                }}
              >
                <Button
                  variant="contained"
                  startIcon={<EditRoundedIcon />}
                  onClick={() => navigate('/profile/edit')}
                >
                  Modifica profilo
                </Button>
                <Button
                  variant="outlined"
                  color="error"
                  startIcon={<DeleteForeverRoundedIcon />}
                  onClick={() => setDeleteDialogOpen(true)}
                >
                  Elimina account
                </Button>
              </Stack>
            </Stack>
          </Box>
        </Stack>
      </SectionCard>

      <Grid container spacing={3}>
        <Grid size={{ xs: 12, lg: 7 }}>
          <SectionCard title="Dati personali">
            <Grid container spacing={2}>
              {/* Ogni coppia di dati personali produce una card; il layout MUI passa da una a due colonne. */}
              {personalItems.map((item) => (
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
                    <Typography sx={{ fontWeight: 700, overflowWrap: 'anywhere' }}>
                  {item.value}
                    </Typography>
                  </Box>
                </Grid>
              ))}

              {/* Lo stato di verifica viene mostrato soltanto quando il backend espone questa funzionalità. */}
              {showEmailVerificationStatus ? (
                <Grid size={{ xs: 12, sm: 6 }}>
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
                      Stato email
                    </Typography>
                    <Typography sx={{ fontWeight: 700, overflowWrap: 'anywhere' }}>
                      {profile.email_verified ? 'Verificata' : 'Non verificata'}
                    </Typography>
                  </Box>
                </Grid>
              ) : null}

              {/* La nuova email resta separata da quella attuale fino alla verifica della modifica. */}
              {showPendingEmailChange ? (
                <Grid size={{ xs: 12, sm: 6 }}>
                  <Box
                    sx={{
                      height: '100%',
                      display: 'flex',
                      flexDirection: 'column',
                      justifyContent: 'space-between',
                      gap: 1.5,
                      p: 2,
                      borderRadius: 2.5,
                      border: '1px solid',
                      borderColor: 'divider',
                      bgcolor: 'rgba(255,255,255,0.48)',
                    }}
                  >
                    <Box>
                      <Typography variant="body2" color="text.secondary" sx={{ mb: 0.5 }}>
                        Nuova email in attesa di verifica
                      </Typography>
                      <Typography sx={{ fontWeight: 700, overflowWrap: 'anywhere' }}>
                        {profile.pending_email}
                      </Typography>
                    </Box>
                    {profile.email_verification_available ? (
                      <Button variant="outlined" onClick={() => void handleResendVerification()}>
                        Invia nuovamente email di verifica
                      </Button>
                    ) : null}
                  </Box>
                </Grid>
              ) : null}

              {/* La condizione evita di offrire il reinvio ordinario per email già verificata o con modifica pendente. */}
              {showResendVerificationButton ? (
                <Grid size={{ xs: 12, sm: 6 }}>
                  <Box
                    sx={{
                      height: '100%',
                      display: 'flex',
                      alignItems: { xs: 'stretch', sm: 'center' },
                    }}
                  >
                    <Button
                      fullWidth
                      variant="outlined"
                      onClick={() => void handleResendVerification()}
                      sx={{
                        minHeight: 56,
                        justifyContent: { xs: 'center', sm: 'flex-start' },
                      }}
                    >
                      Invia nuovamente email di verifica
                    </Button>
                  </Box>
                </Grid>
              ) : null}
            </Grid>
          </SectionCard>
        </Grid>

        <Grid size={{ xs: 12, lg: 5 }}>
          {/* I pulsanti aprono il selettore file o richiedono la rimozione; isUploadingAvatar ne controlla la disponibilità. */}
          <SectionCard title="Immagine profilo" subtitle="PNG, JPEG o GIF fino a 5 MB">
            <Stack spacing={2}>
              <Typography color="text.secondary" sx={{ minWidth: 0 }}>
                Personalizza il tuo account scegliendo un'immagine profilo. Verrà utilizzata nella barra superiore e nella panoramica del tuo account.
              </Typography>
              <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.25}>
                <Button
                  variant="contained"
                  startIcon={<CameraAltRoundedIcon />}
                  disabled={isUploadingAvatar}
                  onClick={() => avatarInputRef.current?.click()}
                >
                  {profile.avatar_url ? 'Cambia immagine' : 'Carica immagine'}
                </Button>
                {/* La rimozione dell’immagine è proposta soltanto se il profilo segnala un avatar esistente. */}
                {profile.avatar_url ? (
                  <Button
                    variant="outlined"
                    color="inherit"
                    startIcon={<DeleteOutlineRoundedIcon />}
                    disabled={isUploadingAvatar}
                    onClick={() => void handleAvatarDelete()}
                  >
                    Rimuovi immagine
                  </Button>
                ) : null}
                {/* accept filtra la selezione proposta dal browser; la validazione del file inviato compete anche al backend. */}
                <input
                  ref={avatarInputRef}
                  type="file"
                  hidden
                  accept="image/png,image/jpeg,image/gif"
                  onChange={(event) => void handleAvatarChange(event.target.files?.[0] ?? null)}
                />
              </Stack>
            </Stack>
          </SectionCard>
        </Grid>

        <Grid size={{ xs: 12 }}>
          {/* Le statistiche personali usano i conteggi aggregati del profilo, senza scaricare qui tutta la cronologia. */}
          <SectionCard title="Informazioni applicative" subtitle="Statistiche personali delle tue analisi">
            <Grid container spacing={2}>
              {[
                { label: 'Analisi totali', value: profile.statistics.total_analyses },
                { label: 'Completate', value: profile.statistics.completed },
                { label: 'In coda o in elaborazione', value: profile.statistics.queued_or_processing },
                { label: 'Fallite', value: profile.statistics.failed },
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
                    <Typography variant="h4" sx={{ fontWeight: 700 }}>
                      {item.value}
                    </Typography>
                  </Box>
                </Grid>
              ))}
            </Grid>
          </SectionCard>
        </Grid>
      </Grid>

      {/* Il dialog MUI raccoglie una conferma testuale prima di abilitare il pulsante di eliminazione. */}
      <Dialog open={deleteDialogOpen} onClose={() => setDeleteDialogOpen(false)} fullWidth maxWidth="sm">
        {/* Il titolo identifica l’operazione del dialog, distinta dal contenuto della pagina sottostante. */}
        <DialogTitle>Conferma eliminazione account</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ pt: 1 }}>
            <Typography>
              Stai per eliminare definitivamente il tuo account <strong>{profile.username}</strong>.
            </Typography>
            <Typography color="text.secondary">
              Per confermare, digita <strong>ELIMINA</strong> oppure il tuo username.
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
            disabled={!(deleteConfirmation.trim() === 'ELIMINA' || deleteConfirmation.trim() === profile.username)}
            onClick={() => void handleDeleteAccount()}
          >
            Elimina account
          </Button>
        </DialogActions>
      </Dialog>
    </Stack>
  )
}
