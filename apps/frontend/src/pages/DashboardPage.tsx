/**
 * Pagina "Dashboard".
 *
 * Mostra un riepilogo operativo dell'account autenticato: conteggi analisi,
 * distribuzione del rischio, andamento temporale, analisi recenti e stato
 * sintetico dei servizi. I dati arrivano dagli endpoint backend
 * `/api/v1/dashboard` e `/api/v1/system/status`.
 *
 * Lo scope dei dati non è deciso dal frontend: il backend applica già RBAC e
 * ownership, quindi un analyst riceve solo i propri numeri mentre un admin
 * riceve la vista globale autorizzata.
 */
import ArrowForwardRoundedIcon from '@mui/icons-material/ArrowForwardRounded'
import RefreshRoundedIcon from '@mui/icons-material/RefreshRounded'
import UploadFileRoundedIcon from '@mui/icons-material/UploadFileRounded'
import {
  Alert,
  Box,
  Button,
  Divider,
  Grid,
  LinearProgress,
  List,
  ListItem,
  ListItemText,
  Stack,
  Typography,
} from '@mui/material'
// Gli hook React mantengono lo stato visibile, riferimenti alle richieste e callback riutilizzabili tra rendering.
import { useCallback, useEffect, useRef, useState } from 'react'
// I link usano la navigazione React Router, mantenendo l’app caricata quando cambia il percorso.
import { Link as RouterLink } from 'react-router'
// La vista richiede sia i riepiloghi delle analisi sia lo stato dei servizi tramite lo stesso client autenticato.
import { AnalysisApiError, getDashboardSnapshot, getSystemStatus } from '../api/analysisApi'
// L’identità condivisa fornisce il nome nell’intestazione, mentre le statistiche arrivano dalla API.
import { useAuth } from '../auth/useAuth'
import { PageHeader } from '../components/PageHeader'
import { RiskChip } from '../components/RiskChip'
import { SectionCard } from '../components/SectionCard'
import { EmptyState, LoadingState } from '../components/StatePanels'
import { StatusChip } from '../components/StatusChip'
// Gli import type descrivono i dati usati dalla pagina e vengono eliminati dal JavaScript prodotto.
import type {
  DashboardRiskDistributionEntry,
  DashboardSnapshot,
  SystemStatusSnapshot,
} from '../types/domain'
import { formatDateTime, getPresentationAnalysisStatus } from '../utils/formatters'

// Fissa l’ordine visuale dei rischi dal critico al basso indipendentemente dall’ordine della risposta.
const riskOrder: DashboardRiskDistributionEntry['risk_level'][] = ['critical', 'high', 'medium', 'low']

// L’interfaccia raccoglie i due snapshot necessari alla pagina in un unico stato tipizzato.
interface DashboardViewState {
  snapshot: DashboardSnapshot
  systemStatus: SystemStatusSnapshot
}

// Traduce gli errori di sessione e permesso in un messaggio della Dashboard.
function getDashboardErrorMessage(error: unknown) {
  // Solo un errore del client espone lo status da distinguere come sessione scaduta o permesso negato.
  if (error instanceof AnalysisApiError) {
    // Un 401 viene presentato come sessione non più valida; il client ha già gestito il suo eventuale retry.
    if (error.status === 401) {
      return "La sessione non è più valida. Effettua nuovamente l'accesso."
    }
    // Un 403 segnala che l’identità non può consultare la dashboard richiesta.
    if (error.status === 403) {
      return 'Non hai i permessi per visualizzare la dashboard.'
    }
  }

  return 'La dashboard non è temporaneamente disponibile.'
}

// Associa il rischio ricevuto al colore della barra; il calcolo del rischio resta esterno alla pagina.
function getRiskBarColor(riskLevel: DashboardRiskDistributionEntry['risk_level']) {
  // Seleziona il colore della barra per il livello ricevuto, mantenendo coerente la distinzione visiva dei rischi.
  switch (riskLevel) {
    case 'critical':
      return '#8a1e1e'
    case 'high':
      return '#e46a1a'
    case 'medium':
      return '#c7a300'
    case 'low':
      return '#27845d'
  }
}

// filter conta i servizi healthy per visualizzare il rapporto rispetto ai servizi presenti nello snapshot.
function getSystemStatusSummary(snapshot: SystemStatusSnapshot) {
  // Conta gli elementi healthy dello snapshot, non il numero delle repliche dentro ogni servizio.
  const healthyServices = snapshot.services.filter((service) => service.status === 'healthy').length
  // Produce un rapporto testuale tra servizi operativi e numero di servizi riportati dal backend.
  return `${healthyServices}/${snapshot.services.length}`
}

