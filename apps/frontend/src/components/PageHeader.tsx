/**
 * Intestazione riutilizzabile per le principali pagine di SecureScan Cloud.
 *
 * Dashboard, Cronologia, Nuova analisi, Profilo, Stato del sistema e area
 * amministrativa condividono tutti questa struttura: titolo, descrizione,
 * eventuale azione contestuale e piccolo highlight.
 */
// MUI fornisce contenitori, testo e badge che compongono la stessa intestazione per pagine diverse.
import { Box, Chip, Stack, Typography } from '@mui/material'
import type { SxProps, Theme } from '@mui/material/styles'
import type { ReactNode } from 'react'

// Le props sono il contratto del componente; ? indica opzioni facoltative e ReactNode ammette contenuto React.
interface PageHeaderProps {
  // Testo introduttivo facoltativo sopra il titolo, omesso quando la pagina non lo specifica.
  eyebrow?: string
  // Titolo obbligatorio della pagina, usato sia nel contenuto sia nell’attributo title del testo.
  title: string
  description: string
  // Permette alla pagina di passare uno o più pulsanti già costruiti come contenuto React.
  action?: ReactNode
  // Testo opzionale del badge, usato per conteggi, identificativi o indicazioni di aggiornamento.
  highlight?: string
  // Accetta stili MUI compatibili con il tema per adattare il titolo alle esigenze della pagina.
  titleSx?: SxProps<Theme>
}

// Il destructuring estrae le props; SxProps<Theme> tipizza gli stili opzionali applicati al titolo.
export function PageHeader({
  eyebrow,
  title,
  description,
  action,
  highlight,
  titleSx,
}: PageHeaderProps) {
  // Stack dispone titolo e azione in colonna o riga secondo il breakpoint; sx contiene le regole di presentazione.
  return (
    <Stack
      direction={{ xs: 'column', lg: 'row' }}
      spacing={2.5}
      sx={{
        // Quando gli elementi sono in riga distribuisce lo spazio fra il testo e l’azione.
        justifyContent: 'space-between',
        alignItems: { xs: 'flex-start', lg: 'center' },
        minWidth: 0,
      }}
    >
      <Box sx={{ minWidth: 0, flex: 1, maxWidth: '100%' }}>
        {/* Il rendering condizionale omette il sottotitolo introduttivo quando la prop non è valorizzata. */}
        {eyebrow ? (
          <Typography variant="overline" color="primary.main" sx={{ fontWeight: 700 }}>
            {eyebrow}
          </Typography>
        ) : null}
        <Stack
          direction="row"
          spacing={1.2}
          sx={{ alignItems: 'center', flexWrap: 'wrap', minWidth: 0, maxWidth: '100%' }}
        >
          <Typography
            variant="h1"
            title={title}
            sx={{
              minWidth: 0,
              maxWidth: '100%',
              // Permette al titolo lungo, ad esempio un nome file, di andare a capo senza uscire dal contenitore.
              overflowWrap: 'anywhere',
              wordBreak: 'break-word',
              whiteSpace: 'normal',
              // Lo spread applica per ultimi gli stili forniti dalla pagina, che possono sovrascrivere quelli precedenti.
              ...titleSx,
            }}
          >
            {title}
          </Typography>
          {/* Il badge compare soltanto se la pagina ha fornito un testo di evidenza. */}
          {highlight ? (
            <Chip
              label={highlight}
              color="primary"
              variant="outlined"
              sx={{ bgcolor: 'rgba(15, 108, 120, 0.08)', height: 30, maxWidth: '100%' }}
            />
          ) : null}
        </Stack>
        {/* La descrizione usa il colore secondario del tema per restare distinta dal titolo. */}
        <Typography color="text.secondary" sx={{ maxWidth: 760, minWidth: 0 }}>
          {description}
        </Typography>
      </Box>
      {/* Se l’azione è assente non crea il suo contenitore; altrimenti mostra il contenuto passato dalla pagina. */}
      {action ? <Box sx={{ flexShrink: 0, maxWidth: '100%' }}>{action}</Box> : null}
    </Stack>
  )
}
