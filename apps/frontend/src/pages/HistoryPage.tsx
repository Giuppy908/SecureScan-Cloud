/**
 * Pagina "Cronologia".
 *
 * Elenca le analisi accessibili all'utente autenticato usando paginazione
 * realmente server-side. Il browser invia pagina, page size e filtri; il
 * backend applica RBAC, ricerca e count filtrato e restituisce solo la porzione
 * necessaria.
 *
 * Differenze di ruolo:
 * - analyst: cronologia personale;
 * - admin: cronologia globale con filtro utente.
 *
 * Se nella pagina corrente sono presenti analisi ancora `queued` o
 * `processing`, il polling ricarica quella stessa vista senza perdere filtri o
 * paginazione.
 */
import OpenInNewRoundedIcon from '@mui/icons-material/OpenInNewRounded'
import NavigateBeforeRoundedIcon from '@mui/icons-material/NavigateBeforeRounded'
import NavigateNextRoundedIcon from '@mui/icons-material/NavigateNextRounded'
import SearchRoundedIcon from '@mui/icons-material/SearchRounded'
import { Alert, Box, Button, Grid, IconButton, InputAdornment, MenuItem, Stack, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, TextField, Typography, useMediaQuery, useTheme } from '@mui/material'
// Gli hook React mantengono lo stato visibile, riferimenti alle richieste e callback riutilizzabili tra rendering.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
// I link usano la navigazione React Router, mantenendo l’app caricata quando cambia il percorso.
import { Link as RouterLink } from 'react-router'
// Il context decide se aggiungere il filtro proprietario; l’effettiva visibilità dei record resta decisa dal server.
import { useAuth } from '../auth/useAuth'
import { AnalysisApiError, listAdminUsers, listAnalyses } from '../api/analysisApi'
import { PageHeader } from '../components/PageHeader'
import { RiskChip } from '../components/RiskChip'
import { EmptyState, ErrorState, LoadingState } from '../components/StatePanels'
import { SectionCard } from '../components/SectionCard'
import { StatusChip } from '../components/StatusChip'
// Gli import type descrivono i dati usati dalla pagina e vengono eliminati dal JavaScript prodotto.
import type { AdminUser, AnalysisApiPage, AnalysisStatus, RiskLevel } from '../types/domain'
import {
  formatDateTime,
  getDisplayAnalysisId,
  getPresentationAnalysisStatus,
  hasPendingAnalysisStatus,
} from '../utils/formatters'

// Ricarica i job pendenti ogni 2 secondi; dopo errori consecutivi aumenta l’attesa fino al limite previsto.
const pollingIntervalMs = 2000
const maxPollingErrors = 3
const desktopResultsBreakpoint = 'lg'
const defaultPageSize = 5
// as const conserva i valori letterali delle dimensioni di pagina; la ricerca viene ritardata di 100 millisecondi.
const pageSizeOptions = [5, 10, 20] as const
const searchDebounceMs = 100

const fileNameClampSx = {
  display: '-webkit-box',
  WebkitBoxOrient: 'vertical',
  WebkitLineClamp: 2,
  overflow: 'hidden',
  overflowWrap: 'anywhere',
  wordBreak: 'break-word',
}

function getHistoryRefreshMessage(error: unknown) {
  if (error instanceof AnalysisApiError && (error.status === 500 || error.status === 503)) {
    return 'Aggiornamento temporaneamente non disponibile.'
  }

  return 'Aggiornamento temporaneamente non disponibile.'
}