export function DashboardPage() {
  // Il custom hook legge dal context il nome da mostrare nell’intestazione.
  const { user } = useAuth()
  // useRef mantiene controller e sequenza delle richieste senza provocare rendering.
  // Conserva il controller della lettura corrente per annullarla nel cleanup o prima di una nuova lettura.
  const requestControllerRef = useRef<AbortController | null>(null)
  // Il numero di sequenza identifica l’ultima richiesta avviata senza introdurre uno stato visibile.
  const requestSequenceRef = useRef(0)

  // useState conserva dati e feedback, distinguendo il primo caricamento dall’aggiornamento manuale.
  // Indica il caricamento dei dati iniziali e governa la vista di attesa al posto del contenuto.
  const [isLoading, setIsLoading] = useState(true)
  // Indica una lettura di aggiornamento, così la UI può mostrare attesa mantenendo i dati già caricati.
  const [isRefreshing, setIsRefreshing] = useState(false)
  // Conserva gli snapshot necessari alla vista; null indica che non è ancora disponibile un caricamento riuscito.
  const [data, setData] = useState<DashboardViewState | null>(null)
  // Conserva il messaggio di errore della lettura per mostrare il pannello o l’avviso della pagina.
  const [error, setError] = useState<string | null>(null)

  // useCallback stabilizza il caricamento asincrono e annulla la richiesta precedente prima del nuovo tentativo.
  const loadDashboard = useCallback(async (showLoader: boolean) => {
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
      // Promise.all avvia le due letture insieme e richiede il successo di entrambe; il destructuring separa le risposte.
      // Conserva lo snapshot API della pagina e viene sostituito quando arriva una lettura valida.
      const [snapshot, systemStatus] = await Promise.all([
        // La GET dashboard fornisce conteggi, distribuzione e record recenti nel perimetro autorizzato dal backend.
        getDashboardSnapshot(controller.signal),
        // La GET dello stato fornisce servizi e istante del controllo, usando lo stesso segnale di annullamento.
        getSystemStatus(controller.signal),
      ])

      // Non applica un risultato ormai superato da una lettura più recente.
      if (requestId !== requestSequenceRef.current) {
        return
      }

      // Memorizza insieme i due risultati soltanto dopo il successo di entrambe le Promise.
      setData({ snapshot, systemStatus })
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

      // Un errore di una delle due letture produce un messaggio della dashboard senza applicare risultati parziali.
      setError(getDashboardErrorMessage(nextError))
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

  // L’effetto avvia un caricamento al montaggio e annulla timer e richiesta nella pulizia; non è un polling periodico.
  useEffect(() => {
    // Pianifica un’attività cancellabile; un timeout non ripete automaticamente l’operazione come un intervallo.
    const timer = window.setTimeout(() => {
      // Il timeout iniziale avvia il caricamento; le letture successive partono dal pulsante Aggiorna.
      void loadDashboard(true)
    }, 0)

    // React esegue questa pulizia prima di ripetere l’effetto al cambio delle dipendenze e quando smonta il componente.
    return () => {
      window.clearTimeout(timer)
      // Annulla la lettura ancora in corso, se presente, prima di sostituirla o lasciare la pagina.
      requestControllerRef.current?.abort()
    }
  }, [loadDashboard])

  // Mostra il caricamento a pagina intera soltanto finché manca anche il primo insieme di dati.
  if (isLoading && data === null) {
    return (
      <LoadingState
        title="Preparazione della Dashboard"
        description="Sto raccogliendo riepilogo analisi, rischio e stato dei servizi."
      />
    )
  }

  // Senza un caricamento riuscito mostra uno stato vuoto con retry, evitando accessi ai campi degli snapshot.
  if (data === null) {
    return (
      <EmptyState
        title="Dashboard non disponibile"
        description={error ?? 'I dati della dashboard non sono ancora disponibili.'}
        action={
          <Button variant="contained" startIcon={<RefreshRoundedIcon />} onClick={() => void loadDashboard(true)}>
            Riprova
          </Button>
        }
      />
    )
  }

  // Il destructuring separa i dati analitici da quelli infrastrutturali conservati nello stesso stato.
  const { snapshot, systemStatus } = data
  const activeIncidents =
    snapshot.risk_distribution.find((entry) => entry.risk_level === 'critical')?.count ?? 0
      + (snapshot.risk_distribution.find((entry) => entry.risk_level === 'high')?.count ?? 0)
  // Somma i job processing e queued per rappresentare il lavoro ancora non concluso.
  const activeProcessing = snapshot.summary.processing + snapshot.summary.queued
  // Usa il totale aggregato della API e non la sola lunghezza delle analisi recenti.
  const totalAnalyses = snapshot.summary.total_analyses
  // Converte lo snapshot dei servizi nel rapporto sintetico mostrato dalla card operativa.
  const systemSummary = getSystemStatusSummary(systemStatus)
  // Formatta l’istante dello snapshot dei servizi per l’indicazione di aggiornamento dell’intestazione.
  const lastCheckedAt = formatDateTime(systemStatus.checked_at)
  // reduce somma i conteggi per ottenere il denominatore delle percentuali di rischio.
  const totalForRiskDistribution = snapshot.risk_distribution.reduce((sum, entry) => sum + entry.count, 0)
  // filter esclude i giorni senza analisi e slice conserva gli ultimi quattro elementi rimasti.
  const analysesOverTime = snapshot.analyses_over_time
    .filter((entry) => entry.count > 0)
    .slice(-4)
  // Trova il massimo dei conteggi selezionati, con minimo 1 per evitare una divisione per zero nelle barre.
  const maxAnalysesOverTimeCount = Math.max(...analysesOverTime.map((entry) => entry.count), 1)
  // map riordina i rischi e calcola le percentuali; optional chaining e ?? gestiscono categorie assenti.
  const normalizedRiskDistribution = riskOrder.map((riskLevel) => {
    // Cerca il conteggio corrispondente al livello attualmente elaborato dal map.
    const entry = snapshot.risk_distribution.find((item) => item.risk_level === riskLevel)
    // Una categoria assente viene rappresentata con zero, così tutti i livelli rimangono visibili.
    const count = entry?.count ?? 0
    // Calcola la percentuale arrotondata sul totale dei livelli, usando zero quando il denominatore è nullo.
    const percentage = totalForRiskDistribution === 0 ? 0 : Math.round((count / totalForRiskDistribution) * 100)
    // Restituisce un oggetto di presentazione con livello, conteggio e percentuale usati da badge e barra.
    return { riskLevel, count, percentage }
  })

  return (
    <Stack spacing={3}>
      {/* L’intestazione presenta il contesto della pagina e le eventuali azioni passate attraverso le props. */}
      <PageHeader
        title={`Benvenuto ${user?.displayName ?? 'Utente'}`}
        description="Monitora le analisi recenti e consulta l'andamento reale della piattaforma."
        action={
          <Stack direction="row" spacing={1.25}>
            <Button
              variant="outlined"
              startIcon={<RefreshRoundedIcon />}
              disabled={isRefreshing}
              onClick={() => void loadDashboard(false)}
            >
              Aggiorna
            </Button>
            <Button
              component={RouterLink}
              to="/new-analysis"
              variant="contained"
              startIcon={<UploadFileRoundedIcon />}
            >
              Nuova analisi
            </Button>
          </Stack>
        }
        highlight={`Aggiornata ${lastCheckedAt}`}
      />

      {/* Un errore successivo al caricamento viene mostrato insieme ai dati già disponibili. */}
      {error ? <Alert severity="warning">{error}</Alert> : null}

      <Grid container spacing={2}>
        {[
          { label: 'Analisi che richiedono attenzione', value: activeIncidents },
          { label: 'Analisi in coda o in elaborazione', value: activeProcessing },
          { label: 'Servizi operativi', value: systemSummary },
          { label: 'Analisi totali', value: totalAnalyses },
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
                minWidth: 0,
              }}
            >
              <Typography
                variant="h3"
                sx={{ minWidth: 78, pl: 0.75, fontSize: '3.15rem', fontWeight: 700, lineHeight: 1 }}
              >
                {metric.value}
              </Typography>
              <Typography sx={{ fontSize: '1.15rem', lineHeight: 1.35, fontWeight: 600 }}>
                {metric.label}
              </Typography>
            </Box>
          </Grid>
        ))}
      </Grid>

      <Grid container spacing={3}>
        <Grid size={{ xs: 12, lg: 6 }}>
          <SectionCard title="Distribuzione del rischio" subtitle="Conteggi reali per livello">
            {/* Se non ci sono conteggi di rischio mostra uno stato vuoto invece di barre prive di dati. */}
            {totalForRiskDistribution === 0 ? (
              <EmptyState
                title="Distribuzione non disponibile"
                description="I livelli di rischio appariranno qui dopo le prime analisi completate."
              />
            ) : (
              <Stack spacing={2.1} sx={{ height: '100%', justifyContent: 'space-evenly' }}>
                {/* Crea una riga per livello con badge, numero di file e barra percentuale. */}
                {normalizedRiskDistribution.map((item) => (
                  <Box key={item.riskLevel}>
                    <Stack direction="row" sx={{ justifyContent: 'space-between', mb: 0.8 }}>
                      <RiskChip risk={item.riskLevel} />
                      <Typography color="text.secondary">
                        {item.count} file · {item.percentage}%
                      </Typography>
                    </Stack>
                    {/* La barra determinate visualizza una percentuale della distribuzione, non l’avanzamento di una scansione. */}
                    <LinearProgress
                      variant="determinate"
                      value={item.percentage}
                      sx={{
                        height: 13,
                        borderRadius: 99,
                        bgcolor: 'rgba(18, 32, 47, 0.08)',
                        '& .MuiLinearProgress-bar': {
                          bgcolor: getRiskBarColor(item.riskLevel),
                        },
                      }}
                    />
                  </Box>
                ))}
              </Stack>
            )}
          </SectionCard>
        </Grid>

        <Grid size={{ xs: 12, lg: 6 }}>
          <SectionCard title="Andamento analisi" subtitle="Aggregazione reale per giorno di creazione">
            {/* L’andamento compare soltanto se restano date con conteggi positivi dopo il filtro. */}
            {analysesOverTime.length === 0 ? (
              <EmptyState
                title="Nessun andamento disponibile"
                description="Il grafico temporale apparirà dopo le prime analisi persistite."
              />
            ) : (
              <Stack spacing={2.1} sx={{ height: '100%', justifyContent: 'space-evenly' }}>
                {/* Ogni giorno selezionato produce una barra proporzionata al massimo, non alla somma dei conteggi. */}
                {analysesOverTime.map((entry) => {
                  // Scala il conteggio giornaliero sul massimo visibile per confrontare le altezze relative delle barre.
                  const percentage = Math.round((entry.count / maxAnalysesOverTimeCount) * 100)
                  return (
                    <Box key={entry.bucket_date}>
                      <Stack direction="row" sx={{ justifyContent: 'space-between', mb: 0.8 }}>
                        <Typography sx={{ fontWeight: 600 }}>
                          {formatDateTime(`${entry.bucket_date}T00:00:00Z`).slice(0, 10)}
                        </Typography>
                        <Typography color="text.secondary">
                          {entry.count} {entry.count === 1 ? 'analisi' : 'analisi'}
                        </Typography>
                      </Stack>
                      <LinearProgress
                        variant="determinate"
                        value={percentage}
                        sx={{
                          height: 13,
                          borderRadius: 99,
                          bgcolor: 'rgba(15, 108, 120, 0.08)',
                        }}
                      />
                    </Box>
                  )
                })}
              </Stack>
            )}
          </SectionCard>
        </Grid>

        <Grid size={{ xs: 12 }}>
          <SectionCard
            title="Analisi recenti"
            subtitle="Ultimi record reali presenti nel database"
            action={
              <Button component={RouterLink} to="/history" endIcon={<ArrowForwardRoundedIcon />}>
                Vai alla cronologia
              </Button>
            }
          >
            {/* La sezione recente distingue l’assenza di record da una lista di scansioni consultabili nel riepilogo. */}
            {snapshot.recent_analyses.length === 0 ? (
              <EmptyState
                title="Nessuna analisi disponibile"
                description="La piattaforma non ha ancora ricevuto file da analizzare."
              />
            ) : (
              <List disablePadding>
                {/* Ogni analisi ricevuta produce una voce con stato, rischio, nome, data e identificativo. */}
                {snapshot.recent_analyses.map((analysis, index) => (
                  <Box key={analysis.id}>
                    <ListItem
                      disableGutters
                      secondaryAction={<RiskChip risk={analysis.risk_level} />}
                      sx={{ py: 1.4, gap: 2, minWidth: 0 }}
                    >
                      <ListItemText
                        sx={{ minWidth: 0, mr: 2 }}
                        primary={
                          <Stack
                            direction={{ xs: 'column', md: 'row' }}
                            spacing={1}
                            sx={{ alignItems: { xs: 'flex-start', md: 'center' }, minWidth: 0 }}
                          >
                            <Typography
                              sx={{
                                fontWeight: 700,
                                minWidth: 0,
                                overflow: 'hidden',
                                textOverflow: 'ellipsis',
                                whiteSpace: 'nowrap',
                              }}
                              title={analysis.file_name}
                            >
                              {analysis.file_name}
                            </Typography>
                            <StatusChip status={getPresentationAnalysisStatus(analysis)} />
                          </Stack>
                        }
                        secondary={`${formatDateTime(analysis.created_at)} • ID ${analysis.id}`}
                      />
                    </ListItem>
                    {/* Aggiunge separatori tra le voci, evitando una linea dopo l’ultimo elemento. */}
                    {index < snapshot.recent_analyses.length - 1 ? <Divider /> : null}
                  </Box>
                ))}
              </List>
            )}
          </SectionCard>
        </Grid>
      </Grid>
    </Stack>
  )
}
