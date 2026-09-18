/**
 * Traduzioni brevi dei valori di dominio usati nell'interfaccia.
 *
 * Backend e tipi condivisi mantengono gli identificativi tecnici in inglese;
 * questo file li converte nelle etichette italiane mostrate in badge, tabelle,
 * card e pannelli del frontend.
 */
import type { AnalysisStatus, RiskLevel, ServiceStatus, UserRole } from '../types/domain'

// La union ammette stati di analisi e di servizio; switch sceglie soltanto la traduzione visualizzata.
export function getStatusLabel(status: AnalysisStatus | ServiceStatus) {
  // Seleziona la traduzione del valore ricevuto; il return di ogni caso conclude subito la funzione.
  switch (status) {
    // Il completamento del job ha un’etichetta diversa dal verdetto clean del motore antimalware.
    case 'completed':
      return 'Completata'
    case 'processing':
      return 'Elaborazione'
    case 'queued':
      return 'In coda'
    case 'failed':
      return 'Fallita'
    // Da questo ramo le etichette descrivono disponibilità di servizi anziché avanzamento dei job.
    case 'healthy':
      return 'Operativo'
    case 'degraded':
      return 'Degradato'
    case 'unavailable':
      return 'Non disponibile'
  }
}

// Traduce il livello di rischio senza cambiare il valore tecnico usato da API e filtri.
export function getRiskLabel(risk: RiskLevel) {
  // Converte ciascun livello di RiskLevel nell’etichetta mostrata nei badge, mantenendo separato il valore API.
  switch (risk) {
    case 'low':
      return 'Basso'
    case 'medium':
      return 'Medio'
    case 'high':
      return 'Alto'
    case 'critical':
      return 'Critico'
  }
}

// Converte il nome del ruolo in testo italiano senza assegnare permessi all’utente.
export function getRoleLabel(role: UserRole) {
  // La traduzione del ruolo produce solo testo e non modifica i permessi del context.
  switch (role) {
    case 'user':
      return 'Utente'
    case 'analyst':
      return 'Analista'
    case 'admin':
      return 'Amministratore'
  }
}

// Converte gli stati account previsti dal tipo in etichette italiane.
export function getUserStatusLabel(status: 'active' | 'invited' | 'suspended') {
  // Seleziona la traduzione del valore ricevuto; il return di ogni caso conclude subito la funzione.
  switch (status) {
    case 'active':
      return 'Attivo'
    case 'invited':
      return 'Invitato'
    case 'suspended':
      return 'Sospeso'
  }
}

// Associa le severità degli indicatori alle etichette brevi della UI.
export function getSeverityLabel(severity: 'info' | 'warning' | 'critical') {
  // Converte il livello dell’indicatore in un testo breve per presentare la sua importanza.
  switch (severity) {
    case 'info':
      return 'Informativo'
    case 'warning':
      return 'Attenzione'
    case 'critical':
      return 'Critico'
  }
}