export function HistoryPage() {
  // Gli hook MUI leggono il tema e scelgono le card sotto lg, mantenendo la tabella sugli schermi più larghi.
  const theme = useTheme()
  const { isAdmin } = useAuth()
  // La media query osserva la larghezza del viewport e sceglie card oppure tabella senza cambiare i dati richiesti.
  const showCardLayout = useMediaQuery(theme.breakpoints.down(desktopResultsBreakpoint))
  // useRef conserva timer, controller e contatori senza causare rendering; servono al ciclo di richieste.
  // Ricorda il timeout pianificato per poterlo cancellare da stopPolling.
  const pollingTimerRef = useRef<number | null>(null)
  // Conserva il controller della lettura corrente per annullarla nel cleanup o prima di una nuova lettura.
  const requestControllerRef = useRef<AbortController | null>(null)
  // Il numero di sequenza identifica l’ultima richiesta avviata senza introdurre uno stato visibile.
  const requestSequenceRef = useRef(0)
  // Conta gli errori consecutivi del ciclo e viene azzerato dopo una risposta valida.
  const pollingErrorCountRef = useRef(0)
  // Mantiene il ricordo del primo caricamento accessibile alle callback asincrone, senza attendere un rendering.
  const hasLoadedOnceRef = useRef(false)

  // useState separa il primo caricamento dagli aggiornamenti, conservando anche pagina, risultati e filtri.
  // Indica il caricamento dei dati iniziali e governa la vista di attesa al posto del contenuto.
  const [isLoading, setIsLoading] = useState(true)
  // Conserva l’errore del caricamento della cronologia, distinto dal messaggio di polling.
  const [loadError, setLoadError] = useState<string | null>(null)
  // Conserva l’avviso dell’ultimo aggiornamento fallito senza cancellare i risultati precedenti.
  const [refreshMessage, setRefreshMessage] = useState<string | null>(null)
  // Ricorda nella UI che una pagina è già stata caricata, evitando di sostituirla con l’attesa a ogni filtro.
  const [hasLoadedOnce, setHasLoadedOnce] = useState(false)
  // Conserva gli account scaricati per alimentare il filtro proprietario della cronologia amministrativa.
  const [adminUsers, setAdminUsers] = useState<AdminUser[]>([])
  // Conserva insieme i record della pagina e i totali restituiti dalla paginazione server.
  const [analysisPage, setAnalysisPage] = useState<AnalysisApiPage>({
    items: [],
    total: 0,
    page: 1,
    page_size: defaultPageSize,
    total_pages: 0,
  })
  // È il testo corrente del campo di ricerca e cambia a ogni digitazione.
  const [query, setQuery] = useState('')
  // È la ricerca inviata alla API dopo il breve ritardo di debounce, distinta dal testo appena digitato.
  const [debouncedQuery, setDebouncedQuery] = useState('')
  // Memorizza all oppure uno stato tecnico del job da trasmettere come filtro.
  const [statusFilter, setStatusFilter] = useState<'all' | AnalysisStatus>('all')
  // Memorizza all oppure il livello di rischio selezionato dall’utente.
  const [riskFilter, setRiskFilter] = useState<'all' | RiskLevel>('all')
  // Memorizza all oppure il subject scelto dall’amministratore per limitare la cronologia.
  const [ownerFilter, setOwnerFilter] = useState<'all' | string>('all')
  // Conserva la pagina richiesta, numerata da 1, e cambia usando i pulsanti di navigazione.
  const [page, setPage] = useState(1)
  // Conserva quanti record chiedere alla API per pagina; modificarlo riporta alla prima pagina.
  const [pageSize, setPageSize] = useState(defaultPageSize)
  // È un contatore di retry: cambiarlo riavvia l’effetto che lo elenca nelle dipendenze.
  const [reloadKey, setReloadKey] = useState(0)

  // useCallback mantiene stabile la funzione che interrompe timer e richiesta durante la pulizia dell’effetto.
  const stopPolling = useCallback(() => {
    if (pollingTimerRef.current !== null) {
      // Rimuove il prossimo controllo pianificato; la richiesta già avviata viene gestita separatamente con abort.
      window.clearTimeout(pollingTimerRef.current)
      pollingTimerRef.current = null
    }

    // Annulla la lettura ancora in corso, se presente, prima di sostituirla o lasciare la pagina.
    requestControllerRef.current?.abort()
    requestControllerRef.current = null
  }, [])

  useEffect(() => {
    // L’effetto carica gli utenti per il filtro proprietario solo per l’admin e si riattiva se cambia isAdmin.
    // Non richiede l’elenco degli account se il filtro per proprietario non è previsto per questo utente.
    if (!isAdmin) {
      return
    }

    // Crea il segnale di annullamento da inoltrare attraverso il client API fino alla fetch.
    const controller = new AbortController()
    // La variabile appartiene a questa esecuzione dell’effetto e viene invalidata dalla relativa pulizia.
    let isMounted = true

    const loadAdminUsers = async () => {
      try {
        // GET amministrativa autenticata: riceve gli account da cui costruire le opzioni del filtro Utente.
        const users = await listAdminUsers(controller.signal)
        // Se questo caricamento dell’elenco utenti è stato annullato, non aggiorna le opzioni del filtro.
        if (!isMounted) {
          return
        }
        // Memorizza gli account ricevuti; availableOwners ne ricaverà quelli con subject e username utilizzabili.
        setAdminUsers(users)
      } catch (error) {
        // L’annullamento è un esito previsto del cambio pagina o dei filtri: questo ramo termina senza feedback di errore.
        if (error instanceof DOMException && error.name === 'AbortError') {
          return
        }
        if (isMounted) {
          // Se fallisce il caricamento degli account, svuota le opzioni invece di bloccare l’intera cronologia.
          setAdminUsers([])
        }
      }
    }

    void loadAdminUsers()

    // React esegue questa pulizia prima di ripetere l’effetto al cambio delle dipendenze e quando smonta il componente.
    return () => {
      // Il cleanup invalida le continuazioni asincrone di questo effetto prima di annullare le attività rimaste.
      isMounted = false
      controller.abort()
    }
  }, [isAdmin])

  useEffect(() => {
    // Il debounce attende una pausa nella digitazione; la pulizia cancella il timer precedente e la ricerca riparte da pagina 1.
    const timeoutId = window.setTimeout(() => {
      setPage((currentPage) => (currentPage === 1 ? currentPage : 1))
      // Applica il testo da usare nella richiesta dopo 100 ms senza nuove variazioni della ricerca.
      setDebouncedQuery((currentValue) => (currentValue === query ? currentValue : query))
    }, searchDebounceMs)

    // React esegue questa pulizia prima di ripetere l’effetto al cambio delle dipendenze e quando smonta il componente.
    return () => {
      // Una nuova digitazione cancella il timeout precedente, così la richiesta segue il testo più recente.
      window.clearTimeout(timeoutId)
    }
  }, [query])

  // L’array di dipendenze riavvia caricamento e pulizia quando cambiano ricerca, filtri, ruolo o paginazione.
  useEffect(() => {
    // La variabile appartiene a questa esecuzione dell’effetto e viene invalidata dalla relativa pulizia.
    let isMounted = true

    // La funzione asincrona invia pagina e filtri alla API e restituisce la pagina ricevuta per decidere il polling.
    const fetchAnalyses = async (showLoader: boolean) => {
      // Annulla la lettura ancora in corso, se presente, prima di sostituirla o lasciare la pagina.
      requestControllerRef.current?.abort()
      // Crea il segnale di annullamento da inoltrare attraverso il client API fino alla fetch.
      const controller = new AbortController()
      // Salva il controller della nuova lettura nel riferimento condiviso con la pulizia.
      requestControllerRef.current = controller
      // La sequenza e isMounted scartano risposte obsolete quando cambiano filtri o la pagina viene smontata.
      // Assegna un numero alla lettura appena avviata: le risposte precedenti saranno riconosciute come obsolete.
      const requestId = ++requestSequenceRef.current

      // Il primo caricamento può sostituire la vista; gli aggiornamenti successivi usano un indicatore meno invasivo.
      if (showLoader) {
        setIsLoading(true)
      }

      try {
        // GET autenticata con pagina e filtri: il backend restituisce solo la porzione richiesta e i totali della ricerca.
        const nextAnalyses = await listAnalyses(
          {
            page,
            pageSize,
            search: debouncedQuery,
            // all viene convertito in undefined per omettere il filtro; un valore selezionato viene inviato senza traduzione.
            status: statusFilter === 'all' ? undefined : statusFilter,
            risk: riskFilter === 'all' ? undefined : riskFilter,
            // Il filtro subject viene inviato soltanto per l’admin e quando non è selezionata l’opzione Tutti.
            owner: isAdmin && ownerFilter !== 'all' ? ownerFilter : undefined,
          },
          controller.signal,
        )
        // Non aggiorna lo stato se l’effetto è terminato o la risposta appartiene a una richiesta superata.
        if (!isMounted || requestId !== requestSequenceRef.current) {
          return null
        }

        // Applica la pagina ricevuta: righe, conteggio risultati e intervallo visibile dipendono da questa risposta.
        setAnalysisPage(nextAnalyses)
        // Se il totale delle pagine si riduce, riallinea la pagina selezionata all’ultima ancora disponibile.
        if (nextAnalyses.total_pages > 0 && page > nextAnalyses.total_pages) {
          setPage(nextAnalyses.total_pages)
        }
        // Al primo successo aggiorna sia il riferimento asincrono sia lo stato usato dal rendering.
        if (!hasLoadedOnceRef.current) {
          hasLoadedOnceRef.current = true
          setHasLoadedOnce(true)
        }
        setLoadError(null)
        // Cancella l’avviso di aggiornamento quando il ciclo riparte o recupera una risposta valida.
        setRefreshMessage(null)
        // Una ripartenza o una risposta valida azzera gli errori accumulati dal ciclo.
        pollingErrorCountRef.current = 0
        // Restituisce i record appena ricevuti anche al ciclo chiamante, che decide se continuare il polling.
        return nextAnalyses
      } catch (error) {
        // L’annullamento è un esito previsto del cambio pagina o dei filtri: questo ramo termina senza feedback di errore.
        if (error instanceof DOMException && error.name === 'AbortError') {
          return null
        }

        // Non aggiorna lo stato se l’effetto è terminato o la risposta appartiene a una richiesta superata.
        if (!isMounted || requestId !== requestSequenceRef.current) {
          return null
        }

        // Il primo caricamento può sostituire la vista; gli aggiornamenti successivi usano un indicatore meno invasivo.
        if (showLoader) {
          // Il fallimento iniziale viene esposto nel pannello con il pulsante Riprova.
          setLoadError(error instanceof Error ? error.message : 'Cronologia non disponibile al momento.')
        } else {
          // Registra un nuovo errore di aggiornamento per limitare i retry e aumentarne il ritardo.
          pollingErrorCountRef.current += 1
          setRefreshMessage(getHistoryRefreshMessage(error))
        }

        return null
      } finally {
        // Soltanto il ciclo ancora attivo e la richiesta più recente possono spegnere gli indicatori di caricamento.
        if (isMounted && requestId === requestSequenceRef.current) {
          // Termina lo stato di caricamento della lettura in questo ramo, consentendo il rendering dei dati o dell’errore.
          setIsLoading(false)
        }
      }
    }

    // Pianifica una sola chiamata futura; il ciclo sceglie il ritardo dopo ogni risposta o errore.
    const schedulePolling = (delayMs: number) => {
      pollingTimerRef.current = window.setTimeout(() => {
        void pollAnalyses()
      }, delayMs)
    }

    // Il polling controlla solo i job della pagina ricevuta; some verifica se almeno uno è ancora pendente.
    const pollAnalyses = async () => {
      // Aggiorna la stessa combinazione di pagina e filtri senza richiedere il loader iniziale.
      const nextAnalyses = await fetchAnalyses(false)
      // Senza una pagina valida non può cercare job pendenti; il ramo valuta soltanto il contatore dei fallimenti.
      if (!isMounted || nextAnalyses === null) {
        // Un errore di refresh può generare un altro tentativo con attesa crescente, finché non si raggiunge il limite.
        if (pollingErrorCountRef.current > 0 && pollingErrorCountRef.current < maxPollingErrors) {
          schedulePolling(pollingIntervalMs * (pollingErrorCountRef.current + 1))
        }
        return
      }

      // some verifica se almeno un record della pagina è queued o processing, condizione necessaria per continuare il ciclo.
      if (nextAnalyses.items.some((analysis) => hasPendingAnalysisStatus(analysis.status))) {
        schedulePolling(pollingIntervalMs)
      }
    }

    const loadInitialAnalyses = async () => {
      // La prima lettura del nuovo effetto usa il loader soltanto se non è mai stata caricata una pagina.
      const nextAnalyses = await fetchAnalyses(!hasLoadedOnceRef.current)
      // Senza una pagina valida non può cercare job pendenti; il ramo valuta soltanto il contatore dei fallimenti.
      if (!isMounted || nextAnalyses === null) {
        return
      }

      // some verifica se almeno un record della pagina è queued o processing, condizione necessaria per continuare il ciclo.
      if (nextAnalyses.items.some((analysis) => hasPendingAnalysisStatus(analysis.status))) {
        schedulePolling(pollingIntervalMs)
      }
    }

    // Avvia subito la lettura; soltanto il risultato stabilisce se pianificare il primo timeout di polling.
    void loadInitialAnalyses()

    // React esegue questa pulizia prima di ripetere l’effetto al cambio delle dipendenze e quando smonta il componente.
    return () => {
      // Il cleanup invalida le continuazioni asincrone di questo effetto prima di annullare le attività rimaste.
      isMounted = false
      stopPolling()
    }
  }, [debouncedQuery, isAdmin, ownerFilter, page, pageSize, reloadKey, riskFilter, statusFilter, stopPolling])

  // useMemo riusa la lista finché adminUsers non cambia; filter restringe il tipo e sort ordina gli username in italiano.
  const availableOwners = useMemo(
    () =>
      adminUsers
        // Il predicato di tipo mantiene gli account con subject e username valorizzati e li rende non opzionali nel risultato.
        .filter((user): user is AdminUser & { subject: string; username: string } => {
          return (
            typeof user.subject === 'string' &&
            Boolean(user.subject) &&
            typeof user.username === 'string' &&
            Boolean(user.username)
          )
        })
        // Ordina la nuova lista filtrata secondo il confronto italiano degli username per rendere il menu consultabile.
        .sort((left, right) => left.username.localeCompare(right.username, 'it')),
    [adminUsers],
  )

  // Estrae i record della pagina corrente senza effettuare una seconda paginazione locale.
  const analyses = analysisPage.items
  // Limita la pagina visualizzata al massimo restituito dal server e usa 1 quando non esistono risultati.
  const currentPage = analysisPage.total_pages > 0 ? Math.min(page, analysisPage.total_pages) : 1
  // Disabilita il comando Indietro quando si è già sulla prima pagina.
  const isPreviousPageDisabled = currentPage <= 1
  // Disabilita il comando Avanti quando non ci sono pagine o si è arrivati all’ultima.
  const isNextPageDisabled = analysisPage.total_pages === 0 || currentPage >= analysisPage.total_pages
  // Memoizza gli indici visualizzati in base a totale, pagina e numero di record, senza ripaginare i dati nel browser.
  const visibleRange = useMemo(() => {
    // Con una lista vuota mostra l’intervallo 0–0 invece di calcolare indici non presenti.
    if (analysisPage.total === 0 || analyses.length === 0) {
      return { start: 0, end: 0 }
    }

    // Converte pagina e dimensione nel numero progressivo del primo elemento mostrato.
    const start = (currentPage - 1) * pageSize + 1
    // Non supera il totale filtrato, neppure quando l’ultima pagina contiene meno elementi del limite.
    const end = Math.min(analysisPage.total, start + analyses.length - 1)

    return { start, end }
  }, [analyses.length, analysisPage.total, currentPage, pageSize])
  // Distingue una cronologia vuota da una ricerca senza corrispondenze per scegliere il messaggio della UI.
  const hasActiveFilters =
    query.trim().length > 0 ||
    statusFilter !== 'all' ||
    riskFilter !== 'all' ||
    (isAdmin && ownerFilter !== 'all')
  // Il blocco JSX collega i controlli della pagina allo stato React, rispettando i limiti restituiti dalla API.
  const paginationControls = (
    <Box
      sx={{
        display: 'grid',
        gap: 1.5,
        alignItems: 'center',
        width: '100%',
        gridTemplateColumns: { xs: '1fr', md: 'minmax(0, 1fr) auto minmax(0, 1fr)' },
      }}
    >
      <Stack
        direction={{ xs: 'column', sm: 'row' }}
        spacing={1}
        sx={{
          alignItems: { xs: 'stretch', sm: 'center' },
          justifyContent: { md: 'flex-start' },
          minWidth: 0,
        }}
      >
        <Typography variant="body2" color="text.secondary">
          Elementi per pagina:
        </Typography>
        <TextField
          select
          size="small"
          value={pageSize}
          onChange={(event) => {
            // Converte il valore testuale del selettore MUI in numero prima di salvarlo nello stato.
            setPageSize(Number(event.target.value))
            // Cambiare dimensione o filtro riporta alla prima pagina, evitando di riutilizzare una posizione non più pertinente.
            setPage(1)
          }}
          sx={{ minWidth: { xs: '100%', sm: 96 } }}
          slotProps={{
            select: {
              'aria-label': 'Elementi per pagina',
            },
          }}
        >
          {pageSizeOptions.map((option) => (
            <MenuItem key={option} value={option}>
              {option}
            </MenuItem>
          ))}
        </TextField>
      </Stack>

      <Stack
        direction="row"
        spacing={0.5}
        sx={{
          justifyContent: 'center',
          alignItems: 'center',
          minWidth: 0,
        }}
      >
        <IconButton
          aria-label="Pagina precedente"
          onClick={() => setPage((currentValue) => Math.max(1, currentValue - 1))}
          disabled={isPreviousPageDisabled}
          size="small"
        >
          <NavigateBeforeRoundedIcon />
        </IconButton>
        <Typography variant="body2" sx={{ fontWeight: 600, whiteSpace: 'nowrap', minWidth: 'fit-content' }}>
          {visibleRange.start} - {visibleRange.end} di {analysisPage.total}
        </Typography>
        <IconButton
          aria-label="Pagina successiva"
          onClick={() =>
            setPage((currentValue) =>
              analysisPage.total_pages > 0
                ? Math.min(analysisPage.total_pages, currentValue + 1)
                : currentValue,
            )
          }
          disabled={isNextPageDisabled}
          size="small"
        >
          <NavigateNextRoundedIcon />
        </IconButton>
      </Stack>

      <Box sx={{ display: { xs: 'none', md: 'block' } }} />
    </Box>
  )

  // Mostra il caricamento a pagina intera soltanto finché manca anche il primo insieme di dati.
  if (isLoading && !hasLoadedOnce) {
    return (
      <LoadingState
        title="Caricamento della Cronologia"
        description="Sto preparando tabella, filtri e collegamenti ai dettagli."
      />
    )
  }

  return (
    <Stack spacing={3} sx={{ minWidth: 0, width: '100%' }}>
      {/* L’intestazione presenta il contesto della pagina e le eventuali azioni passate attraverso le props. */}
      <PageHeader
        title="Cronologia"
        description={
          isAdmin
            ? 'Consulta le analisi effettuate dagli utenti, applica i filtri e apri il dettaglio.'
            : 'Consulta le analisi, filtra per stato e rischio e apri il dettaglio.'
        }
        highlight={`${analysisPage.total} risultati`}
      />

      {/* I campi controllati leggono lo stato React e gli onChange aggiornano i parametri della successiva richiesta. */}
      <SectionCard title="Filtri">
        <Grid container spacing={2} sx={{ minWidth: 0 }}>
          <Grid size={{ xs: 12, md: isAdmin ? 6 : 6 }} sx={{ minWidth: 0 }}>
            <TextField
              fullWidth
              value={query}
              onChange={(event) => {
                setQuery(event.target.value)
              }}
              label="Cerca per nome file o ID"
              slotProps={{
                input: {
                  startAdornment: (
                    <InputAdornment position="start">
                      <SearchRoundedIcon />
                    </InputAdornment>
                  ),
                },
              }}
            />
          </Grid>
          <Grid size={{ xs: 12, sm: 6, md: isAdmin ? 2 : 3 }} sx={{ minWidth: 0 }}>
            <TextField
              select
              fullWidth
              label="Stato"
              value={statusFilter}
              onChange={(event) => {
                setStatusFilter(event.target.value as 'all' | AnalysisStatus)
                // Cambiare dimensione o filtro riporta alla prima pagina, evitando di riutilizzare una posizione non più pertinente.
                setPage(1)
              }}
            >
              <MenuItem value="all">Tutti</MenuItem>
              <MenuItem value="queued">In coda</MenuItem>
              <MenuItem value="processing">Elaborazione</MenuItem>
              <MenuItem value="completed">Completata</MenuItem>
              <MenuItem value="failed">Fallita</MenuItem>
            </TextField>
          </Grid>
          <Grid size={{ xs: 12, sm: 6, md: isAdmin ? 2 : 3 }} sx={{ minWidth: 0 }}>
            <TextField
              select
              fullWidth
              label="Rischio"
              value={riskFilter}
              onChange={(event) => {
                setRiskFilter(event.target.value as 'all' | RiskLevel)
                // Cambiare dimensione o filtro riporta alla prima pagina, evitando di riutilizzare una posizione non più pertinente.
                setPage(1)
              }}
            >
              <MenuItem value="all">Tutti</MenuItem>
              <MenuItem value="low">Basso</MenuItem>
              <MenuItem value="medium">Medio</MenuItem>
              <MenuItem value="high">Alto</MenuItem>
              <MenuItem value="critical">Critico</MenuItem>
            </TextField>
          </Grid>
          {isAdmin ? (
            <Grid size={{ xs: 12, sm: 6, md: 2 }} sx={{ minWidth: 0 }}>
              <TextField
                select
                fullWidth
                label="Utente"
                value={ownerFilter}
                onChange={(event) => {
                  setOwnerFilter(event.target.value)
                  // Cambiare dimensione o filtro riporta alla prima pagina, evitando di riutilizzare una posizione non più pertinente.
                  setPage(1)
                }}
              >
                <MenuItem value="all">Tutti gli utenti</MenuItem>
                {/* Ogni account valido diventa un’opzione con subject come valore e username come etichetta. */}
                {availableOwners.map((owner) => (
                  <MenuItem key={owner.subject} value={owner.subject}>
                    {owner.username}
                  </MenuItem>
                ))}
              </TextField>
            </Grid>
          ) : null}
        </Grid>
      </SectionCard>

      {/* Il pannello espone l’errore della cronologia e il retry incrementa reloadKey per ripetere la lettura. */}
      {loadError ? (
        <ErrorState
          title="Cronologia non disponibile"
          description={loadError}
          actionLabel="Riprova"
          onRetry={() => setReloadKey((currentValue) => currentValue + 1)}
        />
      ) : null}

      <SectionCard title="Risultati" subtitle="Accesso diretto al dettaglio di ogni analisi">
        <Stack spacing={2} sx={{ minWidth: 0, width: '100%' }}>
          {/* Mostra un avviso per l’aggiornamento lasciando disponibili i dati dell’ultima lettura riuscita. */}
          {refreshMessage ? <Alert severity="warning">{refreshMessage}</Alert> : null}
          {/* Se la pagina non contiene record mostra uno stato vuoto coerente con la presenza dei filtri. */}
          {analyses.length === 0 ? (
            <EmptyState
              title={hasActiveFilters ? 'Nessun risultato' : 'Nessuna analisi disponibile'}
              description={
                hasActiveFilters
                  ? 'Modifica ricerca o filtri per visualizzare nuove analisi.'
                  : 'Avvia una nuova analisi per popolare la cronologia locale.'
              }
            />
          ) : (
            <>
              {/* Le stesse analisi vengono rese come card o tabella; map usa analysis.id come chiave stabile. */}
              {showCardLayout ? (
                <Stack spacing={2} sx={{ minWidth: 0, width: '100%' }}>
                  {/* Ogni record produce una card o una riga identificata da analysis.id; i link mantengono l’ID originale. */}
                  {analyses.map((analysis) => (
                    <Box
                      key={analysis.id}
                      sx={{
                        minWidth: 0,
                        width: '100%',
                        borderRadius: 2.5,
                        border: '1px solid rgba(215, 224, 230, 0.9)',
                        bgcolor: 'rgba(251, 253, 254, 0.95)',
                        px: 2,
                        py: 2,
                      }}
                    >
                      <Stack spacing={1.75} sx={{ minWidth: 0 }}>
                        <Box sx={{ minWidth: 0 }}>
                          <Typography
                            title={analysis.file_name}
                            sx={{
                              fontWeight: 700,
                              minWidth: 0,
                              maxWidth: '100%',
                              ...fileNameClampSx,
                              WebkitLineClamp: 3,
                            }}
                          >
                            {analysis.file_name}
                          </Typography>
                          <Typography
                            variant="body2"
                            color="text.secondary"
                            sx={{ mt: 0.5, overflowWrap: 'anywhere' }}
                          >
                            ID analisi: {getDisplayAnalysisId(analysis.id)}
                          </Typography>
                        </Box>

                        <Grid container spacing={1.5} sx={{ minWidth: 0 }}>
                          <Grid size={{ xs: 12, sm: 6 }} sx={{ minWidth: 0 }}>
                            <Typography variant="caption" color="text.secondary">
                              Data
                            </Typography>
                            <Typography variant="body2">{formatDateTime(analysis.created_at)}</Typography>
                          </Grid>
                          <Grid size={{ xs: 12, sm: 6 }} sx={{ minWidth: 0 }}>
                            <Typography variant="caption" color="text.secondary">
                              Inviato da
                            </Typography>
                            <Typography variant="body2">{analysis.owner_username ?? 'Non disponibile'}</Typography>
                          </Grid>
                        </Grid>

                        <Stack
                          direction="row"
                          spacing={1}
                          sx={{ flexWrap: 'wrap', alignItems: 'center', minWidth: 0 }}
                        >
                          <StatusChip status={getPresentationAnalysisStatus(analysis)} />
                          <RiskChip risk={analysis.risk_level} />
                          <Box sx={{ flexGrow: 1 }} />
                          <Button
                            size="small"
                            component={RouterLink}
                            to={`/analyses/${analysis.id}`}
                            endIcon={<OpenInNewRoundedIcon />}
                            sx={{ minWidth: 88, flexShrink: 0 }}
                          >
                            Apri
                          </Button>
                        </Stack>
                      </Stack>
                    </Box>
                  ))}
                </Stack>
              ) : (
                <TableContainer sx={{ width: '100%', minWidth: 0, overflowX: 'hidden' }}>
                  <Table size="medium" sx={{ width: '100%', tableLayout: 'fixed' }}>
                    {/* L’intestazione descrive il significato delle colonne condiviso da tutte le righe della tabella. */}
                    <TableHead>
                      <TableRow>
                        <TableCell sx={{ width: '36%' }}>File</TableCell>
                        <TableCell sx={{ width: '10%' }}>Utente</TableCell>
                        <TableCell sx={{ width: '18%' }}>Data</TableCell>
                        <TableCell sx={{ width: '14%' }}>Stato</TableCell>
                        <TableCell sx={{ width: '12%' }}>Rischio</TableCell>
                        <TableCell align="center" sx={{ width: '10%' }}>
                          Dettaglio
                        </TableCell>
                      </TableRow>
                    </TableHead>
                    {/* Il corpo contiene le righe generate dai dati correnti; le chiavi permettono a React di riconoscerle. */}
                    <TableBody>
                      {/* Ogni record produce una card o una riga identificata da analysis.id; i link mantengono l’ID originale. */}
                      {analyses.map((analysis) => (
                        <TableRow key={analysis.id} hover>
                          <TableCell sx={{ verticalAlign: 'top' }}>
                            <Box sx={{ minWidth: 0, maxWidth: '100%' }}>
                              <Typography
                                title={analysis.file_name}
                                sx={{
                                  fontWeight: 700,
                                  minWidth: 0,
                                  maxWidth: '100%',
                                  ...fileNameClampSx,
                                }}
                              >
                                {analysis.file_name}
                              </Typography>
                              <Typography
                                variant="body2"
                                color="text.secondary"
                                sx={{ mt: 0.5, overflowWrap: 'anywhere' }}
                              >
                                ID analisi: {getDisplayAnalysisId(analysis.id)}
                              </Typography>
                            </Box>
                          </TableCell>
                          <TableCell sx={{ verticalAlign: 'top' }}>{analysis.owner_username ?? 'Non disponibile'}</TableCell>
                          <TableCell sx={{ verticalAlign: 'top' }}>
                            {formatDateTime(analysis.created_at)}
                          </TableCell>
                          <TableCell sx={{ verticalAlign: 'top' }}>
                            <StatusChip status={getPresentationAnalysisStatus(analysis)} />
                          </TableCell>
                          <TableCell sx={{ verticalAlign: 'top' }}>
                            <RiskChip risk={analysis.risk_level} />
                          </TableCell>
                          <TableCell align="center" sx={{ verticalAlign: 'top' }}>
                            <Button
                              size="small"
                              component={RouterLink}
                              to={`/analyses/${analysis.id}`}
                              endIcon={<OpenInNewRoundedIcon />}
                              sx={{ minWidth: 88 }}
                            >
                              Apri
                            </Button>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </TableContainer>
              )}

            </>
          )}
          {/* Mostra i controlli preparati sopra usando i totali della risposta, anche quando la lista è vuota. */}
          {paginationControls}
        </Stack>
      </SectionCard>
    </Stack>
  )
}
