/**
 * Pagina "Dettaglio analisi".
 *
 * È la vista più completa sul risultato di una scansione: metadati strutturali,
 * esito complessivo, risultati ClamAV, risultati YARA, indicatori e timeline.
 * La pagina viene aperta principalmente da Cronologia e può effettuare polling
 * mentre il job non è ancora stabilizzato.
 *
 * Anche se il frontend mostra o nasconde elementi in base al ruolo, la
 * protezione reale di ownership e RBAC viene applicata dal backend.
 */
import ArrowBackRoundedIcon from '@mui/icons-material/ArrowBackRounded'
import { Alert, Box, Button, CircularProgress, Divider, Grid, List, ListItem, ListItemText, Stack, Typography } from '@mui/material'
// Gli hook React mantengono lo stato visibile, riferimenti alle richieste e callback riutilizzabili tra rendering.
import { useCallback, useEffect, useRef, useState } from 'react'
// I link usano la navigazione React Router, mantenendo l’app caricata quando cambia il percorso.
import { Link as RouterLink, useParams } from 'react-router'
// La GET del dettaglio fornisce risultati e metadati; gli errori tipizzati permettono di riconoscere il 404.
import { AnalysisApiError, getAnalysis } from '../api/analysisApi'
import { PageHeader } from '../components/PageHeader'
import { RiskChip } from '../components/RiskChip'
import { SectionCard } from '../components/SectionCard'
import { ErrorState, LoadingState } from '../components/StatePanels'
import { StatusChip } from '../components/StatusChip'
// Gli import type descrivono i dati usati dalla pagina e vengono eliminati dal JavaScript prodotto.
import type { AnalysisApiRecord } from '../types/domain'
import {
  formatBytesToLabel,
  formatDateTime,
  getPresentationAnalysisStatus,
  formatEntropy,
  formatExtensionMatch,
  formatMimeType,
  formatSha256,
  getDisplayAnalysisId,
  hasPendingAnalysisStatus,
} from '../utils/formatters'

// Il dettaglio controlla il job ogni secondo mentre è pendente, con limite di tre errori consecutivi.
const pollingIntervalMs = 1000
const maxPollingErrors = 3

function formatIndicatorMessage(indicator: string) {
  /**
   * Traduce in italiano gli indicatori testuali oggi prodotti dal backend.
   *
   * La trasformazione è solo di presentazione: il contratto API resta invariato
   * e il fallback conserva il messaggio originale se arriva un indicatore non
   * ancora mappato dal frontend.
   */
  // La regex cerca il messaggio di disallineamento prodotto dalla API e ne cattura estensione e MIME.
  const extensionMismatchMatch = indicator.match(
    /^Extension '(.+)' does not match the inferred MIME type '(.+)'\.$/,
  )
  // Se il formato testuale è riconosciuto, usa i gruppi catturati per costruire la traduzione italiana.
  if (extensionMismatchMatch) {
    // Il destructuring salta il match completo e legge soltanto i due gruppi utili al messaggio.
    const [, extension, mimeType] = extensionMismatchMatch
    return `L'estensione '${extension}' non corrisponde al tipo MIME rilevato '${mimeType}'.`
  }

  // Riconosce l’indicatore che associa l’entropia elevata a un formato compatibile con contenuti compressi.
  const highEntropyCompatibleMatch = indicator.match(
    /^High entropy \((\d+(?:\.\d+)?)\) is compatible with compressed content in this file format\.$/,
  )
  if (highEntropyCompatibleMatch) {
    // Estrae dalla corrispondenza il valore numerico già presente nel messaggio, senza ricalcolare l’entropia.
    const [, entropy] = highEntropyCompatibleMatch
    return `Un'entropia elevata (${entropy}) è compatibile con contenuto compresso per questo formato di file.`
  }

  // Riconosce invece l’indicatore di possibile compressione o offuscamento da sottoporre a verifica.
  const highEntropySuspiciousMatch = indicator.match(
    /^High entropy \((\d+(?:\.\d+)?)\) may indicate compressed or obfuscated content\.$/,
  )
  if (highEntropySuspiciousMatch) {
    // Estrae dalla corrispondenza il valore numerico già presente nel messaggio, senza ricalcolare l’entropia.
    const [, entropy] = highEntropySuspiciousMatch
    return `Un'entropia elevata (${entropy}) può indicare contenuto compresso o offuscato.`
  }

  // Questa traduzione richiede il testo esatto dell’indicatore relativo a un file eseguibile.
  if (indicator === 'Executable file format detected; treat with caution because this service does not execute the file.') {
    return "Rilevato un formato di file eseguibile; trattalo con cautela perché questo servizio non esegue il file."
  }

  // Cattura il tipo MIME nel messaggio che segnala un formato insolito per documenti utente.
  const uncommonMimeMatch = indicator.match(/^MIME type '(.+)' is uncommon for end-user documents\.$/)
  if (uncommonMimeMatch) {
    const [, mimeType] = uncommonMimeMatch
    return `Il tipo MIME '${mimeType}' è insolito per un documento destinato all'utente finale.`
  }

  // Conserva il testo originale quando nessuna traduzione riconosce l’indicatore ricevuto.
  return indicator
}

