/**
 * Vista mostrata quando il ruolo disponibile non basta per una sezione.
 *
 * Viene usata dal routing frontend per evitare una navigazione incoerente verso
 * aree come Amministrazione. Non sostituisce in alcun modo i controlli
 * server-side applicati dal backend.
 */
import LockRoundedIcon from '@mui/icons-material/LockRounded'
import { Box, Button, Stack, Typography } from '@mui/material'
import { Link as RouterLink } from 'react-router'
import { useAuth } from '../auth/useAuth'
import { SectionCard } from '../components/SectionCard'

// Questa vista spiega il rifiuto del controllo client senza richiedere dati alle API.
export function UnauthorizedPage() {
  // Il custom hook legge dal context ruolo riconosciuto e logout per adattare testo e azioni della vista.
  const { hasRecognizedRole, logoutUser } = useAuth()

  return (
    <Stack spacing={3} sx={{ py: 3 }}>
      <SectionCard title="Accesso non autorizzato" subtitle="Il tuo account non ha i permessi richiesti per questa sezione.">
        <Stack spacing={2.5} sx={{ alignItems: 'center', py: 3, textAlign: 'center' }}>
          {/* Box disegna il contenitore circolare dell'icona usando le proprietà di stile sx. */}
          <Box
            sx={{
              width: 72,
              height: 72,
              borderRadius: '50%',
              display: 'grid',
              placeItems: 'center',
              bgcolor: 'rgba(15, 108, 120, 0.08)',
              color: 'primary.main',
            }}
          >
            <LockRoundedIcon fontSize="large" />
          </Box>
          <Typography variant="h5">Permessi non sufficienti</Typography>
          {/* Distingue un ruolo insufficiente per questa sezione dall'assenza di un ruolo riconosciuto. */}
          <Typography color="text.secondary" sx={{ maxWidth: 560 }}>
            {hasRecognizedRole
              ? 'La sessione è valida, ma questo profilo non può accedere alla risorsa richiesta.'
              : 'La sessione è valida, ma il profilo non espone un ruolo SecureScan Cloud riconosciuto.'}
          </Typography>
          {/* I pulsanti sono impilati sui piccoli schermi e affiancati da sm in poi. */}
          <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5}>
            {/* Il rendering condizionale offre il ritorno alla Dashboard solo quando è presente un ruolo SecureScan riconosciuto. */}
            {hasRecognizedRole ? (
              <Button component={RouterLink} to="/" variant="contained">
                Torna alla dashboard
              </Button>
            ) : null}
            {/* Il logout permette di uscire dalla sessione anche quando non è disponibile il collegamento alla dashboard. */}
            <Button
              variant={hasRecognizedRole ? 'outlined' : 'contained'}
              onClick={() => {
                // Avvia il logout asincrono dal contesto; void indica che questa callback non ne attende il risultato.
                void logoutUser()
              }}
            >
              Esci
            </Button>
          </Stack>
        </Stack>
      </SectionCard>
    </Stack>
  )
}
