/**
 * Pagina 404 interna del frontend demo.
 *
 * Gestisce URL React non riconosciuti mantenendo l'utente dentro la shell
 * applicativa e offrendo un ritorno rapido alla Dashboard.
 */
// Stack dispone il contenuto verticalmente e Button riutilizza l'aspetto dei pulsanti Material UI.
import { Button, Stack } from '@mui/material'
import { Link as RouterLink } from 'react-router'
import { EmptyState } from '../components/StatePanels'

// Il componente funzionale mostra l’errore della route jolly; RouterLink torna alla Dashboard senza ricaricare il documento.
export function NotFoundPage() {
  // La pagina non carica dati: il contenuto dipende soltanto dalla route non riconosciuta.
  return (
    <Stack spacing={3}>
      {/* Riutilizza il pannello vuoto passando titolo, descrizione e un elemento React nella prop action. */}
      <EmptyState
        title="Pagina non disponibile"
        description="La rotta richiesta non esiste ancora nella demo frontend di SecureScan Cloud."
        action={
          <Button component={RouterLink} to="/" variant="contained">
            Torna alla dashboard
          </Button>
        }
      />
    </Stack>
  )
}
