/**
 * Guardia frontend dedicata alle viste amministrative.
 *
 * Viene usata per la pagina "Amministrazione" e per il dettaglio utente
 * amministrativo. Anche qui il vero controllo di autorizzazione resta
 * server-side: il frontend evita solo di mostrare una schermata non coerente
 * con il ruolo disponibile nel token.
 */
// La prop children può contenere un componente o altri nodi React della sezione amministrativa.
import type { ReactNode } from 'react'
import { UnauthorizedPage } from '../pages/UnauthorizedPage'
import { useAuth } from './useAuth'

// La prop children è il contenuto React da mostrare solo quando il contesto indica un amministratore.
export function RoleRoute({ children }: { children: ReactNode }) {
  // Legge sia la presenza dell’utente sia il flag admin; un utente autenticato può non essere amministratore.
  const { isAuthenticated, isAdmin } = useAuth()

  // Questo controllo RBAC riguarda la UI: le richieste HTTP richiedono comunque autorizzazione sul server.
  if (!isAuthenticated || !isAdmin) {
    // Esclude il contenuto amministrativo dal rendering e mostra la vista di accesso negato nello stesso percorso.
    return <UnauthorizedPage />
  }

  // Solo dopo il controllo restituisce i figli; il Fragment non modifica il layout con un nuovo nodo HTML.
  return <>{children}</>
}
