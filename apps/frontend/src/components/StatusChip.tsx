/**
 * Badge riutilizzabile per stati di analisi e di servizio.
 *
 * Permette di usare una sola grammatica visiva sia per gli stati dei job
 * mostrati in Cronologia/Dettaglio, sia per gli stati infrastrutturali
 * mostrati in Dashboard e Stato del sistema.
 */
import CheckCircleRoundedIcon from '@mui/icons-material/CheckCircleRounded'
import AutorenewRoundedIcon from '@mui/icons-material/AutorenewRounded'
import ErrorRoundedIcon from '@mui/icons-material/ErrorRounded'
import ScheduleRoundedIcon from '@mui/icons-material/ScheduleRounded'
import WarningAmberRoundedIcon from '@mui/icons-material/WarningAmberRounded'
import { Chip } from '@mui/material'
// Il badge accetta stati delle analisi e dei servizi; il tipo union impedisce altri valori durante la compilazione.
import type { AnalysisStatus, ServiceStatus } from '../types/domain'
import { getStatusLabel } from '../utils/labels'

// La union riunisce stati dei job e disponibilità dei servizi ammessi dalla prop status.
type StatusVariant = AnalysisStatus | ServiceStatus

// Record associa a ogni stato una configurazione completa con etichetta italiana, colore e icona.
const statusConfig: Record<
  StatusVariant,
  {
    label: string
    color: 'success' | 'warning' | 'error' | 'info' | 'default'
    icon: typeof CheckCircleRoundedIcon
    sx?: Record<string, string | number>
  }
> = {
  // Il job concluso usa il segno di conferma; un eventuale scan_error viene convertito dalla pagina prima di passare la prop.
  completed: {
    label: getStatusLabel('completed'),
    color: 'success',
    icon: CheckCircleRoundedIcon,
    sx: {
      bgcolor: '#27845d',
      color: '#ffffff',
    },
  },
  // Il job in corso usa l’icona di aggiornamento e una colorazione distinta dalla coda.
  processing: {
    label: getStatusLabel('processing'),
    color: 'info',
    icon: AutorenewRoundedIcon,
    sx: {
      bgcolor: '#1f6fb2',
      color: '#ffffff',
    },
  },
  // La coda è rappresentata con un’icona di attesa e uno stile neutro.
  queued: {
    label: getStatusLabel('queued'),
    color: 'default',
    icon: ScheduleRoundedIcon,
    sx: {
      bgcolor: '#b1b8c0',
      color: '#ffffff',
    },
  },
  // Il job fallito usa un’icona di errore e una colorazione dedicata.
  failed: {
    label: getStatusLabel('failed'),
    color: 'error',
    icon: ErrorRoundedIcon,
    sx: {
      bgcolor: '#b63d3d',
      color: '#ffffff',
    },
  },
  // Il servizio operativo riusa la semantica success del tema MUI.
  healthy: {
    label: getStatusLabel('healthy'),
    color: 'success',
    icon: CheckCircleRoundedIcon,
  },
  // La disponibilità degradata viene distinta sia dal servizio operativo sia da quello non disponibile.
  degraded: {
    label: getStatusLabel('degraded'),
    color: 'warning',
    icon: WarningAmberRoundedIcon,
    sx: {
      bgcolor: '#c7a300',
      color: '#ffffff',
    },
  },
  // Un servizio non disponibile usa la semantica di errore del tema.
  unavailable: {
    label: getStatusLabel('unavailable'),
    color: 'error',
    icon: ErrorRoundedIcon,
  },
}

// Il componente funzionale riceve status come prop e mostra il corrispondente badge MUI.
export function StatusChip({ status }: { status: StatusVariant }) {
  // Seleziona testo, icona e colori dalla configurazione corrispondente alla prop della pagina.
  const config = statusConfig[status]

  // Restituisce un Chip MUI filled usando una larghezza minima comune, così gli stati restano allineati nelle liste.
  return (
    <Chip
      size="small"
      color={config.color}
      variant="filled"
      icon={<config.icon />}
      label={config.label}
      sx={{
        minWidth: 120,
        justifyContent: 'center',
        // Allinea l’etichetta all’interno del badge indipendentemente dalla sua lunghezza.
        '& .MuiChip-label': {
          width: '100%',
          textAlign: 'center',
          px: 1,
        },
        // Fa ereditare all’icona il colore del badge per mantenere leggibile la coppia testo/icona.
        '& .MuiChip-icon': {
          color: 'inherit',
          ml: 1,
        },
        // Lo spread sovrappone gli eventuali stili specifici alle regole comuni del badge.
        ...config.sx,
      }}
    />
  )
}
