/**
 * Tipi TypeScript condivisi dal frontend.
 *
 * Questi modelli descrivono i dati che la GUI riceve dall'Analysis API e le
 * strutture che i componenti usano internamente per renderli. La distinzione è
 * importante: i dati reali arrivano in buona parte in snake_case dal backend,
 * mentre il frontend li organizza in tipi leggibili per pagine e componenti.
 */
// Questo tipo generale comprende anche user; i controlli auth usano invece AuthRole con analyst e admin.
export type UserRole = 'user' | 'analyst' | 'admin'

// La union elenca i livelli di rischio ammessi dal contratto API, separati dallo stato di avanzamento.
export type RiskLevel = 'low' | 'medium' | 'high' | 'critical'
// Il verdetto distingue pulito, sospetto, malevolo ed errore di scansione; clean non è una garanzia assoluta sul file.
export type AnalysisVerdict = 'clean' | 'suspicious' | 'malicious' | 'scan_error'
// Distingue nessuna minaccia, rilevazione, errore, timeout e motore non disponibile.
export type ClamAvStatus = 'clean' | 'found' | 'error' | 'timeout' | 'unavailable'
// Distingue nessuna corrispondenza, regole corrispondenti ed errori o indisponibilità del motore.
export type YaraStatus = 'clean' | 'matched' | 'error' | 'unavailable'

// queued indica attesa, processing elaborazione, completed conclusione e failed fallimento del job.
export type AnalysisStatus = 'queued' | 'processing' | 'completed' | 'failed'

// Descrive la disponibilità di un servizio, distinta dallo stato di elaborazione di un job.
export type ServiceStatus = 'healthy' | 'degraded' | 'unavailable'

// La severità classifica gli indicatori informativi o critici e non coincide con RiskLevel del file.
export type IndicatorSeverity = 'info' | 'warning' | 'critical'

// Descrive una vista sintetica di nome, ruolo e team; il context auth adotta il proprio contratto AuthUser.
export interface CurrentUser {
  name: string
  role: UserRole
  team: string
}

// Un evento temporale combina etichetta, istante e nota per una rappresentazione cronologica.
export interface AnalysisTimelineEvent {
  label: string
  timestamp: string
  note: string
}

// Associa a un indicatore strutturato una severità e una descrizione leggibile.
export interface AnalysisIndicator {
  label: string
  severity: IndicatorSeverity
  description: string
}

// Modello con nomi camelCase e valori di presentazione, distinto dal record JSON AnalysisApiRecord.
export interface AnalysisRecord {
  id: string
  fileName: string
  submittedAt: string
  submittedBy: string
  // Lo stato tecnico serve anche alle pagine per decidere se continuare le letture di polling.
  status: AnalysisStatus
  risk: RiskLevel
  sha256: string
  mimeType: string
  sizeLabel: string
  entropy: number
  extensionMatchesContent: boolean
  summary: string
  indicators: AnalysisIndicator[]
  timeline: AnalysisTimelineEvent[]
}

// L’interfaccia descrive il record JSON: i campi nullable possono non essere disponibili durante la lavorazione.
export interface AnalysisApiRecord {
  id: string
  file_name: string
  // Identificativo del proprietario del job, che può essere assente nel record ricevuto.
  owner_sub: string | null
  // Nome del proprietario mostrabile nella UI senza ricavarlo dall’identificativo tecnico.
  owner_username: string | null
  // Lo stato tecnico serve anche alle pagine per decidere se continuare le letture di polling.
  status: AnalysisStatus
  // Il rischio è un valore di dominio ricevuto dal backend, separato dal verdetto finale.
  risk_level: RiskLevel
  // Data di creazione del job rappresentata come testo dalla API e formattata solo nella UI.
  created_at: string
  // Ultimo aggiornamento del record: non rappresenta una lista completa degli eventi della scansione.
  updated_at: string
  // Dimensione numerica usata dai formatter per produrre un’etichetta in byte, KB o MB.
  size_bytes: number
  // Il MIME inferito può essere assente finché la lavorazione non ha prodotto i metadati.
  mime_type: string | null
  // Hash ricevuto dal backend; null mantiene distinta l’assenza del risultato da una stringa di hash.
  sha256: string | null
  // Valore strutturale numerico che il formatter arrotonda per la visualizzazione.
  entropy: number | null
  // true indica corrispondenza, false disallineamento e null informazione non disponibile.
  extension_matches_mime: boolean | null
  // Il verdetto antimalware può restare null e non viene ricavato automaticamente dallo stato del job.
  verdict: AnalysisVerdict | null
  // Istante della scansione, separato dalle date di creazione e aggiornamento del record.
  scanned_at: string | null
  clamav_status: ClamAvStatus | null
  // Nome opzionale della firma rilevata dal motore ClamAV.
  clamav_signature_name: string | null
  clamav_error: string | null
  yara_status: YaraStatus | null
  // Ogni elemento descrive una regola YARA corrispondente con metadati e tag.
  yara_matches: Array<{
    rule_name: string
    namespace: string | null
    description: string | null
    severity: string | null
    category: string | null
    author: string | null
    reference: string | null
    // Lista delle etichette associate alla regola YARA, distinta dal nome identificativo della regola.
    tags: string[]
  }>
  yara_error: string | null
  // Il record API contiene messaggi testuali, tradotti quando riconosciuti dalla pagina di dettaglio.
  indicators: string[]
  // Testo dell’errore del job o della scansione da presentare nelle viste di risultato.
  error_message: string | null
}

