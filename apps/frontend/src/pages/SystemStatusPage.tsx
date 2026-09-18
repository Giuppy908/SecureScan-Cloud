/**
 * Pagina "Stato del sistema".
 *
 * Mostra uno snapshot operativo dei servizi principali della piattaforma locale:
 * Analysis API, Worker, ClamAV, PostgreSQL, Kong e stack di osservabilità.
 * I dati arrivano dall'endpoint backend `/api/v1/system/status`, che aggrega
 * heartbeat applicativi e controlli infrastrutturali.
 */
import RefreshRoundedIcon from '@mui/icons-material/RefreshRounded'
import {
  Alert,
  Button,
  CircularProgress,
  Grid,
  Stack,
  Typography,
} from '@mui/material'
// Gli hook React mantengono lo stato visibile, riferimenti alle richieste e callback riutilizzabili tra rendering.
import { useCallback, useEffect, useRef, useState } from 'react'
// Lo stato è una risposta aggregata dell’API; il browser non interroga direttamente i singoli servizi.
import { AnalysisApiError, getSystemStatus } from '../api/analysisApi'
import { PageHeader } from '../components/PageHeader'
import { SectionCard } from '../components/SectionCard'
import { EmptyState, LoadingState } from '../components/StatePanels'
import { StatusChip } from '../components/StatusChip'
// Gli import type descrivono i dati usati dalla pagina e vengono eliminati dal JavaScript prodotto.
import type { SystemStatusServiceSnapshot, SystemStatusSnapshot } from '../types/domain'
import { formatDateTime } from '../utils/formatters'

// Lo snapshot viene richiesto ogni 5 secondi dopo i successi; gli errori consecutivi limitano i nuovi tentativi.
const pollingIntervalMs = 5000
const maxPollingErrors = 3

// Traduce gli errori della richiesta distinguendo sessione scaduta, permesso negato e indisponibilità.
function getSystemStatusErrorMessage(error: unknown) {
  // Legge lo status soltanto dagli errori del client HTTP per distinguere autenticazione, permessi e disponibilità.
  if (error instanceof AnalysisApiError) {
    if (error.status === 401) {
      return "Sessione scaduta. Effettua nuovamente l'accesso."
    }
    if (error.status === 403) {
      return 'Non hai i permessi per visualizzare lo stato del sistema.'
    }
    if (error.status === 500 || error.status === 503) {
      return 'Lo stato del sistema non è temporaneamente disponibile.'
    }
  }

  return 'Lo stato del sistema non è temporaneamente disponibile.'
}

// Il tipo indicizzato riusa overall_status del contratto API per scegliere la descrizione complessiva.
function getOverallStatusMessage(status: SystemStatusSnapshot['overall_status']) {
  // L’etichetta complessiva riflette overall_status ricevuto, senza ricalcolarlo dai servizi nel browser.
  switch (status) {
    case 'healthy':
      return 'Tutti i componenti essenziali risultano operativi.'
    case 'degraded':
      return 'La piattaforma è disponibile, ma almeno una componente non critica è degradata.'
    case 'unavailable':
      return 'Una componente essenziale non è disponibile.'
  }
}

// Traduce i nomi tecnici dei servizi conosciuti e conserva il nome ricevuto per quelli non mappati.
function getServiceLabel(serviceName: SystemStatusServiceSnapshot['name']) {
  // Converte i nomi tecnici conosciuti in etichette leggibili e conserva il nome originale come fallback.
  switch (serviceName) {
    case 'analysis-api':
      return 'Analysis API'
    case 'analysis-worker':
      return 'Analysis Worker'
    case 'clamav':
      return 'ClamAV'
    case 'postgres':
      return 'PostgreSQL'
    case 'postgres-exporter':
      return 'PostgreSQL Exporter'
    case 'kong':
      return 'Kong Gateway'
    case 'prometheus':
      return 'Prometheus'
    case 'grafana':
      return 'Grafana'
    default:
      return serviceName
  }
}

