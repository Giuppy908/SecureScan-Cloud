/**
 * Pagina "Nuova analisi".
 *
 * L'utente seleziona un file, lo invia al backend attraverso Kong e riceve un
 * record iniziale dell'analisi. Il risultato finale non è immediato: questa
 * pagina continua quindi a interrogare il dettaglio finché il Worker non
 * completa la pipeline antimalware.
 *
 * Le informazioni ottenute qui riappaiono poi anche in Cronologia e Dettaglio
 * analisi.
 */
import CloudUploadRoundedIcon from '@mui/icons-material/CloudUploadRounded'
import DescriptionRoundedIcon from '@mui/icons-material/DescriptionRounded'
import PlayArrowRoundedIcon from '@mui/icons-material/PlayArrowRounded'
import RefreshRoundedIcon from '@mui/icons-material/RefreshRounded'
import VisibilityRoundedIcon from '@mui/icons-material/VisibilityRounded'
import { Alert, Box, Button, CircularProgress, Grid, Paper, Stack, Typography } from '@mui/material'
// Gli hook separano dati visibili, riferimenti ai controlli e ciclo di lettura del job dopo l’upload.
import { useCallback, useEffect, useRef, useState } from 'react'
// Il link interno apre il dettaglio conservando l’app React già caricata nel browser.
import { Link as RouterLink } from 'react-router'
// Il client crea il job e ne legge il dettaglio; la classe di errore permette di riconoscere gli status HTTP.
import { AnalysisApiError, createAnalysis, getAnalysis } from '../api/analysisApi'
import { PageHeader } from '../components/PageHeader'
import { EmptyState } from '../components/StatePanels'
import { RiskChip } from '../components/RiskChip'
import { SectionCard } from '../components/SectionCard'
import { StatusChip } from '../components/StatusChip'
import { maxUploadSizeBytes, maxUploadSizeLabel } from '../config/api'
// Il record tipizzato contiene ID, stato e risultati che arriveranno progressivamente dalla API.
import type { AnalysisApiRecord } from '../types/domain'
import {
  formatBytesToLabel,
  formatDateTime,
  getDisplayAnalysisId,
  getPresentationAnalysisStatus,
  hasPendingAnalysisStatus,
} from '../utils/formatters'

// Il polling usa un ritardo di 1,5 secondi e si ferma al terzo errore consecutivo.
const pollingIntervalMs = 1500
const maxPollingErrors = 3

function getAnalysisOutcomeMessage(analysis: AnalysisApiRecord) {
  /**
   * Riassume in una frase breve lo stato corrente dell'analisi avviata.
   *
   * Serve soprattutto nella pagina "Nuova analisi", dove l'utente ha bisogno di
   * un feedback immediato prima ancora di aprire Cronologia o Dettaglio.
   */
  // Dà precedenza all’errore di scansione, anche se il job risulta tecnicamente completed.
  if (analysis.verdict === 'scan_error') {
    return analysis.error_message || "La scansione antimalware non è stata completata correttamente."
  }

  // Quando il job è fallito mostra il messaggio backend o una descrizione di riserva.
  if (analysis.status === 'failed') {
    return analysis.error_message || "L'analisi non è stata completata correttamente."
  }

  // Un job in coda è stato accettato, ma i risultati non sono ancora disponibili.
  if (analysis.status === 'queued') {
    return 'Il file è stato accodato. I risultati saranno aggiornati automaticamente.'
  }

  // Un job in lavorazione richiede ulteriori letture prima di poter mostrare il risultato finale.
  if (analysis.status === 'processing') {
    return 'L elaborazione è in corso. I risultati verranno mostrati non appena disponibili.'
  }

  // Nel ramo restante sceglie il testo in base alla presenza di indicatori, senza calcolare nuove evidenze nel browser.
  if (analysis.indicators.length === 0) {
    return 'Analisi completata senza indicatori rilevanti in questa prima versione locale.'
  }

  return 'Analisi completata con indicatori preliminari da verificare nel dettaglio.'
}

