/**
 * Stati visuali riusabili per caricamento, errore e dataset vuoti.
 *
 * Non rappresentano una singola pagina: vengono composti da molte viste del
 * frontend per gestire in modo uniforme gli stati transitori.
 */
import ErrorOutlineRoundedIcon from '@mui/icons-material/ErrorOutlineRounded'
import HourglassEmptyRoundedIcon from '@mui/icons-material/HourglassEmptyRounded'
import InboxRoundedIcon from '@mui/icons-material/InboxRounded'
// MUI fornisce pannelli di errore, indicatori di attesa e contenitori per gli stati senza dati.
import { Alert, Box, Button, CircularProgress, Stack, Typography } from '@mui/material'
import type { ReactNode } from 'react'

// Le props forniscono testi e un eventuale contenuto React per l’azione, senza imporre una richiesta HTTP.
interface StatePanelProps {
  title: string
  description: string
  // Il contenuto dell’azione è opzionale: la pagina può passare un pulsante o lasciare lo stato solo informativo.
  action?: ReactNode
}

// Il componente mostra una lista vuota o dati assenti e lascia alla pagina la scelta dell’eventuale azione.
export function EmptyState({ title, description, action }: StatePanelProps) {
  // Compone la vista dalle props senza mantenere stato locale o effettuare richieste HTTP.
  return (
    <Stack
      spacing={2}
      sx={{ py: 7, px: 3, textAlign: 'center', alignItems: 'center', justifyContent: 'center' }}
    >
      <Box
        sx={{
          width: 72,
          height: 72,
          display: 'grid',
          placeItems: 'center',
          borderRadius: '50%',
          bgcolor: 'rgba(15, 108, 120, 0.08)',
          color: 'primary.main',
        }}
      >
        {/* L’icona identifica lo stato vuoto, mentre titolo e descrizione spiegano il contesto specifico della pagina. */}
        <InboxRoundedIcon fontSize="large" />
      </Box>
      <Box>
        <Typography variant="h5" gutterBottom>
          {title}
        </Typography>
        <Typography color="text.secondary">{description}</Typography>
      </Box>
      {/* Visualizza l’eventuale azione ricevuta, ad esempio un pulsante per riprovare o avviare un’analisi. */}
      {action}
    </Stack>
  )
}

// Omit riusa il contratto escludendo action; CircularProgress indica attesa senza una percentuale misurata.
export function LoadingState({ title, description }: Omit<StatePanelProps, 'action'>) {
  // Compone la vista dalle props senza mantenere stato locale o effettuare richieste HTTP.
  return (
    <Stack spacing={2} sx={{ py: 8, alignItems: 'center', justifyContent: 'center' }}>
      {/* L’indicatore segnala un’attività pendente; non misura i byte caricati o la percentuale della scansione. */}
      <CircularProgress />
      <Box sx={{ textAlign: 'center' }}>
        <Typography variant="h6">{title}</Typography>
        <Typography color="text.secondary">{description}</Typography>
      </Box>
      <HourglassEmptyRoundedIcon sx={{ color: 'text.disabled' }} />
    </Stack>
  )
}

// L’intersezione aggiunge etichetta e callback di retry opzionali: il pulsante delega il nuovo tentativo alla pagina.
export function ErrorState({
  title,
  description,
  actionLabel,
  onRetry,
}: StatePanelProps & { actionLabel?: string; onRetry?: () => void }) {
  // Compone la vista dalle props senza mantenere stato locale o effettuare richieste HTTP.
  return (
    <Alert
      severity="error"
      icon={<ErrorOutlineRoundedIcon />}
      sx={{ borderRadius: 4, alignItems: 'center' }}
      action={
        // Il pulsante di retry viene costruito solo quando sono presenti sia l’etichetta sia la callback.
        actionLabel && onRetry ? (
          <Button color="inherit" size="small" onClick={onRetry}>
            {actionLabel}
          </Button>
        ) : undefined
      }
    >
      {/* Il titolo e la descrizione spiegano l’errore; l’azione resta affidata alla callback della pagina. */}
      <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>
        {title}
      </Typography>
      <Typography variant="body2">{description}</Typography>
    </Alert>
  )
}
