/**
 * Funzioni di presentazione per i dati restituiti dal backend.
 *
 * Il loro scopo non è cambiare il significato delle informazioni, ma renderle
 * leggibili nelle pagine del frontend: date italiane, dimensioni file, hash,
 * tipi MIME, entropia e stato visuale derivato da `scan_error`.
 */
import type { AnalysisApiRecord, AnalysisStatus } from '../types/domain'

// Intl formatta la data in italiano usando il fuso del browser, poiché non viene specificato timeZone.
const italianDateTimeFormatter = new Intl.DateTimeFormat('it-IT', {
  day: '2-digit',
  month: '2-digit',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
})

// La union accetta oggetti Date, timestamp numerici, stringhe o valori assenti.
type DateTimeValue = Date | number | string | null | undefined

// Il destructuring separa data e ora; map(Number) converte le parti e Date usa mesi numerati da zero.
function parseDateTimeInput(value: string) {
  const normalizedValue = value.trim().replace('T', ' ')
  const [datePart, timePart = '00:00:00'] = normalizedValue.split(' ')
  const [year, month, day] = datePart.split('-').map(Number)
  const [hour = 0, minute = 0, second = 0] = timePart.split(':').map(Number)

  return new Date(year, (month || 1) - 1, day || 1, hour, minute, second)
}

// Controlla la validità della data e prova il formato semplificato solo se il parsing nativo non riesce.
function normalizeDateTimeValue(value: DateTimeValue) {
  // Riusa l’oggetto Date solo se il suo timestamp è valido.
  if (value instanceof Date) {
    return Number.isNaN(value.getTime()) ? null : value
  }

  // Interpreta un numero come timestamp in millisecondi, come quello fornito da File.lastModified.
  if (typeof value === 'number') {
    const date = new Date(value)
    return Number.isNaN(date.getTime()) ? null : date
  }

  // Rifiuta i valori assenti o non supportati prima di eseguire operazioni sulle stringhe.
  if (typeof value !== 'string') {
    return null
  }

  const trimmedValue = value.trim()
  // Una stringa vuota dopo trim non viene interpretata come una data.
  if (!trimmedValue) {
    return null
  }

  // Prova prima il parser nativo Date per riconoscere timestamp testuali come quelli delle API.
  const nativeParsedDate = new Date(trimmedValue)
  // Accetta il parsing nativo solo se produce un timestamp valido.
  if (!Number.isNaN(nativeParsedDate.getTime())) {
    return nativeParsedDate
  }

  const normalizedValue = trimmedValue.replace('T', ' ')
  // Il fallback ammette una data numerica e un’ora opzionale; altri formati restano non interpretabili.
  if (!/^\d{4}-\d{2}-\d{2}(?: \d{2}:\d{2}(?::\d{2})?)?$/.test(normalizedValue)) {
    return null
  }

  const [datePart, timePart] = normalizedValue.split(' ')
  // Completa l’ora con secondi zero se mancano e usa mezzanotte quando non è indicata.
  const completedTimePart = timePart
    ? timePart.length === 5
      ? `${timePart}:00`
      : timePart
    : '00:00:00'

  // Passa al parser semplificato una stringa con data e ora complete.
  return parseDateTimeInput(`${datePart} ${completedTimePart}`)
}

// Conserva il testo non interpretabile invece di mostrare una data artificiale; i valori assenti producono testo vuoto.
export function formatDateTime(value: DateTimeValue) {
  if (typeof value === 'string') {
    const trimmedValue = value.trim()
    // Una stringa vuota dopo trim non viene interpretata come una data.
    if (!trimmedValue) {
      return value
    }
  }

  // Converte l’input eterogeneo in Date oppure null prima della formattazione italiana.
  const normalizedDate = normalizeDateTimeValue(value)
  // Se la conversione non riesce conserva una stringa originale o restituisce testo vuoto per altri valori.
  if (!normalizedDate) {
    return typeof value === 'string' ? value : ''
  }

  // Produce il testo finale con giorno, mese, anno e ora secondo il formato condiviso.
  return italianDateTimeFormatter.format(normalizedDate)
}

// Converte l’ID in maiuscolo solo per mostrarlo: URL e richieste mantengono l’identificativo originale.
export function getDisplayAnalysisId(analysisId: string) {
  // Restituisce una nuova stringa per la visualizzazione senza modificare l’ID passato dal chiamante.
  return analysisId.toUpperCase()
}