// Dà priorità agli errori di scansione e del job prima di descrivere attesa, elaborazione o indicatori.
function getAnalysisDescription(analysis: AnalysisApiRecord) {
  // L’errore del motore di scansione prevale nella descrizione anche se lo stato tecnico è completed.
  if (analysis.verdict === 'scan_error') {
    return 'La scansione antimalware non è stata completata correttamente.'
  }

  if (analysis.status === 'failed') {
    return analysis.error_message || "L'analisi non è stata completata correttamente."
  }

  // Mostra attesa dei risultati per il job accettato ma ancora in coda.
  if (analysis.status === 'queued') {
    return "Il file è in coda. I risultati saranno disponibili al termine dell'elaborazione."
  }

  // Informa che il risultato non è definitivo e sarà aggiornato dalle letture successive.
  if (analysis.status === 'processing') {
    return "L'analisi è in elaborazione. I risultati vengono aggiornati automaticamente."
  }

  if (analysis.indicators.length === 0) {
    return 'Nessun indicatore rilevante restituito da questa prima versione locale.'
  }

  return 'Indicatori preliminari disponibili per una verifica manuale del file.'
}

// Traduce clean, suspicious, malicious e scan_error senza dedurre un esito dai soli metadati.
function getVerdictLabel(analysis: AnalysisApiRecord) {
  // Seleziona l’etichetta del verdetto antimalware, distinta dallo stato del job e dal livello di rischio.
  switch (analysis.verdict) {
    case 'clean':
      return 'Pulito'
    case 'suspicious':
      return 'Sospetto'
    case 'malicious':
      return 'Malevolo'
    case 'scan_error':
      return 'Errore di scansione'
    default:
      return analysis.status === 'completed' ? 'Non disponibile' : 'In attesa'
  }
}

// Distingue l’esito ClamAV dai suoi errori, timeout e indisponibilità.
function getClamAvLabel(analysis: AnalysisApiRecord) {
  // Traduce gli esiti del motore ClamAV, inclusi timeout e indisponibilità.
  switch (analysis.clamav_status) {
    case 'clean':
      return 'Pulito'
    case 'found':
      return 'Minaccia rilevata'
    case 'error':
      return 'Errore di scansione'
    case 'timeout':
      return 'Timeout di scansione'
    case 'unavailable':
      return 'Servizio non disponibile'
    default:
      return analysis.status === 'completed' ? 'Non disponibile' : 'In attesa'
  }
}

// Conta le regole YARA corrispondenti quando matched e distingue assenza di match da errore del motore.
function getYaraLabel(analysis: AnalysisApiRecord) {
  // Quando YARA segnala corrispondenze, la descrizione usa il numero di regole presenti nella risposta.
  if (analysis.yara_status === 'matched') {
    // Conta le regole ricevute per scegliere singolare o plurale nell’etichetta.
    const count = analysis.yara_matches.length
    return count === 1 ? '1 corrispondenza' : `${count} corrispondenze`
  }

  // Per gli altri esiti distingue nessun match, errore del motore e risultato non ancora disponibile.
  switch (analysis.yara_status) {
    case 'clean':
      return 'Nessuna corrispondenza'
    case 'error':
      return 'Errore di scansione'
    case 'unavailable':
      return 'Motore non disponibile'
    default:
      return analysis.status === 'completed' ? 'Non disponibile' : 'In attesa'
  }
}

