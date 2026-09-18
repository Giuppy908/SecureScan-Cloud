/**
 * Tema MUI condiviso del frontend SecureScan Cloud.
 *
 * Qui sono concentrate le scelte visive che devono restare coerenti in tutte le
 * pagine: palette, tipografia, radius e personalizzazioni dei componenti base.
 */
import { alpha, createTheme } from '@mui/material/styles'

// Le larghezze sono condivise con AppShell per allineare sidebar, barra superiore e contenuto.
export const drawerWidth = 280
export const drawerCollapsedWidth = 96

// createTheme costruisce il tema letto dai componenti MUI attraverso ThemeProvider in App.
export const appTheme = createTheme({
  // La palette definisce colori semantici riutilizzabili con primary.main, background.paper e text.secondary.
  palette: {
    // Seleziona la modalità chiara del tema da cui MUI ricava i valori predefiniti dei componenti.
    mode: 'light',
    // Il colore principale identifica le azioni e le evidenze comuni dell’app.
    primary: {
      main: '#0f6c78',
      dark: '#0a424b',
      light: '#6cb7c4',
      contrastText: '#f8fbfc',
    },
    secondary: {
      main: '#1b3a57',
      dark: '#102739',
      light: '#7a99b7',
      contrastText: '#ffffff',
    },
    success: {
      main: '#27845d',
    },
    warning: {
      main: '#b7791f',
    },
    error: {
      main: '#b63d3d',
    },
    // Distingue lo sfondo generale dalla superficie dei contenitori come Paper e Card.
    background: {
      default: '#eef3f6',
      paper: '#fbfdfe',
    },
    // Distingue il testo principale da descrizioni e informazioni secondarie.
    text: {
      primary: '#12202f',
      secondary: '#576273',
    },
    divider: '#d7e0e6',
  },
  // Definisce il raggio base degli angoli, personalizzabile dai singoli componenti o tramite sx.
  shape: {
    borderRadius: 12,
  },
  // Centralizza font e varianti tipografiche di titoli e pulsanti.
  typography: {
    // Specifica una lista di font con fallback; questa dichiarazione non scarica da sola i file dei font.
    fontFamily: '"IBM Plex Sans", "Segoe UI", sans-serif',
    h1: {
      fontFamily: '"Space Grotesk", "IBM Plex Sans", sans-serif',
      fontSize: '2.6rem',
      fontWeight: 700,
      letterSpacing: '-0.04em',
    },
    h2: {
      fontFamily: '"Space Grotesk", "IBM Plex Sans", sans-serif',
      fontWeight: 700,
      letterSpacing: '-0.03em',
    },
    h3: {
      fontWeight: 700,
      letterSpacing: '-0.02em',
    },
    // Personalizza la tipografia dei pulsanti e conserva il testo senza trasformarlo in maiuscolo.
    button: {
      textTransform: 'none',
      fontWeight: 600,
    },
  },
  // defaultProps imposta le props predefinite; styleOverrides personalizza l’aspetto dei componenti MUI.
  components: {
    // Le regole globali vengono applicate quando App rende CssBaseline dentro ThemeProvider.
    MuiCssBaseline: {
      styleOverrides: {
        body: {
          background: '#eef3f6',
          margin: 0,
          minHeight: '100vh',
        },
        '#root': {
          minHeight: '100vh',
          margin: 0,
        },
      },
    },
    // Imposta superficie, bordo e ombra comuni ai componenti basati su Paper.
    MuiPaper: {
      styleOverrides: {
        root: {
          backgroundImage: 'none',
          border: '1px solid rgba(215, 224, 230, 0.9)',
          boxShadow: '0 20px 40px rgba(15, 35, 52, 0.06)',
          borderRadius: 12,
        },
      },
    },
    // Le card informative condividono sfondo e arrotondamento definiti in questo blocco.
    MuiCard: {
      styleOverrides: {
        root: {
          backgroundImage:
            'linear-gradient(180deg, rgba(251, 253, 254, 0.98), rgba(245, 249, 251, 0.98))',
          borderRadius: 12,
        },
      },
    },
    // Imposta proprietà predefinite e stile dei pulsanti, mantenendo una dimensione minima comune.
    MuiButton: {
      defaultProps: {
        // Disabilita l’elevazione predefinita; gli stili possono comunque assegnare ombre specifiche.
        disableElevation: true,
      },
      styleOverrides: {
        root: {
          borderRadius: 8,
          paddingInline: 20,
          minHeight: 44,
          // alpha ricava un colore con trasparenza per l’ombra dei pulsanti primari.
          '&.MuiButton-containedPrimary': {
            boxShadow: `0 14px 26px ${alpha('#0f6c78', 0.22)}`,
          },
        },
      },
    },
    // Rende i badge arrotondati con testo marcato; le singole configurazioni possono aggiungere colori.
    MuiChip: {
      styleOverrides: {
        root: {
          borderRadius: 999,
          fontWeight: 600,
        },
      },
    },
    // I campi di testo usano outlined come variante predefinita se la pagina non ne specifica un’altra.
    MuiTextField: {
      defaultProps: {
        variant: 'outlined',
      },
    },
    // Personalizza il bordo arrotondato della variante di input usata dai form.
    MuiOutlinedInput: {
      styleOverrides: {
        root: {
          borderRadius: 8,
        },
      },
    },
    // Distingue le intestazioni delle tabelle dalle celle dei dati con peso e colore del testo.
    MuiTableCell: {
      styleOverrides: {
        head: {
          fontWeight: 700,
          color: '#32475a',
        },
      },
    },
  },
})