// Legge i dettagli aggregati dal backend e ne verifica il tipo; il browser non effettua probe diretti sui servizi.
function getServiceMessage(service: SystemStatusServiceSnapshot) {
  // Per il servizio API costruisce il messaggio usando il numero di repliche e il loro stato aggregato.
  if (service.name === 'analysis-api') {
    // Accetta il conteggio delle repliche attive solo se è un numero; altrimenti visualizza zero.
    const activeInstances =
      typeof service.details.active_instances === 'number' ? service.details.active_instances : 0
    // Legge il totale configurato dal dettaglio tipizzato come eterogeneo, senza dedurlo dai nomi delle istanze.
    const configuredInstances =
      typeof service.details.configured_instances === 'number' ? service.details.configured_instances : 0

    // Il testo del ramo descrive il servizio come operativo secondo lo snapshot, non come esito di un nuovo controllo locale.
    if (service.status === 'healthy') {
      return `${activeInstances} repliche API attive su ${configuredInstances}.`
    }
    // Il ramo degraded mantiene distinta la disponibilità parziale rispetto a quella completa.
    if (service.status === 'degraded') {
      return `${activeInstances} repliche API attive su ${configuredInstances}.`
    }
    return 'Nessuna replica API attiva entro la finestra di heartbeat.'
  }

  // Traduce lo stato del database in raggiungibile o non raggiungibile.
  if (service.name === 'postgres') {
    return service.status === 'healthy'
      ? 'Database raggiungibile.'
      : 'Database non raggiungibile.'
  }

  // Per i worker legge i conteggi degli heartbeat riportati dal backend.
  if (service.name === 'analysis-worker') {
    // Accetta solo il dettaglio numerico e lo usa anche per scegliere singolare o plurale del messaggio.
    const activeWorkers = typeof service.details.active_workers === 'number' ? service.details.active_workers : 0
    // Il testo del ramo descrive il servizio come operativo secondo lo snapshot, non come esito di un nuovo controllo locale.
    if (service.status === 'healthy') {
      return activeWorkers === 1
        ? '1 worker attivo rilevato.'
        : `${activeWorkers} worker attivi rilevati.`
    }
    // Il ramo degraded mantiene distinta la disponibilità parziale rispetto a quella completa.
    if (service.status === 'degraded') {
      return 'Nessun worker attivo entro la finestra di heartbeat.'
    }
    return 'Disponibilità dei worker non determinabile.'
  }

  // Descrive la raggiungibilità del motore antimalware senza avviare una scansione.
  if (service.name === 'clamav') {
    return service.status === 'healthy'
      ? 'Motore antimalware raggiungibile.'
      : 'Motore antimalware temporaneamente non raggiungibile.'
  }

  // Il messaggio si riferisce alla disponibilità del gateway pubblico indicata nello snapshot.
  if (service.name === 'kong') {
    return service.status === 'healthy'
      ? 'Gateway pubblico raggiungibile.'
      : 'Gateway pubblico temporaneamente non raggiungibile.'
  }

  // Associa lo stato alla raccolta delle metriche, distinta dalla disponibilità delle analisi.
  if (service.name === 'prometheus') {
    return service.status === 'healthy'
      ? 'Raccolta metriche disponibile.'
      : 'Raccolta metriche temporaneamente non disponibile.'
  }

  // Associa lo stato alla dashboard di osservabilità e non alla pagina Dashboard di SecureScan.
  if (service.name === 'grafana') {
    return service.status === 'healthy'
      ? 'Dashboard di osservabilità disponibile.'
      : 'Dashboard di osservabilità temporaneamente non disponibile.'
  }

  // Descrive il componente che espone metriche del database, separato dal database stesso.
  if (service.name === 'postgres-exporter') {
    return service.status === 'healthy'
      ? 'Exporter del database raggiungibile.'
      : 'Exporter del database temporaneamente non disponibile.'
  }

  // Per servizi non mappati mantiene il messaggio originale ricevuto dalla API.
  return service.message
}