// Il contenitore paginato unisce i record alla numerazione e ai totali calcolati dal backend.
export interface AnalysisApiPage {
  // Questi sono soltanto i record della pagina richiesta, non l’intera cronologia.
  items: AnalysisApiRecord[]
  total: number
  page: number
  page_size: number
  // Il totale delle pagine consente alla UI di disabilitare Avanti o riallineare una pagina non più disponibile.
  total_pages: number
}

// Descrive la risposta pubblica di health con nome del servizio, versione e identificativo dell’istanza.
export interface AnalysisHealth {
  status: string
  service: string
  version: string
  instance_id: string
}

// Raccoglie conteggi aggregati delle analisi per stato, usati dalle card di riepilogo.
export interface DashboardSummary {
  total_analyses: number
  completed: number
  processing: number
  queued: number
  failed: number
}

// Associa un livello di rischio al suo conteggio per costruire barre e percentuali nella UI.
export interface DashboardRiskDistributionEntry {
  // Il rischio è un valore di dominio ricevuto dal backend, separato dal verdetto finale.
  risk_level: RiskLevel
  count: number
}

// Associa una data di aggregazione al numero di analisi, senza includere i singoli record.
export interface DashboardAnalysesOverTimeEntry {
  bucket_date: string
  count: number
}

// Raggruppa riepilogo, distribuzione del rischio, ultime analisi e conteggi per data per la Dashboard.
export interface DashboardSnapshot {
  summary: DashboardSummary
  risk_distribution: DashboardRiskDistributionEntry[]
  recent_analyses: AnalysisApiRecord[]
  analyses_over_time: DashboardAnalysesOverTimeEntry[]
}

// Conteggi personali del profilo: unisce queued e processing nel lavoro ancora pendente.
export interface ProfileStatistics {
  total_analyses: number
  completed: number
  queued_or_processing: number
  failed: number
}

// Lo snapshot distingue email attuale e modifica pendente e contiene avatar, ruoli e statistiche personali.
export interface UserProfileSnapshot {
  subject: string
  username: string
  first_name: string | null
  last_name: string | null
  email: string | null
  email_verified: boolean
  // L’indirizzo in attesa di verifica resta separato da email, che rappresenta quello attuale.
  pending_email: string | null
  // Segnala alla UI una modifica email non ancora conclusa.
  email_change_pending: boolean
  // Permette alle pagine di decidere se proporre lo stato e l’azione di verifica.
  email_verification_available: boolean
  roles: Array<'analyst' | 'admin'>
  // Percorso remoto da scaricare tramite client autenticato; non è necessariamente l’URL blob visualizzato.
  avatar_url: string | null
  statistics: ProfileStatistics
}

// Il generico Record ammette dettagli eterogenei: la pagina ne controlla il tipo prima di visualizzarli.
export interface SystemStatusServiceSnapshot {
  name: string
  status: ServiceStatus
  message: string
  last_checked_at: string
  // Le chiavi dei dettagli sono dinamiche e i valori possono avere più tipi: la UI usa typeof e Array.isArray.
  details: Record<string, string | number | boolean | null | string[]>
}

// Combina stato complessivo, istante dello snapshot e dettagli dei servizi in un’unica risposta.
export interface SystemStatusSnapshot {
  overall_status: ServiceStatus
  checked_at: string
  services: SystemStatusServiceSnapshot[]
}

// Descrive una struttura con repliche e note operative, distinta dallo snapshot API effettivo dei servizi.
export interface SystemService {
  name: string
  status: ServiceStatus
  replicas: number
  region: string
  lastFault: string
  lastRecovery: string
  note: string
}

// I campi opzionali possono mancare; le pagine amministrative usano fallback quando costruiscono la vista.
export interface AdminUser {
  id?: string
  name?: string
  subject?: string
  username?: string
  first_name?: string | null
  last_name?: string | null
  email?: string | null
  email_verified?: boolean
  pending_email?: string | null
  email_change_pending?: boolean
  email_verification_available?: boolean
  // L’abilitazione dell’account è facoltativa nel tipo e viene usata dalle azioni e dai badge amministrativi.
  enabled?: boolean
  roles?: Array<'analyst' | 'admin'>
  // Il conteggio opzionale evita di dover ricavare il numero di analisi dalla lista di dettaglio.
  analysis_count?: number
  // L’elenco amministrativo può fornire un riferimento immagine distinto dall’avatar_url del proprio profilo.
  avatar_data_url?: string | null
  created_at?: string | null
  role?: UserRole
  status?: 'active' | 'invited' | 'suspended'
  lastAccess?: string
}

// Associa un account alle sue statistiche, distribuzione del rischio e analisi per il dettaglio admin.
export interface AdminUserAnalysesSnapshot {
  user: AdminUser
  statistics: ProfileStatistics
  risk_distribution: DashboardRiskDistributionEntry[]
  analyses: AnalysisApiRecord[]
}

// Descrive un evento amministrativo con attore, istante, severità e testo.
export interface AdminEvent {
  id: string
  title: string
  type: string
  actor: string
  occurredAt: string
  severity: IndicatorSeverity
  description: string
}

// Descrive campi di presentazione di una regola di limite; questo tipo non applica rate limiting nel browser.
export interface RateLimitRule {
  scope: string
  limit: string
  burst: string
  action: string
}