// Esprime File.size e size_bytes in B, KB o MB usando multipli di 1024.
export function formatBytesToLabel(sizeBytes: number) {
  // Per file sotto un KiB mantiene il valore in byte senza introdurre decimali.
  if (sizeBytes < 1024) {
    return `${sizeBytes} B`
  }

  // Per dimensioni sotto un MiB divide per 1024 e mostra un decimale con etichetta KB.
  if (sizeBytes < 1024 * 1024) {
    return `${(sizeBytes / 1024).toFixed(1)} KB`
  }

  // Negli altri casi usa la scala in multipli di 1024 al quadrato e mostra due decimali.
  return `${(sizeBytes / (1024 * 1024)).toFixed(2)} MB`
}

export function getDisplayEventId(eventId: string) {
  // Estrae solo le cifre dall’identificativo evento ricevuto, scartando gli altri caratteri.
  const numericId = eventId.replace(/\D/g, '')
  // Costruisce l’etichetta con prefisso fisso e almeno quattro cifre, senza ricavare l’anno da una data.
  return `EVT-2026-${numericId.padStart(4, '0') || '0000'}`
}

export function formatNullableText(value: string | null, unavailableLabel = 'Non disponibile') {
  // Un testo assente viene sostituito con l’etichetta di indisponibilità passata dal chiamante.
  if (value === null) {
    return unavailableLabel
  }

  const trimmedValue = value.trim()
  // Restituisce il testo ripulito se non vuoto, altrimenti lo stesso fallback usato per null.
  return trimmedValue ? trimmedValue : unavailableLabel
}

// Presenta completed con scan_error come failed senza modificare status nel record API originale.
export function getPresentationAnalysisStatus(analysis: AnalysisApiRecord): AnalysisStatus {
  // L’errore di scansione viene presentato come fallimento solo per un job tecnicamente concluso.
  if (analysis.status === 'completed' && analysis.verdict === 'scan_error') {
    return 'failed'
  }

  // Negli altri casi mantiene lo stato tecnico ricevuto dalla API.
  return analysis.status
}

// Per i metadati null distingue un fallimento dall’informazione non ancora disponibile.
export function formatMimeType(value: string | null, status: AnalysisStatus) {
  // Se il metadato esiste lo restituisce o lo formatta senza sostituirlo con un testo di attesa.
  if (value !== null) {
    return value
  }

  // Per un fallimento mostra indisponibilità del dato anziché prometterne l’arrivo.
  if (status === 'failed') {
    return 'Non disponibile'
  }

  return 'Non ancora disponibile'
}

// Mostra l’hash ricevuto oppure un testo di attesa/assenza: il browser non ricalcola SHA-256.
export function formatSha256(value: string | null, status: AnalysisStatus) {
  // Se il metadato esiste lo restituisce o lo formatta senza sostituirlo con un testo di attesa.
  if (value !== null) {
    return value
  }

  // Per un fallimento mostra indisponibilità del dato anziché prometterne l’arrivo.
  if (status === 'failed') {
    return 'Non disponibile'
  }

  return 'Non ancora disponibile'
}

// Arrotonda l’entropia ricevuta a due decimali e rende espliciti i valori mancanti.
export function formatEntropy(value: number | null, status: AnalysisStatus) {
  // Se il metadato esiste lo restituisce o lo formatta senza sostituirlo con un testo di attesa.
  if (value !== null) {
    return value.toFixed(2)
  }

  // Per un fallimento mostra indisponibilità del dato anziché prometterne l’arrivo.
  if (status === 'failed') {
    return 'Non disponibile'
  }

  return 'Non ancora disponibile'
}

// Traduce true, false e null in corrispondenza, disallineamento o attesa/assenza.
export function formatExtensionMatch(
  value: boolean | null,
  status: AnalysisStatus,
) {
  // Una corrispondenza esplicita produce l’etichetta positiva per estensione e contenuto.
  if (value === true) {
    return 'Corrispondenza confermata'
  }

  // Un disallineamento esplicito produce l’etichetta di incoerenza, distinta da null.
  if (value === false) {
    return 'Disallineamento rilevato'
  }

  // Per un fallimento mostra indisponibilità del dato anziché prometterne l’arrivo.
  if (status === 'failed') {
    return 'Non disponibile'
  }

  return 'In attesa'
}

// Le pagine continuano il polling soltanto per i due stati non terminali queued e processing.
export function hasPendingAnalysisStatus(status: AnalysisStatus) {
  // Restituisce il booleano usato dai cicli di polling per riconoscere i job non terminali.
  return status === 'queued' || status === 'processing'
}
