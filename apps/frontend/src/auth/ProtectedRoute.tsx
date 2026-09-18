/**
 * Guardia frontend per tutte le pagine accessibili almeno a un analyst.
 *
 * Se la sessione non esiste oppure il token non espone un ruolo SecureScan
 * Cloud riconosciuto, l'utente viene portato alla pagina "Accesso non
 * autorizzato". Questo protegge l'esperienza utente, ma la separazione reale
 * dei dati resta comunque applicata dal backend.
 */
// ReactNode ammette la pagina o altri contenuti React ricevuti nella prop children.
import type { ReactNode } from 'react'
import { UnauthorizedPage } from '../pages/UnauthorizedPage'
import { useAuth } from './useAuth'

// La prop children contiene la pagina protetta; il destructuring estrae il contenuto passato dal router.
export function ProtectedRoute({ children }: { children: ReactNode }) {
  // Legge separatamente esistenza della sessione e ruolo analyst dal context fornito da AuthProvider.
  const { isAuthenticated, isAnalyst } = useAuth()

  // Il rendering condizionale mostra UnauthorizedPage nello stesso URL, senza eseguire un redirect.
  if (!isAuthenticated || !isAnalyst) {
    // Il return anticipato impedisce il montaggio di children: la pagina protetta non avvia i propri effetti.
    return <UnauthorizedPage />
  }

  // Il Fragment restituisce la pagina autorizzata senza introdurre contenitori HTML aggiuntivi.
  return <>{children}</>
}
