/**
 * Configurazione browser-facing per il frontend.
 *
 * Qui vengono raccolti i valori di ambiente che il codice React usa più spesso
 * quando deve parlare con il backend. In locale l'URL predefinito punta a Kong
 * su `http://localhost:8000`, quindi il browser non contatta direttamente
 * l'Analysis API ma attraversa il gateway previsto dall'architettura.
 *
 * Le pagine che caricano o interrogano analisi, profilo, dashboard e stato del
 * sistema dipendono indirettamente da questi valori.
 */
// Rimuove gli spazi esterni dall’URL configurato; una stringa vuota usa il fallback locale del gateway.
export const analysisApiUrl = import.meta.env.VITE_ANALYSIS_API_URL?.trim() || 'http://localhost:8000'

// Converte il valore testuale in intero positivo oppure usa il limite predefinito; è una validazione lato browser.
function parsePositiveInteger(value: string | undefined, fallbackValue: number): number {
  // parseInt legge un intero in base 10 dalla stringa; non richiede che tutto il testo sia numerico.
  const parsed = Number.parseInt(value?.trim() || '', 10)
  // Accetta solo il risultato intero positivo, altrimenti mantiene il valore predefinito.
  return Number.isInteger(parsed) && parsed > 0 ? parsed : fallbackValue
}

// Il limite in MB deriva dalla variabile Vite oppure da 250 e alimenta il controllo preliminare dell’upload.
export const maxUploadSizeMb = parsePositiveInteger(import.meta.env.VITE_MAX_UPLOAD_SIZE_MB, 250)
// Converte il limite in byte per confrontarlo con File.size prima dell’invio.
export const maxUploadSizeBytes = maxUploadSizeMb * 1024 * 1024
// Costruisce la stessa etichetta testuale usata nei messaggi e nel riepilogo del file.
export const maxUploadSizeLabel = `${maxUploadSizeMb} MB`
