/**
 * Definizione del contesto di autenticazione condiviso da tutto il frontend.
 *
 * Questo file non mostra direttamente una pagina, ma descrive i dati che
 * componenti e pagine possono leggere dopo il login: utente corrente, ruoli,
 * stato della sessione e funzioni per sincronizzare profilo e avatar.
 *
 * Dashboard, Cronologia, Profilo, Amministrazione e il layout laterale
 * dipendono tutti da questo contratto.
 */
// createContext definisce il canale condiviso; AuthProvider ne produce il valore e useAuth lo legge.
import { createContext } from 'react'

// La union ammette soltanto i due ruoli riconosciuti dai controlli della UI.
export type AuthRole = 'analyst' | 'admin'

// L’interfaccia descrive l’identità nel browser; i campi con null rappresentano informazioni assenti.
export interface AuthUser {
  // Nome di accesso mostrato nella shell e nel profilo; non coincide necessariamente con il subject.
  username: string
  // Nome leggibile usato nell’accoglienza e come fallback dell’identità visualizzata.
  displayName: string
  firstName: string | null
  lastName: string | null
  email: string | null
  // Stato della verifica email mostrato dalla UI, distinto dalla sola presenza di un indirizzo.
  emailVerified: boolean
  // Identificativo dell’utente usato per distinguere sessioni e avatar di account diversi.
  subject: string
  // Lista normalizzata che consente alla UI di distinguere analista e amministratore.
  roles: AuthRole[]
  // Contiene anche URL blob temporanei nonostante il nome del campo; null indica assenza dell’anteprima.
  avatarDataUrl: string | null
}

// Il contratto del context espone stato e callback; Promise<void> indica operazioni asincrone senza risultato utile.
export interface AuthContextValue {
  // Segnala il completamento del bootstrap auth e permette al provider di mostrare prima l’attesa.
  isReady: boolean
  // Descrive la presenza dell’identità nel context, separata dai permessi per le singole sezioni.
  isAuthenticated: boolean
  isAdmin: boolean
  isAnalyst: boolean
  // Indica almeno un ruolo supportato, usato per menu e azioni della pagina non autorizzata.
  hasRecognizedRole: boolean
  // Il consumer deve gestire null quando non è disponibile un’identità autenticata.
  user: AuthUser | null
  // La funzione asincrona consente a menu e pagine di avviare il logout tramite il provider.
  logoutUser: () => Promise<void>
  // Aggiorna i dati condivisi dopo una lettura o modifica del profilo, senza eseguire direttamente una richiesta.
  applyProfileSnapshot: (payload: {
    username: string
    first_name: string | null
    last_name: string | null
    email: string | null
    email_verified: boolean
    // Il contratto ammette informazioni opzionali sulla modifica email, separate dall’indirizzo attualmente attivo.
    pending_email?: string | null
    email_change_pending?: boolean
    avatar_url: string | null
  }) => void
  // Permette di cambiare o azzerare l’anteprima condivisa e gestirne la sostituzione nel provider.
  applyAvatarPreviewUrl: (payload: string | null) => void
  // Espone il caricamento asincrono di profilo e avatar quando occorre risincronizzare l’identità.
  refreshAuthenticatedProfile: () => Promise<void>
}

// Il valore iniziale null permette a useAuth di rilevare l’assenza del provider.
export const AuthContext = createContext<AuthContextValue | null>(null)