// Distingue una risorsa non trovata dagli errori temporanei durante l’aggiornamento dei risultati.
function getRefreshErrorMessage(error: unknown) {
  // Controlla il tipo dell’eccezione prima di leggerne lo status specifico del client HTTP.
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

// Il componente funzionale coordina selezione, upload e lettura del job; la scansione viene eseguita fuori dal browser.
export function NewAnalysisPage() {
  // useRef conserva il nodo input e i controlli del polling tra rendering, senza aggiornare direttamente la UI.
  // Conserva l’input nativo nascosto per aprire il selettore dal pulsante e svuotarlo nel reset.
  const inputRef = useRef<HTMLInputElement | null>(null)
  // Conserva il timeout pendente per cancellarlo quando cambia file, termina il job o si lascia la pagina.
  const pollingTimerRef = useRef<number | null>(null)
  // Rende disponibile il controller della GET corrente alla funzione stopPolling.
  const pollingControllerRef = useRef<AbortController | null>(null)
  // Il numero cresce a ogni GET: solo la risposta dell’ultima richiesta può aggiornare il riepilogo.
  const pollingRequestIdRef = useRef(0)
  // Conta i fallimenti consecutivi senza mostrare direttamente il contatore nella UI.
  const pollingErrorCountRef = useRef(0)

  // useState mantiene il file e il record ricevuto; i setter aggiornano messaggi, pulsanti e riepilogo.
  // Memorizza l’oggetto File da inviare e determina se mostrare il riepilogo e abilitare l’avvio.
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  // Tiene traccia del trascinamento per evidenziare il bordo e lo sfondo della zona di caricamento.
  const [dragActive, setDragActive] = useState(false)
  // Conserva prima il record creato e poi le versioni aggiornate restituite dal polling.
  const [analysis, setAnalysis] = useState<AnalysisApiRecord | null>(null)
  // Blocca selezione e nuovo invio durante la POST e mostra il testo di upload in corso.
  const [isSubmitting, setIsSubmitting] = useState(false)
  // Attiva il piccolo indicatore mentre una GET aggiorna lo stato del job già creato.
  const [isRefreshing, setIsRefreshing] = useState(false)
  // Contiene l’avviso locale, ad esempio quando il file supera il limite configurato.
  const [validationMessage, setValidationMessage] = useState<string | null>(null)
  // Conserva l’errore dell’invio iniziale, distinto dall’errore di aggiornamento di un job esistente.
  const [requestError, setRequestError] = useState<string | null>(null)
  // Mostra un avviso di polling conservando i dati dell’ultima risposta disponibile.
  const [refreshMessage, setRefreshMessage] = useState<string | null>(null)

  // useCallback stabilizza la pulizia: annulla timer e richiesta di polling; ?. tollera un controller assente.
  const stopPolling = useCallback(() => {
    // Se è pianificata una futura lettura la cancella e azzera l’identificativo del timeout.
    if (pollingTimerRef.current !== null) {
      window.clearTimeout(pollingTimerRef.current)
      pollingTimerRef.current = null
    }

    // Interrompe la GET in corso, se esiste; non annulla con questo riferimento la POST di upload.
    pollingControllerRef.current?.abort()
    pollingControllerRef.current = null
  }, [])

  // Usa solo il primo file; ?. e ?? gestiscono una selezione vuota, poi valida la dimensione nel browser.
  const handleFileSelection = (fileList: FileList | null) => {
    // Estrae soltanto il primo file dalla selezione o dal trascinamento e usa null se non esiste.
    const file = fileList?.[0] ?? null
    stopPolling()
    // Svuota il risultato precedente mentre viene predisposta una nuova selezione, un invio o il reset.
    setAnalysis(null)
    setRequestError(null)
    setRefreshMessage(null)

    // Una selezione vuota rimuove il file corrente e il relativo avviso, poi termina la callback.
    if (!file) {
      setSelectedFile(null)
      setValidationMessage(null)
      return
    }

    // Confronta la dimensione in byte con il limite del frontend prima di chiamare la API.
    if (file.size > maxUploadSizeBytes) {
      setSelectedFile(null)
      setValidationMessage(`Il file supera il limite di ${maxUploadSizeLabel} e non può essere inviato.`)
      return
    }

    // Conserva il file valido nello stato: il rendering successivo ne mostra nome, tipo e dimensione.
    setSelectedFile(file)
    setValidationMessage(null)
  }

  // async/await attende l’upload multipart tramite createAnalysis e salva il record iniziale restituito dalla API.
  const handleStartAnalysis = async () => {
    // Evita la POST quando manca un file o l’invio precedente risulta ancora in corso.
    if (!selectedFile || isSubmitting) {
      return
    }

    stopPolling()
    // Attiva subito lo stato di invio e prepara la UI prima di attendere la risposta HTTP.
    setIsSubmitting(true)
    setRequestError(null)
    setRefreshMessage(null)
    // Svuota il risultato precedente mentre viene predisposta una nuova selezione, un invio o il reset.
    setAnalysis(null)

    // Crea un segnale per questa richiesta; nell’upload resta locale, mentre nel polling viene salvato nel ref.
    const controller = new AbortController()

    try {
      // Invia il multipart autenticato alla raccolta analisi e attende il record iniziale con l’ID del job.
      const createdAnalysis = await createAnalysis(selectedFile, controller.signal)
      // Salvare il job provoca un rendering e permette all’effetto di avviare il polling se lo stato è pendente.
      setAnalysis(createdAnalysis)
      // Azzera i fallimenti accumulati quando si riparte o arriva una lettura valida.
      pollingErrorCountRef.current = 0
    } catch (error) {
      // Ignora gli annullamenti richiesti dal browser o dal cleanup anziché presentarli come errori applicativi.
      if (error instanceof DOMException && error.name === 'AbortError') {
        return
      }

      // Mostra il messaggio dell’errore di upload quando disponibile, altrimenti usa il testo locale di riserva.
      setRequestError(error instanceof Error ? error.message : 'Analisi non disponibile al momento.')
    } finally {
      // Il finally riabilita la UI sia dopo il successo sia dopo un errore o un annullamento dell’invio.
      setIsSubmitting(false)
    }
  }

  // Azzera lo stato della pagina e l’input nativo per consentire anche una nuova selezione dello stesso file.
  const handleReset = () => {
    stopPolling()
    setSelectedFile(null)
    // Svuota il risultato precedente mentre viene predisposta una nuova selezione, un invio o il reset.
    setAnalysis(null)
    setValidationMessage(null)
    setRequestError(null)
    setRefreshMessage(null)
    setIsRefreshing(false)
    // Azzera i fallimenti accumulati quando si riparte o arriva una lettura valida.
    pollingErrorCountRef.current = 0
    if (inputRef.current) {
      // Svuota anche il controllo DOM, così selezionare di nuovo lo stesso file può generare un nuovo evento change.
      inputRef.current.value = ''
    }
  }

  // L’effetto segue analysis e stopPolling: avvia il polling dei job pendenti e pulisce il ciclo quando cambiano o la pagina si smonta.
  useEffect(() => {
    // Senza job o con stato terminale ferma il ciclo: completed e failed non richiedono nuove letture automatiche.
    if (!analysis || !hasPendingAnalysisStatus(analysis.status)) {
      stopPolling()
      return
    }

    // Identifica il ciclo corrente dell’effetto; il cleanup lo invalida quando cambia analysis o la pagina si smonta.
    let isMounted = true

    // Il timeout avvia una singola lettura futura; sarà l’esito della GET a decidere se programmarne un’altra.
    const scheduleNext = (delayMs: number) => {
      pollingTimerRef.current = window.setTimeout(() => {
        // Il timer avvia la funzione asincrona, che gestisce al proprio interno risposta, errori e indicatore di refresh.
        void pollAnalysis()
      }, delayMs)
    }

    const pollAnalysis = async () => {
      // Non avvia una GET se questa esecuzione dell’effetto è già stata invalidata.
      if (!isMounted) {
        return
      }

      // Interrompe la GET in corso, se esiste; non annulla con questo riferimento la POST di upload.
      pollingControllerRef.current?.abort()
      // Crea un segnale per questa richiesta; nell’upload resta locale, mentre nel polling viene salvato nel ref.
      const controller = new AbortController()
      pollingControllerRef.current = controller
      // Il contatore identifica la richiesta corrente: le risposte superate non devono sostituire il risultato più recente.
      const requestId = ++pollingRequestIdRef.current

      // Rende visibile l’indicatore di aggiornamento senza cancellare il risultato già mostrato.
      setIsRefreshing(true)

      try {
        // Esegue una GET autenticata sull’ID restituito dalla POST per osservare l’avanzamento del job.
        const refreshedAnalysis = await getAnalysis(analysis.id, controller.signal)
        // Scarta risultati o errori di un ciclo terminato o di una richiesta superata da una più recente.
        if (!isMounted || requestId !== pollingRequestIdRef.current) {
          return
        }

        // Sostituisce il record con la risposta aggiornata e provoca il rendering di stato, rischio e messaggi.
        setAnalysis(refreshedAnalysis)
        setRefreshMessage(null)
        // Azzera i fallimenti accumulati quando si riparte o arriva una lettura valida.
        pollingErrorCountRef.current = 0

        // Continua soltanto per queued o processing; il risultato terminale resta visibile senza altri timeout.
        if (hasPendingAnalysisStatus(refreshedAnalysis.status)) {
          scheduleNext(pollingIntervalMs)
        }
      } catch (error) {
        // Ignora gli annullamenti richiesti dal browser o dal cleanup anziché presentarli come errori applicativi.
        if (error instanceof DOMException && error.name === 'AbortError') {
          return
        }

        // Scarta risultati o errori di un ciclo terminato o di una richiesta superata da una più recente.
        if (!isMounted || requestId !== pollingRequestIdRef.current) {
          return
        }

        // Incrementa gli errori consecutivi e prepara l’avviso prima di valutare un altro tentativo.
        pollingErrorCountRef.current += 1
        setRefreshMessage(getRefreshErrorMessage(error))

        // Un ID non più trovato interrompe il polling invece di continuare a interrogare la stessa risorsa.
        if (error instanceof AnalysisApiError && error.status === 404) {
          return
        }

        // Dopo un errore aumenta il ritardo; il 404 interrompe invece il tentativo di aggiornare un job assente.
        if (pollingErrorCountRef.current < maxPollingErrors) {
          // Moltiplica l’intervallo base per il numero di errori più uno: l’attesa cresce dopo i fallimenti.
          const nextDelay = pollingIntervalMs * (pollingErrorCountRef.current + 1)
          scheduleNext(nextDelay)
        }
      } finally {
        // Il finally spegne l’indicatore soltanto se sta ancora completando la richiesta corrente.
        if (isMounted && requestId === pollingRequestIdRef.current) {
          setIsRefreshing(false)
        }
      }
    }

    scheduleNext(pollingIntervalMs)

    return () => {
      // Il cleanup invalida questa esecuzione prima di fermare timeout e richiesta tramite stopPolling.
      isMounted = false
      stopPolling()
    }
  }, [analysis, stopPolling])

  return (
    <Stack spacing={3}>
      {/* Mostra titolo e descrizione della pagina, indipendentemente dallo stato della selezione. */}
      <PageHeader
        title="Nuova analisi"
        description="Carica un file, controlla i metadati principali e avvia l'analisi reale sulla Analysis API locale."
      />

      <Grid container spacing={3} sx={{ alignItems: 'stretch' }}>
        <Grid size={{ xs: 12, lg: 7 }}>
          {/* La zona di trascinamento impedisce l’apertura predefinita del file e inoltra la selezione allo stesso controllo dell’input. */}
          <Paper
            onDragOver={(event) => {
              // Impedisce al browser di gestire il trascinamento o aprire il file fuori dall’app.
              event.preventDefault()
              // Durante l’invio ignora nuove interazioni di trascinamento per non cambiare il file in lavorazione.
              if (isSubmitting) {
                return
              }
              setDragActive(true)
            }}
            onDragLeave={() => setDragActive(false)}
            onDrop={(event) => {
              // Impedisce al browser di gestire il trascinamento o aprire il file fuori dall’app.
              event.preventDefault()
              setDragActive(false)
              // Durante l’invio ignora nuove interazioni di trascinamento per non cambiare il file in lavorazione.
              if (isSubmitting) {
                return
              }
              // Inoltra i file trascinati alla stessa validazione usata dal selettore nativo.
              handleFileSelection(event.dataTransfer.files)
            }}
            sx={{
              p: { xs: 2.5, md: 3 },
              minHeight: 260,
              height: '100%',
              borderRadius: 3,
              border: '2px dashed',
              borderColor: dragActive ? 'primary.main' : 'divider',
              bgcolor: dragActive ? 'rgba(15, 108, 120, 0.06)' : 'rgba(251, 253, 254, 0.72)',
              display: 'grid',
              placeItems: 'center',
            }}
          >
            <Stack spacing={1.5} sx={{ alignItems: 'center', textAlign: 'center', maxWidth: 460 }}>
              <Box
                sx={{
                  width: 72,
                  height: 72,
                  borderRadius: '50%',
                  display: 'grid',
                  placeItems: 'center',
                  bgcolor: 'rgba(15, 108, 120, 0.1)',
                  color: 'primary.main',
                }}
              >
                <CloudUploadRoundedIcon sx={{ fontSize: 34 }} />
              </Box>
              <Typography variant="h4">Trascina qui un file oppure selezionalo dal dispositivo.</Typography>
              <Typography color="text.secondary">
                Dimensione massima: {maxUploadSizeLabel}. Il file non verrà eseguito.
              </Typography>
              <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5}>
                <Button variant="contained" onClick={() => inputRef.current?.click()} disabled={isSubmitting}>
                  Seleziona file
                </Button>
                {selectedFile ? (
                  <Button variant="outlined" onClick={handleReset} disabled={isSubmitting}>
                    Reimposta
                  </Button>
                ) : null}
              </Stack>
              {/* L’input nascosto espone i file selezionati a onChange; il pulsante lo apre usando inputRef. */}
              <input
                ref={inputRef}
                type="file"
                hidden
                onChange={(event) => handleFileSelection(event.target.files)}
              />
            </Stack>
          </Paper>
        </Grid>

        <Grid size={{ xs: 12, lg: 5 }} sx={{ minWidth: 0 }}>
          {/* La card alterna i metadati del File locale e lo stato vuoto prima dell’invio. */}
          <SectionCard title="Riepilogo file" subtitle="Dati essenziali prima dell'avvio">
            {selectedFile ? (
              <Stack spacing={1.5}>
                <Stack
                  direction="row"
                  spacing={1.5}
                  sx={{
                    p: 1.5,
                    borderRadius: 2,
                    bgcolor: 'rgba(15, 108, 120, 0.06)',
                    alignItems: 'center',
                    overflow: 'hidden',
                  }}
                >
                  <DescriptionRoundedIcon color="primary" sx={{ flexShrink: 0 }} />
                  <Box
                    sx={{
                      flex: 1,
                      minWidth: 0,
                      maxWidth: '100%',
                      overflow: 'hidden',
                    }}
                  >
                    <Typography
                      title={selectedFile.name}
                      sx={{
                        fontWeight: 700,
                        display: 'block',
                        width: '100%',
                        maxWidth: '100%',
                        minWidth: 0,
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        whiteSpace: 'nowrap',
                      }}
                    >
                      {selectedFile.name}
                    </Typography>
                    <Typography
                      variant="body2"
                      color="text.secondary"
                      sx={{
                        display: 'block',
                        width: '100%',
                        maxWidth: '100%',
                        minWidth: 0,
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        whiteSpace: 'nowrap',
                      }}
                    >
                      {selectedFile.type || 'application/octet-stream'} • {formatBytesToLabel(selectedFile.size)}
                    </Typography>
                  </Box>
                </Stack>
                <Grid container spacing={1.5}>
                  <Grid size={{ xs: 6 }}>
                    <Typography variant="body2" color="text.secondary">
                      Ultima modifica
                    </Typography>
                    <Typography sx={{ fontWeight: 700 }}>
                      {formatDateTime(selectedFile.lastModified)}
                    </Typography>
                  </Grid>
                  <Grid size={{ xs: 6 }}>
                    <Typography variant="body2" color="text.secondary">
                      Limite upload
                    </Typography>
                    <Typography sx={{ fontWeight: 700 }}>{maxUploadSizeLabel}</Typography>
                  </Grid>
                </Grid>
                {/* L’Alert segnala la validazione locale; il messaggio è mostrato anche quando il file è stato rifiutato. */}
                {validationMessage ? <Alert severity="warning">{validationMessage}</Alert> : null}
                {/* L’errore della POST appare vicino al pulsante di avvio per consentire un nuovo tentativo. */}
                {requestError ? <Alert severity="error">{requestError}</Alert> : null}
                <Button
                  variant="contained"
                  startIcon={<PlayArrowRoundedIcon />}
                  onClick={handleStartAnalysis}
                  disabled={isSubmitting || !selectedFile}
                >
                  {isSubmitting ? 'Invio in corso...' : 'Avvia analisi'}
                </Button>
              </Stack>
            ) : (
              <Stack spacing={2}>
                <EmptyState title="Nessun file selezionato" description="" />
                {/* L’Alert segnala la validazione locale; il messaggio è mostrato anche quando il file è stato rifiutato. */}
                {validationMessage ? <Alert severity="warning">{validationMessage}</Alert> : null}
              </Stack>
            )}
          </SectionCard>
        </Grid>
      </Grid>

      {/* Il rendering condizionale distingue selezione, invio, attesa del record e risultato aggiornato dal polling. */}
      <SectionCard title="Esito dell'analisi" subtitle="Risposta reale restituita dalla Analysis API locale">
        <Stack spacing={3}>
          {!selectedFile ? (
            <Alert severity="info">Seleziona un file per avviare una nuova analisi.</Alert>
          ) : isSubmitting ? (
            <Alert severity="info">Invio del file in corso. Attendi la risposta del backend locale.</Alert>
          ) : !analysis ? (
            <Alert severity="info">L'analisi non è ancora stata avviata.</Alert>
          ) : (
            <Stack spacing={2}>
              <Stack direction="row" spacing={1.2} sx={{ alignItems: 'center', flexWrap: 'wrap' }}>
                {/* Il badge usa lo stato di presentazione, che tratta scan_error come fallimento senza cambiare il record API. */}
                <StatusChip status={getPresentationAnalysisStatus(analysis)} />
                {/* Il rischio viene visualizzato dal valore restituito dal backend, senza essere calcolato in questa pagina. */}
                <RiskChip risk={analysis.risk_level} />
                {/* L’indicatore appare soltanto mentre si legge di nuovo il job e non sostituisce il riepilogo. */}
                {isRefreshing ? (
                  <Stack direction="row" spacing={1} sx={{ alignItems: 'center' }}>
                    <CircularProgress size={16} />
                    <Typography variant="body2" color="text.secondary">
                      Aggiornamento in corso
                    </Typography>
                  </Stack>
                ) : null}
              </Stack>
              {/* Un errore di aggiornamento compare come avviso lasciando consultabile l’ultimo risultato. */}
              {refreshMessage ? <Alert severity="warning">{refreshMessage}</Alert> : null}
              <Typography color="text.secondary">{getAnalysisOutcomeMessage(analysis)}</Typography>
              <Grid container spacing={1.5}>
                <Grid size={{ xs: 12, md: 6 }}>
                  <Typography variant="body2" color="text.secondary">
                    ID analisi
                  </Typography>
                  <Typography sx={{ fontWeight: 700 }}>{getDisplayAnalysisId(analysis.id)}</Typography>
                </Grid>
                <Grid size={{ xs: 12, md: 6 }}>
                  <Typography variant="body2" color="text.secondary">
                    Data creazione
                  </Typography>
                  <Typography sx={{ fontWeight: 700 }}>{formatDateTime(analysis.created_at)}</Typography>
                </Grid>
              </Grid>
              <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5}>
                <Button
                  variant="contained"
                  component={RouterLink}
                  to={`/analyses/${analysis.id}`}
                  startIcon={<VisibilityRoundedIcon />}
                >
                  Apri dettaglio
                </Button>
                <Button variant="outlined" startIcon={<RefreshRoundedIcon />} onClick={handleReset}>
                  Nuova analisi
                </Button>
              </Stack>
            </Stack>
          )}
        </Stack>
      </SectionCard>
    </Stack>
  )
}
