/**
 * Badge visivo del livello di rischio restituito dal backend.
 *
 * Il frontend riceve valori tecnici (`low`, `medium`, `high`, `critical`) e li
 * converte qui in una rappresentazione grafica coerente, riusata soprattutto in
 * Dashboard, Cronologia e Dettaglio analisi.
 */
import PriorityHighRoundedIcon from '@mui/icons-material/PriorityHighRounded'
import ReportRoundedIcon from '@mui/icons-material/ReportRounded'
import ShieldRoundedIcon from '@mui/icons-material/ShieldRounded'
import WarningAmberRoundedIcon from '@mui/icons-material/WarningAmberRounded'
import { Chip } from '@mui/material'
// Il tipo limita il rischio ai valori del contratto API, così la configurazione può coprirli tutti.
import type { RiskLevel } from '../types/domain'
import { getRiskLabel } from '../utils/labels'

// Record richiede una configurazione per ciascun RiskLevel: il badge visualizza il rischio ricevuto, non lo calcola.
const riskConfig: Record<
  RiskLevel,
  {
    label: string
    color: 'success' | 'warning' | 'error'
    // La configurazione conserva un componente icona, non un elemento DOM già creato.
    icon: typeof ShieldRoundedIcon
    // Le personalizzazioni opzionali associano proprietà di stile a valori testuali o numerici.
    sx?: Record<string, string | number>
  }
> = {
  // Il rischio basso usa l’icona scudo e uno stile distinto dagli altri livelli.
  low: {
    label: getRiskLabel('low'),
    color: 'success',
    icon: ShieldRoundedIcon,
    sx: {
      bgcolor: 'rgba(39, 132, 93, 0.10)',
      color: '#1f6a4a',
      border: '1px solid rgba(39, 132, 93, 0.35)',
    },
  },
  // Il rischio medio associa l’etichetta tradotta a un’evidenza gialla.
  medium: {
    label: getRiskLabel('medium'),
    color: 'warning',
    icon: PriorityHighRoundedIcon,
    sx: {
      bgcolor: 'rgba(255, 247, 204, 0.95)',
      color: '#c7a300',
      border: '1px solid rgba(199, 163, 0, 0.38)',
    },
  },
  // Il rischio alto usa l’icona di avviso e un’evidenza arancione.
  high: {
    label: getRiskLabel('high'),
    color: 'error',
    icon: WarningAmberRoundedIcon,
    sx: {
      bgcolor: 'rgba(255, 239, 228, 0.95)',
      color: '#e46a1a',
      border: '1px solid rgba(228, 106, 26, 0.38)',
    },
  },
  // Il rischio critico usa il badge più marcato, mantenendo invariato il valore di dominio.
  critical: {
    label: getRiskLabel('critical'),
    color: 'error',
    icon: ReportRoundedIcon,
    sx: {
      bgcolor: 'rgba(252, 236, 236, 0.95)',
      color: '#8a1e1e',
      border: '1px solid rgba(138, 30, 30, 0.35)',
    },
  },
}

// La prop risk seleziona etichetta, icona e stile del componente MUI Chip.
export function RiskChip({ risk }: { risk: RiskLevel }) {
  // Legge la configurazione associata alla prop ricevuta; non modifica il record della scansione.
  const config = riskConfig[risk]

  // Il Chip riceve testo e icona dalla configurazione e applica gli stili comuni prima di quelli specifici.
  return (
    <Chip
      size="small"
      color={config.color}
      variant="outlined"
      icon={<config.icon />}
      label={config.label}
      sx={{
        minWidth: 90,
        justifyContent: 'center',
        // Il selettore sx allinea al centro l’etichetta interna del componente MUI.
        '& .MuiChip-label': {
          width: '100%',
          textAlign: 'center',
          px: 1,
        },
        // L’icona eredita il colore del badge invece di mantenere un colore autonomo.
        '& .MuiChip-icon': {
          color: 'inherit',
          ml: 1,
        },
        // Lo spread aggiunge le personalizzazioni del livello dopo le regole comuni del badge.
        ...config.sx,
      }}
    />
  )
}
