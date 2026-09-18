/**
 * Pagina "Amministrazione".
 *
 * Mostra agli admin una vista globale sugli utenti e alcune metriche aggregate
 * della piattaforma. La pagina è importante per comprendere come il frontend
 * differenzi l'esperienza analyst/admin senza spostare sul browser i controlli
 * di autorizzazione reali.
 */
import RefreshRoundedIcon from '@mui/icons-material/RefreshRounded'
import VisibilityRoundedIcon from '@mui/icons-material/VisibilityRounded'
import {
  Alert,
  Avatar,
  Box,
  Button,
  Chip,
  Grid,
  MenuItem,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from '@mui/material'
// Gli hook React mantengono lo stato visibile, riferimenti alle richieste e callback riutilizzabili tra rendering.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
// I link usano la navigazione React Router, mantenendo l’app caricata quando cambia il percorso.
import { Link as RouterLink } from 'react-router'
import { AnalysisApiError, getDashboardSnapshot, listAdminUsers } from '../api/analysisApi'
import { PageHeader } from '../components/PageHeader'
import { SectionCard } from '../components/SectionCard'
import { EmptyState, LoadingState } from '../components/StatePanels'
// Gli import type descrivono i dati usati dalla pagina e vengono eliminati dal JavaScript prodotto.
import type { AdminUser, DashboardSnapshot } from '../types/domain'

// L’interfaccia riunisce riepilogo della piattaforma ed elenco utenti nello stato della pagina.
interface AdminViewState {
  dashboard: DashboardSnapshot
  users: AdminUser[]
}

// La union della severità limita i tipi di messaggio supportati dalla UI amministrativa.
interface TimedFeedback {
  message: string
  severity: 'success' | 'info' | 'warning'
}

// Distingue errori di sessione e permesso e conserva il messaggio API per gli altri fallimenti.
function getAdminErrorMessage(error: unknown) {
  if (error instanceof AnalysisApiError) {
    // Il messaggio distingue una sessione non più valida dagli errori dell’area utenti.
    if (error.status === 401) {
      return "La sessione non è più valida. Effettua nuovamente l'accesso."
    }
    // Segnala un accesso negato dal server, anche se la pagina è protetta da una guardia frontend.
    if (error.status === 403) {
      return "Non hai i permessi per visualizzare l'area amministrativa."
    }
    // Per gli altri errori del client conserva il messaggio ricevuto quando non è vuoto.
    if (error.message.trim()) {
      return error.message
    }
  }

  return "L'area amministrativa non è temporaneamente disponibile."
}

// Il nullish coalescing sceglie subject, id o username disponibili per costruire il collegamento al dettaglio.
function getAdminUserSubject(user: AdminUser) {
  // Sceglie il primo identificativo non nullo tra subject, id e username per costruire il percorso del dettaglio.
  return user.subject ?? user.id ?? user.username ?? ''
}

export function AdminPage() {
  // useRef conserva controller e contatore delle richieste tra rendering senza aggiornare la UI.
  // Conserva il controller della lettura corrente per annullarla nel cleanup o prima di una nuova lettura.
  const requestControllerRef = useRef<AbortController | null>(null)
  // Il numero di sequenza identifica l’ultima richiesta avviata senza introdurre uno stato visibile.
  const requestSequenceRef = useRef(0)

  // useState mantiene dati, caricamento e filtri controllati della tabella utenti.
  // Indica il caricamento dei dati iniziali e governa la vista di attesa al posto del contenuto.
  const [isLoading, setIsLoading] = useState(true)
  // Indica una lettura di aggiornamento, così la UI può mostrare attesa mantenendo i dati già caricati.
  const [isRefreshing, setIsRefreshing] = useState(false)
  // Conserva gli snapshot necessari alla vista; null indica che non è ancora disponibile un caricamento riuscito.
  const [data, setData] = useState<AdminViewState | null>(null)
  // Conserva il messaggio di errore della lettura per mostrare il pannello o l’avviso della pagina.
  const [error, setError] = useState<string | null>(null)
  // Contiene il risultato delle operazioni utente da mostrare in un Alert, separato dall’errore di lettura.
  const [feedback, setFeedback] = useState<TimedFeedback | null>(null)
  // Conserva il testo usato per filtrare gli utenti già scaricati nel browser.
  const [searchValue, setSearchValue] = useState('')
  // Conserva il ruolo da mostrare nella lista utenti oppure all per non applicare il filtro.
  const [roleFilter, setRoleFilter] = useState<'all' | 'admin' | 'analyst'>('all')

  // useEffect nasconde i feedback non warning dopo 5 secondi; la dipendenza feedback riavvia il timer e il return lo cancella.
  useEffect(() => {
    // Non nasconde automaticamente gli avvisi warning; gli altri feedback possono scadere dopo il timeout.
    if (!feedback || feedback.severity === 'warning') {
      return
    }

    // Pianifica un’attività cancellabile; un timeout non ripete automaticamente l’operazione come un intervallo.
    const timer = window.setTimeout(() => {
      // Il timer rimuove soltanto il feedback per cui è stato pianificato.
      setFeedback((current) => (current === feedback ? null : current))
    }, 5000)

    return () => window.clearTimeout(timer)
  }, [feedback])

  // useCallback mantiene stabile il caricamento e annulla la precedente richiesta prima di aggiornare la vista.
  const loadAdminData = useCallback(async (showLoader: boolean) => {
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
      // Promise.all attende insieme dashboard ed elenco utenti; se una lettura fallisce il blocco entra nel catch.
      const [dashboard, users] = await Promise.all([
        // GET autenticata dei totali della piattaforma nel perimetro autorizzato dell’amministratore.
        getDashboardSnapshot(controller.signal),
        // GET amministrativa degli account che alimentano conteggi e tabella della pagina.
        listAdminUsers(controller.signal),
      ])

      // Non applica un risultato ormai superato da una lettura più recente.
      if (requestId !== requestSequenceRef.current) {
        return
      }

      // Applica insieme riepilogo e utenti solo quando entrambe le richieste sono riuscite.
      setData({ dashboard, users })
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
      // Conserva il messaggio dell’errore mantenendo l’eventuale snapshot precedente.
      setError(getAdminErrorMessage(nextError))
    } finally {
      // Il finally aggiorna gli indicatori solo per la richiesta corrente, senza interferire con una lettura successiva.
      if (requestId === requestSequenceRef.current) {
        // Termina lo stato di caricamento della lettura in questo ramo, consentendo il rendering dei dati o dell’errore.
        setIsLoading(false)
        // Spegne l’indicatore di aggiornamento dopo il completamento della richiesta corrente.
        setIsRefreshing(false)
      }
    }
  }, [])

  // Carica i dati al montaggio; la pulizia annulla il timer iniziale e l’eventuale richiesta quando la pagina si smonta.
  useEffect(() => {
    // Pianifica un’attività cancellabile; un timeout non ripete automaticamente l’operazione come un intervallo.
    const timer = window.setTimeout(() => {
      // Il timeout dell’effetto avvia il caricamento iniziale; il pulsante Aggiorna richiama la stessa callback.
      void loadAdminData(true)
    }, 0)

    // React esegue questa pulizia prima di ripetere l’effetto al cambio delle dipendenze e quando smonta il componente.
    return () => {
      window.clearTimeout(timer)
      // Annulla la lettura ancora in corso, se presente, prima di sostituirla o lasciare la pagina.
      requestControllerRef.current?.abort()
    }
  }, [loadAdminData])

  // Deriva il numero di account dalla lista scaricata e usa zero prima della risposta.
  const usersCount = data?.users.length ?? 0
  // useMemo ricalcola i conteggi solo al cambio degli utenti; filter seleziona gli account con ruolo admin.
  const adminsCount = useMemo(
    // Il conteggio memoizzato include gli utenti la cui lista roles contiene admin.
    () => data?.users.filter((user) => (user.roles ?? []).includes('admin')).length ?? 0,
    [data?.users],
  )
  // La ricerca e il filtro ruolo lavorano sulla lista già scaricata, senza inviare una query per ogni digitazione.
  const filteredUsers = useMemo(() => {
    // Elimina gli spazi esterni e converte la ricerca in minuscolo per il confronto locale.
    const normalizedQuery = searchValue.trim().toLowerCase()
    // Prima della risposta usa una lista vuota; poi verifica ruolo e testo per ogni account ricevuto.
    return (data?.users ?? []).filter((user) => {
      // I ruoli possono essere opzionali nel tipo AdminUser: una lista vuota consente controlli sicuri con includes.
      const roles = user.roles ?? []
      // all accetta ogni ruolo; altrimenti richiede che la lista dell’account contenga il ruolo selezionato.
      const matchesRole = roleFilter === 'all' || roles.includes(roleFilter)
      // Esclude subito gli account che non soddisfano il filtro ruolo, senza controllarne il testo.
      if (!matchesRole) {
        return false
      }

      // Quando non c’è ricerca testuale conserva tutti gli account già ammessi dal filtro ruolo.
      if (!normalizedQuery) {
        return true
      }

      // Unisce username, nome, cognome ed email in un testo ricercabile ignorando i campi assenti.
      const haystack = [user.username, user.first_name, user.last_name, user.email]
        .filter(Boolean)
        .join(' ')
        .toLowerCase()

      // Mantiene l’account se il testo normalizzato contiene la sottostringa cercata.
      return haystack.includes(normalizedQuery)
    })
  }, [data?.users, roleFilter, searchValue])

  // Mostra il caricamento a pagina intera soltanto finché manca anche il primo insieme di dati.
  if (isLoading && data === null) {
    return (
      <LoadingState
        title="Preparazione dell'area amministrativa"
        description="Sto caricando utenti reali, ruoli e riepilogo della piattaforma."
      />
    )
  }

  // Senza una risposta completa rende disponibile il retry al posto della tabella.
  if (data === null) {
    return (
      <EmptyState
        title="Area amministrativa non disponibile"
        description={error ?? 'I dati amministrativi reali non sono disponibili.'}
        action={
          <Button variant="contained" onClick={() => void loadAdminData(true)}>
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
        title="Amministrazione"
        description="Gestisci utenti, ruoli e stato degli account attraverso dati reali della piattaforma."
        action={
          <Button
            variant="outlined"
            startIcon={<RefreshRoundedIcon />}
            disabled={isRefreshing}
            onClick={() => void loadAdminData(false)}
          >
            Aggiorna
          </Button>
        }
        highlight="Solo admin"
      />

      {/* Un errore successivo al caricamento viene mostrato insieme ai dati già disponibili. */}
      {error ? <Alert severity="warning">{error}</Alert> : null}
      {/* Il feedback visualizza l’esito dell’azione dell’utente quando lo stato contiene un messaggio. */}
      {feedback ? <Alert severity={feedback.severity}>{feedback.message}</Alert> : null}

      <Grid container spacing={2}>
        {[
          { label: 'Utenti registrati', value: usersCount },
          { label: 'Amministratori', value: adminsCount },
          { label: 'Analisi totali', value: data.dashboard.summary.total_analyses },
          { label: 'Analisi fallite', value: data.dashboard.summary.failed },
        ].map((metric) => (
          <Grid key={metric.label} size={{ xs: 12, sm: 6, xl: 3 }}>
            <Box
              sx={{
                pl: 3,
                pr: 2,
                py: 1.5,
                borderRadius: 3,
                border: '1px solid',
                borderColor: 'divider',
                bgcolor: 'background.paper',
                minHeight: 98,
                display: 'flex',
                alignItems: 'center',
                gap: 2.75,
              }}
            >
              <Typography variant="h3" sx={{ minWidth: 78, pl: 0.75, fontSize: '3.15rem', fontWeight: 700, lineHeight: 1 }}>
                {metric.value}
              </Typography>
              <Typography sx={{ fontSize: '1.15rem', lineHeight: 1.35, fontWeight: 600 }}>
                {metric.label}
              </Typography>
            </Box>
          </Grid>
        ))}
      </Grid>

      {/* Ricerca e selettore ruolo filtrano localmente la lista, senza una GET per ogni modifica del campo. */}
      <SectionCard title="Utenti" subtitle="Account reali provenienti da Keycloak con riepilogo essenziale e accesso al dettaglio">
        <Grid container spacing={2} sx={{ mb: 2 }}>
          <Grid size={{ xs: 12, md: 8 }}>
            <TextField
              fullWidth
              label="Cerca utenti"
              placeholder="Username, nome, cognome o email"
              value={searchValue}
              onChange={(event) => setSearchValue(event.target.value)}
            />
          </Grid>
          <Grid size={{ xs: 12, md: 4 }}>
            <TextField
              select
              fullWidth
              label="Ruolo"
              value={roleFilter}
              onChange={(event) => setRoleFilter(event.target.value as 'all' | 'admin' | 'analyst')}
            >
              <MenuItem value="all">Tutti i ruoli</MenuItem>
              <MenuItem value="admin">Amministratori</MenuItem>
              <MenuItem value="analyst">Analisti</MenuItem>
            </TextField>
          </Grid>
        </Grid>

        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          {filteredUsers.length} utenti mostrati su {data.users.length}.
        </Typography>

        {/* La tabella MUI mantiene una larghezza minima e permette lo scorrimento orizzontale nei contenitori più stretti. */}
        {/* Nessuna corrispondenza mostra lo stato vuoto; la lista originale resta conservata in data.users. */}
        {filteredUsers.length === 0 ? (
          <EmptyState
            title="Nessun utente corrisponde ai filtri"
            description="Modifica ricerca o ruolo per visualizzare gli account disponibili."
          />
        ) : (
          <TableContainer sx={{ width: '100%', minWidth: 0, overflowX: 'auto' }}>
            <Table size="medium" sx={{ minWidth: 920 }}>
              {/* L’intestazione descrive il significato delle colonne condiviso da tutte le righe della tabella. */}
              <TableHead>
                <TableRow>
                  <TableCell sx={{ width: '26%' }}>Utente</TableCell>
                  <TableCell sx={{ width: '24%' }}>Email</TableCell>
                  <TableCell sx={{ width: '14%' }}>Ruolo</TableCell>
                  <TableCell sx={{ width: '14%' }}>Stato account</TableCell>
                  <TableCell sx={{ width: '10%' }}>Analisi</TableCell>
                  <TableCell sx={{ width: '12%' }}>Azione</TableCell>
                </TableRow>
              </TableHead>
              {/* Il corpo contiene le righe generate dai dati correnti; le chiavi permettono a React di riconoscerle. */}
              <TableBody>
                {/* map costruisce le righe con avatar, ruolo e stato; il collegamento codifica il subject nel percorso React. */}
                {filteredUsers.map((user) => {
                  // Deriva l’identificativo usato sia come chiave React sia nel collegamento al dettaglio.
                  const subject = getAdminUserSubject(user)
                  // I ruoli possono essere opzionali nel tipo AdminUser: una lista vuota consente controlli sicuri con includes.
                  const roles = user.roles ?? []
                  // Per l’etichetta della riga dà priorità ad admin quando l’account possiede entrambi i ruoli.
                  const primaryRole = roles.includes('admin') ? 'admin' : 'analyst'
                  // Unisce nome e cognome e ricade sullo username o sul testo di riserva se mancano.
                  const fullName =
                    [user.first_name, user.last_name].filter(Boolean).join(' ').trim() || user.username || 'Utente'

                  return (
                    <TableRow key={subject} hover>
                      <TableCell>
                        <Stack direction="row" spacing={1.25} sx={{ alignItems: 'center' }}>
                          {/* Mostra l’immagine ricevuta oppure l’iniziale del nome scelto per la riga. */}
                          <Avatar src={user.avatar_data_url ?? undefined} sx={{ bgcolor: 'secondary.main' }}>
                            {fullName.charAt(0).toUpperCase()}
                          </Avatar>
                          <Box sx={{ minWidth: 0 }}>
                            <Typography sx={{ fontWeight: 700, overflowWrap: 'anywhere' }} title={fullName}>
                              {fullName}
                            </Typography>
                            <Typography
                              variant="body2"
                              color="text.secondary"
                              sx={{ overflowWrap: 'anywhere' }}
                              title={user.username ?? 'utente'}
                            >
                              {user.username ?? 'utente'}
                            </Typography>
                          </Box>
                        </Stack>
                      </TableCell>
                      <TableCell sx={{ overflowWrap: 'anywhere' }}>{user.email ?? 'Non disponibile'}</TableCell>
                      <TableCell>
                        {/* Il badge presenta ruolo o abilitazione dell’account attraverso etichetta, colore e variante. */}
                        <Chip
                          size="small"
                          label={primaryRole === 'admin' ? 'Amministratore' : 'Analista'}
                          color={primaryRole === 'admin' ? 'primary' : 'default'}
                          variant={primaryRole === 'admin' ? 'filled' : 'outlined'}
                        />
                      </TableCell>
                      <TableCell>
                        {/* Il badge presenta ruolo o abilitazione dell’account attraverso etichetta, colore e variante. */}
                        <Chip
                          size="small"
                          label={user.enabled ? 'Attivo' : 'Disabilitato'}
                          color={user.enabled ? 'success' : 'default'}
                          variant={user.enabled ? 'filled' : 'outlined'}
                        />
                      </TableCell>
                      {/* Il conteggio delle analisi viene dal riepilogo utente, con zero come valore di riserva. */}
                      <TableCell>{user.analysis_count ?? 0}</TableCell>
                      <TableCell>
                        <Button
                          size="small"
                          variant="outlined"
                          component={RouterLink}
                          to={`/admin/users/${encodeURIComponent(subject)}`}
                          startIcon={<VisibilityRoundedIcon />}
                        >
                          Dettaglio
                        </Button>
                      </TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>
          </TableContainer>
        )}
      </SectionCard>
    </Stack>
  )
}