// Sceglie un messaggio per il fallimento di un aggiornamento, distinto dall’errore del primo caricamento.
function getDetailRefreshMessage(error: unknown) {
  if (error instanceof AnalysisApiError) {
    if (error.status === 404) {
      return 'Analisi non trovata.'
    }

    if (error.status === 500 || error.status === 503) {
      return 'Aggiornamento temporaneamente non disponibile.'
    }
  }

  return 'Aggiornamento temporaneamente non disponibile.'
}

export function AnalysisDetailPage() {
  // useParams estrae dall’URL il parametro della route /analyses/:analysisId tramite destructuring.
  const { analysisId } = useParams()
  // useRef conserva timer e sequenza delle richieste tra rendering senza rappresentare dati visibili.
  // Ricorda il timeout pianificato per poterlo cancellare da stopPolling.
  const pollingTimerRef = useRef<number | null>(null)
  // Conserva il controller della lettura corrente per annullarla nel cleanup o prima di una nuova lettura.
  const requestControllerRef = useRef<AbortController | null>(null)
  // Il numero di sequenza identifica l’ultima richiesta avviata senza introdurre uno stato visibile.
  const requestSequenceRef = useRef(0)
  // Conta gli errori consecutivi del ciclo e viene azzerato dopo una risposta valida.
  const pollingErrorCountRef = useRef(0)

  // useState mantiene il record, gli stati di attesa e gli errori che determinano il rendering condizionale.
  // Indica il caricamento dei dati iniziali e governa la vista di attesa al posto del contenuto.
  const [isLoading, setIsLoading] = useState(Boolean(analysisId))
  // Indica una lettura di aggiornamento, così la UI può mostrare attesa mantenendo i dati già caricati.
  const [isRefreshing, setIsRefreshing] = useState(false)
  // Conserva il record della scansione, aggiornato dopo ogni GET valida per alimentare metadati e risultati.
  const [analysis, setAnalysis] = useState<AnalysisApiRecord | null>(null)
  // Conserva il messaggio di errore della lettura per mostrare il pannello o l’avviso della pagina.
  const [error, setError] = useState<string | null>(null)
  // Conserva l’avviso dell’ultimo aggiornamento fallito senza cancellare i risultati precedenti.
  const [refreshMessage, setRefreshMessage] = useState<string | null>(null)
  // Distingue un ID non trovato dagli errori temporanei e attiva la vista dedicata al 404.
  const [notFound, setNotFound] = useState(false)
  // È un contatore di retry: cambiarlo riavvia l’effetto che lo elenca nelle dipendenze.
  const [reloadKey, setReloadKey] = useState(0)

  // useCallback stabilizza la funzione di pulizia che cancella il timer e interrompe la richiesta in corso.
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

  // L’effetto carica il dettaglio e si riattiva per analysisId o retry; la pulizia ferma il ciclo precedente.
  useEffect(() => {
    // Senza il parametro di route non è possibile costruire la GET del dettaglio.
    if (!analysisId) {
      return
    }

    // La variabile appartiene a questa esecuzione dell’effetto e viene invalidata dalla relativa pulizia.
    let isMounted = true

    // async/await legge il record per ID; showLoader distingue apertura iniziale e aggiornamento in background.
    const loadAnalysis = async (showLoader: boolean) => {
      // Annulla la lettura ancora in corso, se presente, prima di sostituirla o lasciare la pagina.
      requestControllerRef.current?.abort()
      // Crea il segnale di annullamento da inoltrare attraverso il client API fino alla fetch.
      const controller = new AbortController()
      // Salva il controller della nuova lettura nel riferimento condiviso con la pulizia.
      requestControllerRef.current = controller
      // Assegna un numero alla lettura appena avviata: le risposte precedenti saranno riconosciute come obsolete.
      const requestId = ++requestSequenceRef.current

      // Il primo caricamento può sostituire la vista; gli aggiornamenti successivi usano un indicatore meno invasivo.
      // Il ramo distingue un problema dell’apertura iniziale da un fallimento della lettura periodica.
      if (showLoader) {
        setIsLoading(true)
      } else {
        setIsRefreshing(true)
      }

      try {
        // GET autenticata per analysisId: restituisce il record completo senza avviare una nuova scansione.
        const result = await getAnalysis(analysisId, controller.signal)
        // Non aggiorna lo stato se l’effetto è terminato o la risposta appartiene a una richiesta superata.
        if (!isMounted || requestId !== requestSequenceRef.current) {
          return null
        }

        // Aggiorna il record mostrato dalla pagina e cancella le precedenti condizioni di errore.
        setAnalysis(result)
        // Rimuove il precedente errore dopo il buon esito o la preparazione di un nuovo tentativo.
        setError(null)
        // Una risposta valida rimuove la vista di risorsa non trovata eventualmente mostrata in precedenza.
        setNotFound(false)
        // Cancella l’avviso di aggiornamento quando il ciclo riparte o recupera una risposta valida.
        setRefreshMessage(null)
        // Una ripartenza o una risposta valida azzera gli errori accumulati dal ciclo.
        pollingErrorCountRef.current = 0
        // Restituisce il record al ciclo di polling per controllare subito se è ancora pendente.
        return result
      } catch (nextError) {
        // L’annullamento volontario non viene mostrato come errore del servizio.
        if (nextError instanceof DOMException && nextError.name === 'AbortError') {
          return null
        }

        // Non aggiorna lo stato se l’effetto è terminato o la risposta appartiene a una richiesta superata.
        if (!isMounted || requestId !== requestSequenceRef.current) {
          return null
        }

        // Il 404 attiva la vista Analisi non trovata invece di mostrare il record precedente.
        if (nextError instanceof AnalysisApiError && nextError.status === 404) {
          // Il 404 attiva il pannello dedicato e impedisce di presentare un vecchio record come risultato corrente.
          setNotFound(true)
          // Rimuove il precedente errore dopo il buon esito o la preparazione di un nuovo tentativo.
          setError(null)
          // Cancella l’avviso di aggiornamento quando il ciclo riparte o recupera una risposta valida.
          setRefreshMessage(null)
          return null
        }

        // Il primo caricamento può sostituire la vista; gli aggiornamenti successivi usano un indicatore meno invasivo.
        // Il ramo distingue un problema dell’apertura iniziale da un fallimento della lettura periodica.
        if (showLoader) {
          // Conserva il messaggio della prima lettura fallita per offrire il pulsante Riprova.
          setError(nextError instanceof Error ? nextError.message : 'Dettaglio analisi non disponibile.')
        } else {
          // Registra un nuovo errore di aggiornamento per limitare i retry e aumentarne il ritardo.
          pollingErrorCountRef.current += 1
          // Durante il polling mostra un avviso e mantiene disponibili i metadati già ricevuti.
          setRefreshMessage(getDetailRefreshMessage(nextError))
        }

        return null
      } finally {
        // Soltanto il ciclo ancora attivo e la richiesta più recente possono spegnere gli indicatori di caricamento.
        if (isMounted && requestId === requestSequenceRef.current) {
          // Termina lo stato di caricamento della lettura in questo ramo, consentendo il rendering dei dati o dell’errore.
          setIsLoading(false)
          // Spegne l’indicatore di aggiornamento dopo il completamento della richiesta corrente.
          setIsRefreshing(false)
        }
      }
    }

    // Conserva nel ref un timeout singolo che avvierà il controllo successivo.
    const schedulePolling = (delayMs: number) => {
      pollingTimerRef.current = window.setTimeout(() => {
        void pollAnalysis()
      }, delayMs)
    }

    // Pianifica il controllo successivo dopo la risposta, con attesa crescente sugli errori e arresto sui job terminali.
    const pollAnalysis = async () => {
      // Richiede una versione aggiornata del record usando l’indicatore di refresh invece dell’attesa iniziale.
      const result = await loadAnalysis(false)
      // Senza un risultato utilizzabile non può valutare lo stato del job e passa alla gestione dei tentativi.
      if (!isMounted || result === null) {
        // Raggiunto il limite di errori consecutivi, termina il ciclo senza pianificare un altro timeout.
        if (pollingErrorCountRef.current >= maxPollingErrors) {
          return
        }

        // Dopo un errore ammesso aumenta il ritardo in proporzione al contatore prima del tentativo successivo.
        if (pollingErrorCountRef.current > 0) {
          schedulePolling(pollingIntervalMs * (pollingErrorCountRef.current + 1))
        }
        return
      }

      // queued e processing richiedono un nuovo controllo; completed e failed terminano la lettura periodica.
      if (hasPendingAnalysisStatus(result.status)) {
        schedulePolling(pollingIntervalMs)
      }
    }

    const loadInitialAnalysis = async () => {
      // Carica il dettaglio all’avvio dell’effetto con il loader iniziale, prima di qualsiasi polling.
      const result = await loadAnalysis(true)
      // Senza un risultato utilizzabile non può valutare lo stato del job e passa alla gestione dei tentativi.
      if (!isMounted || result === null) {
        return
      }

      // queued e processing richiedono un nuovo controllo; completed e failed terminano la lettura periodica.
      if (hasPendingAnalysisStatus(result.status)) {
        schedulePolling(pollingIntervalMs)
      }
    }

    // Avvia la prima GET per questo ID; il cleanup invaliderà questo ciclo quando cambia route o reloadKey.
    void loadInitialAnalysis()

    // React esegue questa pulizia prima di ripetere l’effetto al cambio delle dipendenze e quando smonta il componente.
    return () => {
      // Il cleanup invalida le continuazioni asincrone di questo effetto prima di annullare le attività rimaste.
      isMounted = false
      stopPolling()
    }
  }, [analysisId, reloadKey, stopPolling])

  // I return anticipati separano caricamento, parametro assente, record non trovato ed errore senza dati.
  // Durante la prima lettura restituisce il pannello di attesa prima di provare a leggere campi del record.
  if (isLoading) {
    return (
      <LoadingState
        title="Apertura del dettaglio"
        description="Sto caricando metadati, indicatori e riepilogo temporale."
      />
    )
  }

  // Senza il parametro di route non è possibile costruire la GET del dettaglio.
  if (!analysisId) {
    return (
      <ErrorState
        title="Analisi Non Specificata"
        description="Manca l'identificativo del report da consultare."
      />
    )
  }

  // Mostra l’errore di risorsa assente anche quando in memoria resta un record caricato precedentemente.
  if (notFound) {
    return (
      <ErrorState
        title="Analisi Non Trovata"
        description="L'identificativo richiesto non corrisponde ad alcun report disponibile sulla Analysis API locale."
      />
    )
  }

  // L’errore blocca la vista completa solo se non è disponibile alcun record da consultare.
  if (error && !analysis) {
    return (
      <ErrorState
        title="Dettaglio non disponibile"
        description={error}
        actionLabel="Riprova"
        onRetry={() => setReloadKey((currentValue) => currentValue + 1)}
      />
    )
  }

  // Il return nullo evita l’accesso ai metadati finché non è presente un record utilizzabile.
  if (!analysis) {
    return null
  }

  // Mostra l’ultimo aggiornamento soltanto quando differisce dalla data iniziale del record.
  const showUpdatedAt = analysis.created_at !== analysis.updated_at
  // Deriva lo stato visuale con il formatter, lasciando invariato analysis.status usato dal polling.
  const presentationStatus = getPresentationAnalysisStatus(analysis)
  // Raccoglie regole sx riutilizzate per rendere leggibili nomi file, hash e testi lunghi senza uscire dal contenitore.
  const wrappingTextSx = {
    minWidth: 0,
    maxWidth: '100%',
    overflowWrap: 'anywhere',
    wordBreak: 'break-word',
    whiteSpace: 'normal',
  } as const

  return (
    <Stack spacing={3}>
      {/* L’intestazione presenta il contesto della pagina e le eventuali azioni passate attraverso le props. */}
      <PageHeader
        title={analysis.file_name}
        description={getAnalysisDescription(analysis)}
        highlight={`ID analisi: ${getDisplayAnalysisId(analysis.id)}`}
        titleSx={{
          fontSize: { xs: '1.95rem', sm: '2.35rem', lg: '2.85rem' },
          display: '-webkit-box',
          WebkitBoxOrient: 'vertical',
          WebkitLineClamp: 3,
          overflow: 'hidden',
        }}
        action={
          <Button component={RouterLink} to="/history" variant="outlined" startIcon={<ArrowBackRoundedIcon />}>
            Torna alla cronologia
          </Button>
        }
      />

      {/* Raggruppa identità della scansione, avanzamento e metadati ricevuti dal backend. */}
      <SectionCard title="Esito e metadati principali">
        <Stack spacing={2.5}>
          <Stack
            direction={{ xs: 'column', md: 'row' }}
            spacing={1.2}
            sx={{ alignItems: 'flex-start', minWidth: 0 }}
          >
            <StatusChip status={presentationStatus} />
            <RiskChip risk={analysis.risk_level} />
            {isRefreshing ? (
              <Stack direction="row" spacing={1} sx={{ alignItems: 'center', pt: 0.4 }}>
                <CircularProgress size={16} />
                <Typography variant="body2" color="text.secondary">
                  Aggiornamento in corso
                </Typography>
              </Stack>
            ) : null}
          </Stack>
          {/* Mostra un avviso per l’aggiornamento lasciando disponibili i dati dell’ultima lettura riuscita. */}
          {refreshMessage ? <Alert severity="warning">{refreshMessage}</Alert> : null}
          <Typography title={analysis.file_name} sx={wrappingTextSx}>
            <strong>Nome file:</strong> {analysis.file_name}
          </Typography>
          <Typography sx={wrappingTextSx}>
            <strong>ID analisi:</strong> {getDisplayAnalysisId(analysis.id)}
          </Typography>
          {/* Mostra il proprietario soltanto se il backend ha fornito un nome utente. */}
          {analysis.owner_username ? (
            <Typography sx={wrappingTextSx}>
              <strong>Utente:</strong> {analysis.owner_username}
            </Typography>
          ) : null}
          <Typography sx={wrappingTextSx}>
            <strong>SHA-256:</strong> {formatSha256(analysis.sha256, presentationStatus)}
          </Typography>
          <Typography sx={wrappingTextSx}>
            <strong>Data creazione:</strong> {formatDateTime(analysis.created_at)}
          </Typography>
          {/* Evita una data duplicata quando creazione e ultimo aggiornamento coincidono. */}
          {showUpdatedAt ? (
            <Typography sx={wrappingTextSx}>
              <strong>Ultimo aggiornamento:</strong> {formatDateTime(analysis.updated_at)}
            </Typography>
          ) : null}
          <Grid container spacing={2} sx={{ minWidth: 0 }}>
            <Grid size={{ xs: 12, sm: 4 }} sx={{ minWidth: 0 }}>
              <Typography variant="body2" color="text.secondary">
                Tipo MIME
              </Typography>
              <Typography sx={{ fontWeight: 700, ...wrappingTextSx }}>
                {formatMimeType(analysis.mime_type, presentationStatus)}
              </Typography>
            </Grid>
            <Grid size={{ xs: 12, sm: 4 }} sx={{ minWidth: 0 }}>
              <Typography variant="body2" color="text.secondary">
                Dimensione
              </Typography>
              <Typography sx={{ fontWeight: 700, ...wrappingTextSx }}>
                {formatBytesToLabel(analysis.size_bytes)}
              </Typography>
            </Grid>
            <Grid size={{ xs: 12, sm: 4 }} sx={{ minWidth: 0 }}>
              <Typography variant="body2" color="text.secondary">
                Entropia
              </Typography>
              <Typography sx={{ fontWeight: 700, ...wrappingTextSx }}>
                {formatEntropy(analysis.entropy, presentationStatus)}
              </Typography>
            </Grid>
          </Grid>
          <Divider />
          <Box sx={{ minWidth: 0 }}>
            <Typography variant="body2" color="text.secondary" gutterBottom>
              Verdetto finale
            </Typography>
            <Typography sx={{ fontWeight: 700, ...wrappingTextSx }}>
              {getVerdictLabel(analysis)}
            </Typography>
          </Box>
          {/* Il momento di scansione compare solo quando il campo è valorizzato nella risposta. */}
          {analysis.scanned_at ? (
            <Box sx={{ minWidth: 0 }}>
              <Typography variant="body2" color="text.secondary" gutterBottom>
                Scansione completata
              </Typography>
              <Typography sx={{ fontWeight: 700, ...wrappingTextSx }}>
                {formatDateTime(analysis.scanned_at)}
              </Typography>
            </Box>
          ) : null}
          <Divider />
          <Box sx={{ minWidth: 0 }}>
            <Typography variant="body2" color="text.secondary" gutterBottom>
              Coerenza estensione / contenuto
            </Typography>
            <Typography sx={{ fontWeight: 700, ...wrappingTextSx }}>
              {formatExtensionMatch(analysis.extension_matches_mime, presentationStatus)}
            </Typography>
          </Box>
          {/* Questo blocco mostra l’errore generale del job; scan_error viene trattato negli altri testi della pagina. */}
          {analysis.error_message && analysis.verdict !== 'scan_error' ? (
            <>
              <Divider />
              <Box sx={{ minWidth: 0 }}>
                <Typography variant="body2" color="text.secondary" gutterBottom>
                  Messaggio di errore
                </Typography>
                <Typography sx={wrappingTextSx}>{analysis.error_message}</Typography>
              </Box>
            </>
          ) : null}
        </Stack>
      </SectionCard>

      <Grid container spacing={3} sx={{ minWidth: 0, alignItems: 'stretch' }}>
        <Grid
          size={{ xs: 12, lg: 6 }}
          sx={{
            minWidth: 0,
            display: 'flex',
            width: '100%',
          }}
        >
          <Box sx={{ width: '100%' }}>
            {/* Separa gli esiti ClamAV e YARA, così un errore del motore non viene confuso con l’assenza di minacce. */}
            <SectionCard title="Analisi antimalware">
              <Stack spacing={2.5}>
                <Box sx={{ minWidth: 0 }}>
                  <Typography variant="body2" color="text.secondary" gutterBottom>
                    ClamAV
                  </Typography>
                  <Typography sx={{ fontWeight: 700, ...wrappingTextSx }}>
                    {getClamAvLabel(analysis)}
                  </Typography>
                  {/* La firma della minaccia compare soltanto se ClamAV ne ha restituito il nome. */}
                  {analysis.clamav_signature_name ? (
                    <Typography sx={wrappingTextSx}>
                      <strong>Firma:</strong> {analysis.clamav_signature_name}
                    </Typography>
                  ) : null}
                  {/* Il dettaglio dell’errore ClamAV rimane distinto dall’etichetta sintetica del motore. */}
                  {analysis.clamav_error ? (
                    <Typography sx={wrappingTextSx}>
                      <strong>Dettaglio:</strong> {analysis.clamav_error}
                    </Typography>
                  ) : null}
                </Box>
                <Divider />
                <Box sx={{ minWidth: 0 }}>
                  <Typography variant="body2" color="text.secondary" gutterBottom>
                    YARA
                  </Typography>
                  <Typography sx={{ fontWeight: 700, ...wrappingTextSx }}>
                    {getYaraLabel(analysis)}
                  </Typography>
                  {/* map crea una voce per ogni regola ricevuta e mostra i dettagli opzionali soltanto quando presenti. */}
                  {analysis.yara_matches.map((match, index) => (
                    <Box key={`${match.rule_name}-${index}`} sx={{ pt: index === 0 ? 1 : 1.5 }}>
                      <Typography sx={wrappingTextSx}>
                        <strong>Regola:</strong> {match.rule_name}
                      </Typography>
                      {/* Categoria e severità sono metadati opzionali della regola corrispondente, mostrati quando presenti. */}
                      {match.category ? (
                        <Typography sx={wrappingTextSx}>
                          <strong>Categoria:</strong> {match.category}
                        </Typography>
                      ) : null}
                      {match.severity ? (
                        <Typography sx={wrappingTextSx}>
                          <strong>Severità:</strong> {match.severity}
                        </Typography>
                      ) : null}
                      {match.description ? <Typography sx={wrappingTextSx}>{match.description}</Typography> : null}
                    </Box>
                  ))}
                  {/* Espone l’errore del motore YARA senza ricostruirlo dagli altri campi della scansione. */}
                  {analysis.yara_error ? (
                    <Typography sx={{ pt: 1, ...wrappingTextSx }}>
                      <strong>Dettaglio:</strong> {analysis.yara_error}
                    </Typography>
                  ) : null}
                </Box>
              </Stack>
            </SectionCard>
          </Box>
        </Grid>

        <Grid
          size={{ xs: 12, lg: 6 }}
          sx={{
            minWidth: 0,
            display: 'flex',
            width: '100%',
          }}
        >
          <Box sx={{ width: '100%' }}>
            <SectionCard title="Indicatori">
              {/* Gli indicatori vengono mostrati come lista soltanto quando lo stato di presentazione è completato. */}
              {presentationStatus !== 'completed' ? (
                <Typography color="text.secondary" sx={wrappingTextSx}>
                  Non disponibili.
                </Typography>
              ) : analysis.indicators.length === 0 ? (
                <Typography color="text.secondary" sx={wrappingTextSx}>
                  Nessun indicatore rilevante.
                </Typography>
              ) : (
                <List disablePadding sx={{ minWidth: 0 }}>
                  {/* Trasforma ogni indicatore testuale in una voce numerata con traduzione e separatore. */}
                  {analysis.indicators.map((indicator, index) => (
                    <Box key={`${indicator}-${index}`} sx={{ minWidth: 0 }}>
                      <ListItem
                        disableGutters
                        sx={{
                          pt: index === 0 ? 0 : 1.3,
                          pb: 1.3,
                          alignItems: 'flex-start',
                        }}
                      >
                        <ListItemText
                          primary={
                            <Stack direction="row" spacing={1.2} sx={{ alignItems: 'center', minWidth: 0 }}>
                              <Typography sx={{ fontWeight: 700 }}>{`Indicatore ${index + 1}`}</Typography>
                              <Box
                                sx={{
                                  width: 10,
                                  height: 10,
                                  borderRadius: '50%',
                                  bgcolor: 'primary.main',
                                }}
                              />
                            </Stack>
                          }
                          secondary={formatIndicatorMessage(indicator)}
                          sx={{
                            m: 0,
                            minWidth: 0,
                            '& .MuiListItemText-primary': {
                              minWidth: 0,
                            },
                            '& .MuiListItemText-secondary': {
                              ...wrappingTextSx,
                            },
                          }}
                        />
                      </ListItem>
                      {index < analysis.indicators.length - 1 ? <Divider /> : null}
                    </Box>
                  ))}
                </List>
              )}
            </SectionCard>
          </Box>
        </Grid>
      </Grid>

      {/* La timeline deriva solo da creazione e ultimo aggiornamento del record, senza ricostruire eventi di scansione intermedi. */}
      <SectionCard title="Riepilogo temporale" subtitle="Informazioni temporali realmente disponibili">
        <Stack spacing={0}>
          {[
            {
              label: 'Analisi creata',
              timestamp: analysis.created_at,
              note: 'Il file è stato ricevuto dalla Analysis API locale.',
            },
            // Lo spread aggiunge l’evento di aggiornamento alla timeline solo quando la data differisce dalla creazione.
            ...(showUpdatedAt
              ? [
                  {
                    label: 'Ultimo aggiornamento',
                    timestamp: analysis.updated_at,
                    note: "Questo timestamp rappresenta l'ultimo aggiornamento noto del record.",
                  },
                ]
              : []),
          ].map((event, index, events) => (
            <Stack
              key={`${event.label}-${event.timestamp}`}
              direction="row"
              spacing={2}
              sx={{ alignItems: 'stretch', minWidth: 0 }}
            >
              <Stack sx={{ alignItems: 'center', flexShrink: 0 }}>
                <Box
                  sx={{
                    width: 14,
                    height: 14,
                    borderRadius: '50%',
                    bgcolor: 'primary.main',
                    mt: 0.8,
                  }}
                />
                {index < events.length - 1 ? (
                  <Box sx={{ width: 2, flexGrow: 1, bgcolor: 'divider', minHeight: 46 }} />
                ) : null}
              </Stack>
              <Box sx={{ py: 1.1, pb: 2.2, minWidth: 0, flex: 1 }}>
                <Typography sx={{ fontWeight: 700, ...wrappingTextSx }}>{event.label}</Typography>
                <Typography variant="body2" color="text.secondary" sx={wrappingTextSx}>
                  {formatDateTime(event.timestamp)}
                </Typography>
                <Typography sx={wrappingTextSx}>{event.note}</Typography>
              </Box>
            </Stack>
          ))}
        </Stack>
      </SectionCard>
    </Stack>
  )
}