export function SystemStatusPage() {
  // useRef mantiene timer, controller e contatori tra rendering senza aggiornare direttamente l’interfaccia.
  // Ricorda il timeout pianificato per poterlo cancellare da stopPolling.
  const pollingTimerRef = useRef<number | null>(null)
  // Conserva il controller della lettura corrente per annullarla nel cleanup o prima di una nuova lettura.
  const requestControllerRef = useRef<AbortController | null>(null)
  // Il numero di sequenza identifica l’ultima richiesta avviata senza introdurre uno stato visibile.
  const requestSequenceRef = useRef(0)
  // Conta gli errori consecutivi del ciclo e viene azzerato dopo una risposta valida.
  const pollingErrorCountRef = useRef(0)
  // Ricorda alle callback se esiste già uno snapshot, così un errore successivo non viene trattato come fallimento iniziale.
  const hasSnapshotRef = useRef(false)

  // useState conserva snapshot e messaggi distinguendo il primo errore dai problemi di aggiornamento.
  // Indica il caricamento dei dati iniziali e governa la vista di attesa al posto del contenuto.
  const [isLoading, setIsLoading] = useState(true)
  // Indica una lettura di aggiornamento, così la UI può mostrare attesa mantenendo i dati già caricati.
  const [isRefreshing, setIsRefreshing] = useState(false)
  // Conserva lo snapshot API della pagina e viene sostituito quando arriva una lettura valida.
  const [snapshot, setSnapshot] = useState<SystemStatusSnapshot | null>(null)
  // Conserva il messaggio di errore della lettura per mostrare il pannello o l’avviso della pagina.
  const [error, setError] = useState<string | null>(null)
  // Conserva l’avviso dell’ultimo aggiornamento fallito senza cancellare i risultati precedenti.
  const [refreshMessage, setRefreshMessage] = useState<string | null>(null)
  // È un contatore di retry: cambiarlo riavvia l’effetto che lo elenca nelle dipendenze.
  const [reloadKey, setReloadKey] = useState(0)

  // useCallback stabilizza la pulizia che cancella il timeout e annulla la richiesta in corso.
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

  // La callback asincrona legge lo stato dalla API, scarta risposte superate e restituisce un booleano al ciclo di polling.
  const requestSnapshot = useCallback(
    async (showLoader: boolean) => {
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
        // GET autenticata: riceve stato complessivo, servizi, dettagli e istanti degli ultimi controlli.
        const nextSnapshot = await getSystemStatus(controller.signal)
        // Non applica un risultato ormai superato da una lettura più recente.
        if (requestId !== requestSequenceRef.current) {
          // Comunica al chiamante che la lettura non ha applicato uno snapshot valido, anche quando è stata annullata.
          return false
        }

        // Applica in un solo aggiornamento i dati che alimentano lo stato generale e tutte le card dei servizi.
        setSnapshot(nextSnapshot)
        // Da questo momento il ciclo può conservare i dati e mostrare avvisi se un aggiornamento fallisce.
        hasSnapshotRef.current = true
        // Rimuove il precedente errore dopo il buon esito o la preparazione di un nuovo tentativo.
        setError(null)
        // Cancella l’avviso di aggiornamento quando il ciclo riparte o recupera una risposta valida.
        setRefreshMessage(null)
        // Una ripartenza o una risposta valida azzera gli errori accumulati dal ciclo.
        pollingErrorCountRef.current = 0
        // Segnala al ciclo che la lettura è riuscita e può essere pianificato un altro aggiornamento.
        return true
      } catch (nextError) {
        // L’annullamento volontario non viene mostrato come errore del servizio.
        if (nextError instanceof DOMException && nextError.name === 'AbortError') {
          // Comunica al chiamante che la lettura non ha applicato uno snapshot valido, anche quando è stata annullata.
          return false
        }
        // Non applica un risultato ormai superato da una lettura più recente.
        if (requestId !== requestSequenceRef.current) {
          // Comunica al chiamante che la lettura non ha applicato uno snapshot valido, anche quando è stata annullata.
          return false
        }

        // Ricava il testo dell’errore prima di scegliere tra pannello iniziale e avviso di refresh.
        const message = getSystemStatusErrorMessage(nextError)
        // Solo una prima lettura senza dati imposta l’errore bloccante; gli altri fallimenti conservano lo snapshot.
        if (showLoader && hasSnapshotRef.current === false) {
          setError(message)
        } else {
          // Registra un nuovo errore di aggiornamento per limitare i retry e aumentarne il ritardo.
          pollingErrorCountRef.current += 1
          setRefreshMessage(message)
        }
        // Comunica al chiamante che la lettura non ha applicato uno snapshot valido, anche quando è stata annullata.
        return false
      } finally {
        // Il finally aggiorna gli indicatori solo per la richiesta corrente, senza interferire con una lettura successiva.
        if (requestId === requestSequenceRef.current) {
          // Termina lo stato di caricamento della lettura in questo ramo, consentendo il rendering dei dati o dell’errore.
          setIsLoading(false)
          // Spegne l’indicatore di aggiornamento dopo il completamento della richiesta corrente.
          setIsRefreshing(false)
        }
      }
    },
    [],
  )

  // L’effetto avvia caricamento e timer; le dipendenze permettono al pulsante Aggiorna di riavviarlo tramite reloadKey.
  useEffect(() => {
    // Programma un singolo controllo futuro e conserva il timeout per la funzione di arresto.
    const scheduleNext = (delayMs: number) => {
      pollingTimerRef.current = window.setTimeout(() => {
        void pollSnapshot()
      }, delayMs)
    }

    const pollSnapshot = async () => {
      // Attende il completamento della GET periodica prima di decidere quando eseguirne un’altra.
      const succeeded = await requestSnapshot(false)
      // Un successo pianifica il successivo controllo dopo l’intervallo normale.
      if (succeeded) {
        scheduleNext(pollingIntervalMs)
        return
      }

      // Il ritardo cresce con il numero di errori; raggiunto il limite non pianifica un ulteriore tentativo.
      // Quando non è stato raggiunto il limite, il ramo pianifica un tentativo in base al contatore corrente.
      if (pollingErrorCountRef.current < maxPollingErrors) {
        scheduleNext(pollingIntervalMs * (pollingErrorCountRef.current + 1))
      }
    }

    // La lettura iniziale dell’effetto decide se usare il loader in base all’esistenza di uno snapshot precedente.
    void requestSnapshot(hasSnapshotRef.current === false).then((succeeded) => {
      // Un successo pianifica il successivo controllo dopo l’intervallo normale.
      if (succeeded) {
        scheduleNext(pollingIntervalMs)
      }
    })

    // React esegue questa pulizia prima di ripetere l’effetto al cambio delle dipendenze e quando smonta il componente.
    return () => {
      stopPolling()
    }
  }, [reloadKey, requestSnapshot, stopPolling])

  if (isLoading) {
    return (
      <LoadingState
        title="Raccolta dello stato del sistema"
        description="Sto aggiornando lo stato dei servizi locali."
      />
    )
  }

  // Senza dati utilizzabili mostra il pannello di errore con il comando che riavvia il ciclo.
  if (error && snapshot === null) {
    return (
      <EmptyState
        title="Stato del sistema non disponibile"
        description={error}
        action={
          <Button
            variant="contained"
            startIcon={<RefreshRoundedIcon />}
            onClick={() => {
              stopPolling()
              // Una ripartenza o una risposta valida azzera gli errori accumulati dal ciclo.
              pollingErrorCountRef.current = 0
              // Rimuove il precedente errore dopo il buon esito o la preparazione di un nuovo tentativo.
              setError(null)
              // Cancella l’avviso di aggiornamento quando il ciclo riparte o recupera una risposta valida.
              setRefreshMessage(null)
              setReloadKey((currentValue) => currentValue + 1)
            }}
          >
            Riprova
          </Button>
        }
      />
    )
  }

  // Evita di accedere ai campi prima di avere uno snapshot, restituendo nessun contenuto in questo ramo.
  if (!snapshot) {
    return null
  }

  return (
    <Stack spacing={3}>
      {/* L’intestazione presenta il contesto della pagina e le eventuali azioni passate attraverso le props. */}
      <PageHeader
        title="Stato del sistema"
        description="Snapshot reale dei componenti principali della piattaforma locale."
        highlight={`Ultimo controllo: ${formatDateTime(snapshot.checked_at)}`}
        action={
          <Button
            variant="outlined"
            startIcon={isRefreshing ? <CircularProgress size={16} /> : <RefreshRoundedIcon />}
            onClick={() => {
              stopPolling()
              // Una ripartenza o una risposta valida azzera gli errori accumulati dal ciclo.
              pollingErrorCountRef.current = 0
              // Cancella l’avviso di aggiornamento quando il ciclo riparte o recupera una risposta valida.
              setRefreshMessage(null)
              setReloadKey((currentValue) => currentValue + 1)
            }}
          >
            Aggiorna
          </Button>
        }
      />

      {/* Mostra un avviso per l’aggiornamento lasciando disponibili i dati dell’ultima lettura riuscita. */}
      {refreshMessage ? <Alert severity="warning">{refreshMessage}</Alert> : null}

      {/* Il badge usa overall_status e la descrizione tradotta; la data indica quando il backend ha costruito lo snapshot. */}
      <SectionCard title="Stato generale" subtitle={getOverallStatusMessage(snapshot.overall_status)}>
        <Stack direction={{ xs: 'column', md: 'row' }} spacing={2} sx={{ alignItems: { xs: 'flex-start', md: 'center' } }}>
          <StatusChip status={snapshot.overall_status} />
          <Typography color="text.secondary">
            Snapshot aggiornato alle {formatDateTime(snapshot.checked_at)}.
          </Typography>
        </Stack>
      </SectionCard>

      <Grid container spacing={3} sx={{ minWidth: 0 }}>
        {/* map costruisce una card per servizio; i breakpoint MUI passano da una a due o tre colonne. */}
        {snapshot.services.map((service) => (
          <Grid key={service.name} size={{ xs: 12, md: 6, xl: 4 }} sx={{ minWidth: 0 }}>
            <SectionCard title={getServiceLabel(service.name)}>
              <Stack spacing={1.5} sx={{ minWidth: 0 }}>
                <StatusChip status={service.status} />
                <Typography color="text.secondary" sx={{ minWidth: 0 }}>
                  {getServiceMessage(service)}
                </Typography>
                <Typography sx={{ minWidth: 0 }}>
                  <strong>Ultimo controllo:</strong> {formatDateTime(service.last_checked_at)}
                </Typography>
                {/* Il rendering condizionale mostra i dettagli opzionali solo se hanno il tipo atteso. */}
                {typeof service.details.version === 'string' ? (
                  <Typography sx={{ minWidth: 0 }}>
                    <strong>Versione:</strong> {service.details.version}
                  </Typography>
                ) : null}
                {/* Mostra l’identificativo dell’istanza soltanto se il dettaglio è una stringa. */}
                {typeof service.details.instance_id === 'string' ? (
                  <Typography sx={{ minWidth: 0, overflowWrap: 'anywhere' }}>
                    <strong>Replica corrente:</strong> {service.details.instance_id}
                  </Typography>
                ) : null}
                {/* Il totale delle repliche compare solo per snapshot che espongono questo dettaglio numerico. */}
                {typeof service.details.configured_instances === 'number' ? (
                  <Typography sx={{ minWidth: 0 }}>
                    <strong>Repliche configurate:</strong> {service.details.configured_instances}
                  </Typography>
                ) : null}
                {typeof service.details.active_instances === 'number' ? (
                  <Typography sx={{ minWidth: 0 }}>
                    <strong>Repliche attive:</strong> {service.details.active_instances}
                  </Typography>
                ) : null}
                {/* Controlla che gli ID siano un array prima di contarli e unirli in una stringa separata da virgole. */}
                {Array.isArray(service.details.active_instance_ids) ? (
                  <Typography sx={{ minWidth: 0, overflowWrap: 'anywhere' }}>
                    <strong>ID repliche attive:</strong>{' '}
                    {service.details.active_instance_ids.length > 0
                      ? service.details.active_instance_ids.join(', ')
                      : 'Nessuna'}
                  </Typography>
                ) : null}
                {/* Il timeout heartbeat API viene mostrato soltanto nella card API e se il valore è numerico. */}
                {service.name === 'analysis-api' && typeof service.details.heartbeat_timeout_seconds === 'number' ? (
                  <Typography sx={{ minWidth: 0 }}>
                    <strong>Timeout heartbeat API:</strong> {service.details.heartbeat_timeout_seconds} s
                  </Typography>
                ) : null}
                {typeof service.details.active_workers === 'number' ? (
                  <Typography sx={{ minWidth: 0 }}>
                    <strong>Worker attivi:</strong> {service.details.active_workers}
                  </Typography>
                ) : null}
                {/* Il timeout dei worker riguarda la loro finestra heartbeat, distinta dal ritmo del polling del browser. */}
                {service.name === 'analysis-worker' && typeof service.details.heartbeat_timeout_seconds === 'number' ? (
                  <Typography sx={{ minWidth: 0 }}>
                    <strong>Timeout heartbeat:</strong> {service.details.heartbeat_timeout_seconds} s
                  </Typography>
                ) : null}
              </Stack>
            </SectionCard>
          </Grid>
        ))}
      </Grid>
    </Stack>
  )
}
