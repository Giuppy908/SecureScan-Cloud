/**
 * Hook di comodità per leggere il contesto di autenticazione.
 *
 * Le pagine non importano direttamente `AuthContext`: usano questo hook per
 * recuperare utente, ruoli e funzioni di logout in modo uniforme.
 */
import { useContext } from 'react'
// Importa il canale condiviso, mentre il suo valore concreto viene impostato da AuthProvider.
import { AuthContext } from './authContext'

export function useAuth() {
  // useContext legge il valore del provider più vicino e aggiorna il componente quando quel valore cambia.
  const context = useContext(AuthContext)
  // Rileva un consumer montato senza provider e interrompe il rendering con un errore di uso del context.
  if (context === null) {
    throw new Error('useAuth must be used within AuthProvider.')
  }

  // Consegna stato e callback al componente chiamante, senza avviare un login o una fetch autonomamente.
  return context
}
