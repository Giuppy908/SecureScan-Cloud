/**
 * Card base per le sezioni informative del frontend.
 *
 * Riduce duplicazioni strutturali tra pagine diverse e rende più immediato
 * riconoscere i blocchi logici dell'interfaccia.
 */
// Card e CardContent forniscono la superficie della sezione; Stack e Typography ne organizzano l’intestazione.
import { Card, CardContent, Stack, Typography } from '@mui/material'
import type { ReactNode } from 'react'

// Le props richiedono titolo e children e ammettono sottotitolo e azione opzionali.
interface SectionCardProps {
  title: string
  subtitle?: string
  // La pagina può fornire un’azione, come il collegamento alla cronologia, senza imporla a tutte le card.
  action?: ReactNode
  // Il contenuto obbligatorio può essere una tabella, un form, una lista o altri componenti React.
  children: ReactNode
}

// Il componente funzionale destruttura le props e racchiude il contenuto in Card e CardContent di MUI.
export function SectionCard({ title, subtitle, action, children }: SectionCardProps) {
  // Restituisce una card a tutta altezza con padding interno, titolo e contenuto separati.
  return (
    <Card sx={{ height: '100%', borderRadius: 3 }}>
      {/* CardContent applica lo spazio interno comune alle sezioni delle diverse pagine. */}
      <CardContent sx={{ p: 3 }}>
        <Stack
          direction={{ xs: 'column', sm: 'row' }}
          spacing={1.5}
          sx={{
            justifyContent: 'space-between',
            alignItems: { xs: 'flex-start', sm: 'center' },
            mb: 2.5,
          }}
        >
          <div>
            <Typography variant="h6">{title}</Typography>
            {/* Omette il sottotitolo quando la prop non è valorizzata, evitando un testo vuoto aggiuntivo. */}
            {subtitle ? (
              <Typography variant="body2" color="text.secondary">
                {subtitle}
              </Typography>
            ) : null}
          </div>
          {/* Inserisce l’azione opzionale fornita dalla pagina accanto al gruppo del titolo. */}
          {action}
        </Stack>
        {/* Lo slot children mostra il contenuto specifico della pagina dentro la card riutilizzabile. */}
        {children}
      </CardContent>
    </Card>
  )
}
