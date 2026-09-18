/**
 * Layout principale dell'applicazione autenticata.
 *
 * Questo file costruisce la cornice condivisa del frontend: sidebar, header con
 * titolo corrente, menu utente e area centrale in cui React monta la route
 * attiva tramite `<Outlet />`.
 *
 * Tutte le pagine protette passano da qui. La shell mostra navigazione diversa
 * tra analyst e admin leggendo il ruolo dal contesto di autenticazione, ma i
 * permessi reali restano verificati server-side dall'Analysis API.
 */
// Le icone sono componenti React usati per identificare visivamente le destinazioni del menu.
import AdminPanelSettingsRoundedIcon from '@mui/icons-material/AdminPanelSettingsRounded'
import DashboardRoundedIcon from '@mui/icons-material/DashboardRounded'
import HistoryRoundedIcon from '@mui/icons-material/HistoryRounded'
import MonitorHeartRoundedIcon from '@mui/icons-material/MonitorHeartRounded'
import PersonRoundedIcon from '@mui/icons-material/PersonRounded'
import LogoutRoundedIcon from '@mui/icons-material/LogoutRounded'
import SecurityRoundedIcon from '@mui/icons-material/SecurityRounded'
import UploadFileRoundedIcon from '@mui/icons-material/UploadFileRounded'
import {
  AppBar,
  Avatar,
  Box,
  ButtonBase,
  Divider,
  Drawer,
  List,
  ListItemButton,
  ListItemIcon,
  ListItemText,
  Menu,
  MenuItem,
  Stack,
  Toolbar,
  Tooltip,
  Typography,
} from '@mui/material'
// Lo stato locale governa soltanto sidebar e menu; identità e logout provengono dal context auth.
import { useState } from 'react'
// NavLink crea link interni, useLocation legge il percorso e Outlet ospita la pagina selezionata.
import { NavLink, Outlet, useLocation } from 'react-router'
import { useAuth } from '../auth/useAuth'
import { drawerCollapsedWidth, drawerWidth } from '../theme/appTheme'

// L’interfaccia descrive le voci di navigazione: etichetta, componente icona e destinazione.
interface NavItem {
  label: string
  icon: typeof DashboardRoundedIcon
  to: string
}

// Le voci comuni portano a dashboard, upload, cronologia e stato del sistema.
const navigationItems: NavItem[] = [
  { label: 'Dashboard', icon: DashboardRoundedIcon, to: '/' },
  { label: 'Nuova analisi', icon: UploadFileRoundedIcon, to: '/new-analysis' },
  { label: 'Cronologia', icon: HistoryRoundedIcon, to: '/history' },
  { label: 'Stato del sistema', icon: MonitorHeartRoundedIcon, to: '/system-status' },
]

// La voce amministrativa viene aggiunta alla lista solo quando il context indica il ruolo admin.
const adminNavigationItem: NavItem = {
  label: 'Amministrazione',
  icon: AdminPanelSettingsRoundedIcon,
  to: '/admin',
}

function getPageTitle(pathname: string) {
  /**
   * Associa l'URL React al titolo mostrato nell'header globale.
   *
   * In questo modo l'intestazione della shell resta coerente anche quando la
   * pagina interna cambia senza ricaricare l'intera applicazione.
   */
  if (pathname.startsWith('/new-analysis')) {
    return 'Nuova analisi'
  }

  if (pathname.startsWith('/history')) {
    return 'Cronologia'
  }

  // Riconosce qualsiasi ID di analisi nello stesso prefisso e usa un titolo comune per il dettaglio.
  if (pathname.startsWith('/analyses/')) {
    return 'Dettaglio analisi'
  }

  if (pathname.startsWith('/system-status')) {
    return 'Stato del sistema'
  }

  // Il prefisso include sia la pagina profilo sia il percorso di modifica.
  if (pathname.startsWith('/profile')) {
    return 'Profilo'
  }

  // L’intestazione resta amministrativa anche nel dettaglio di un singolo utente.
  if (pathname.startsWith('/admin')) {
    return 'Amministrazione'
  }

  // Per i percorsi senza una corrispondenza precedente usa questo titolo di riserva.
  return 'Dashboard'
}

export function AppShell() {
  // useState mantiene apertura della sidebar e ancoraggio del menu utente; aggiornarli provoca un nuovo rendering.
  // false mostra la sidebar estesa; il pulsante del logo inverte il valore per passare alla vista compatta.
  const [isCollapsed, setIsCollapsed] = useState(false)
  // Conserva l’elemento cliccato a cui ancorare il menu; null equivale a menu chiuso.
  const [userMenuAnchor, setUserMenuAnchor] = useState<HTMLElement | null>(null)
  // useLocation legge l’URL corrente di React Router per titolo e selezione della voce di navigazione.
  const location = useLocation()
  // Il custom hook legge identità e callback dal context di autenticazione condiviso.
  const { hasRecognizedRole, isAdmin, logoutUser, user } = useAuth()

  // Calcola la larghezza usata insieme da barra superiore e sidebar per mantenere l’allineamento.
  const currentDrawerWidth = isCollapsed ? drawerCollapsedWidth : drawerWidth
  // Deriva il titolo dal pathname corrente, quindi si aggiorna quando React Router cambia percorso.
  const pageTitle = getPageTitle(location.pathname)
  // L’optional chaining legge l’utente se presente; ?? usa il nome di riserva quando il valore manca.
  const userDisplayName = user?.username ?? 'utente'
  // Sceglie il testo del ruolo per l’header a partire dal flag admin già derivato dal provider.
  const userRoleLabel = isAdmin ? 'Amministratore' : 'Analista'
  // Il ternario seleziona le voci per ruolo; lo spread aggiunge l’area admin a una nuova lista.
  const navigation = hasRecognizedRole
    ? isAdmin
      ? [...navigationItems, adminNavigationItem]
      : navigationItems
    : []

  // Prepara il contenuto della sidebar come espressione JSX da riutilizzare dentro Drawer.
  const drawerContent = (
    <Box
      sx={{
        height: '100%',
        bgcolor: '#0f2334',
        color: '#e6f0f5',
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      <Toolbar
        sx={{
          px: 0,
          minHeight: 84,
          justifyContent: 'center',
        }}
      >
        {/* Il suggerimento descrive l’azione del logo; il click alterna lo stato della sidebar usando il valore precedente. */}
        <Tooltip title={isCollapsed ? 'Apri menu' : 'Chiudi menu'} placement="right">
          <ButtonBase
            onClick={() => setIsCollapsed((previous) => !previous)}
            sx={{
              width: '100%',
              height: '100%',
              display: 'grid',
              placeItems: 'center',
            }}
          >
            <Box
              sx={{
                width: 44,
                height: 44,
                borderRadius: 2,
                bgcolor: 'rgba(108, 183, 196, 0.16)',
                display: 'grid',
                placeItems: 'center',
              }}
            >
              <SecurityRoundedIcon sx={{ color: '#8fd3dc' }} />
            </Box>
          </ButtonBase>
        </Tooltip>
      </Toolbar>
      {/* Nasconde il separatore nella sidebar compatta insieme agli elementi testuali non necessari. */}
      {!isCollapsed ? <Divider sx={{ borderColor: 'rgba(230, 240, 245, 0.08)' }} /> : null}
      <List sx={{ px: isCollapsed ? 0.75 : 1.5, py: 1.5 }}>
        {/* map crea un collegamento per ogni voce; key identifica stabilmente l’elemento durante gli aggiornamenti React. */}
        {navigation.map((item) => {
          // Per la dashboard richiede il percorso esatto; per le altre voci considera selezionate anche le sottopagine.
          const selected =
            item.to === '/' ? location.pathname === '/' : location.pathname.startsWith(item.to)

          return (
            <Tooltip key={item.to} title={item.label} placement="right">
              {/* Il pulsante usa NavLink per navigare; selected governa la rappresentazione della voce attiva. */}
              <ListItemButton
                component={NavLink}
                to={item.to}
                selected={selected}
                sx={{
                  mb: 0.75,
                  minHeight: 52,
                  px: isCollapsed ? 0 : 1.5,
                  justifyContent: 'center',
                  borderRadius: isCollapsed ? 0 : 2,
                  borderLeft: selected ? '3px solid #42d9ea' : '3px solid transparent',
                  color: '#ffffff',
                  bgcolor: selected
                    ? isCollapsed
                      ? 'rgba(143, 211, 220, 0.08)'
                      : 'rgba(143, 211, 220, 0.16)'
                    : 'transparent',
                  // Dentro sx, questo selettore personalizza il testo interno del componente MUI per la voce selezionata.
                  '& .MuiListItemText-primary': {
                    fontWeight: selected ? 700 : 500,
                  },
                  // Le regole di hover cambiano lo sfondo al passaggio del puntatore senza cambiare la selezione.
                  '&:hover': {
                    bgcolor: selected
                      ? isCollapsed
                        ? 'rgba(143, 211, 220, 0.08)'
                        : 'rgba(143, 211, 220, 0.16)'
                      : 'rgba(223, 245, 248, 0.08)',
                  },
                }}
              >
                <ListItemIcon
                  sx={{
                    minWidth: isCollapsed ? 0 : 40,
                    mr: isCollapsed ? 0 : 1,
                    color: '#ffffff',
                    justifyContent: 'center',
                  }}
                >
                  <item.icon />
                </ListItemIcon>
                {/* Nella modalità compatta resta l’icona; l’etichetta viene omessa dal rendering. */}
                {!isCollapsed ? <ListItemText primary={item.label} /> : null}
              </ListItemButton>
            </Tooltip>
          )
        })}
      </List>
    </Box>
  )

  return (
    <Box
      sx={{
        display: 'flex',
        minHeight: '100vh',
        width: '100vw',
        bgcolor: 'background.default',
      }}
    >
      {/* La barra superiore rimane fissa e lascia a sinistra lo spazio calcolato per la sidebar. */}
      <AppBar
        position="fixed"
        color="transparent"
        elevation={0}
        sx={{
          width: `calc(100% - ${currentDrawerWidth}px)`,
          ml: `${currentDrawerWidth}px`,
          borderBottom: '1px solid rgba(215, 224, 230, 0.85)',
          bgcolor: '#f7fbfd',
          backdropFilter: 'none',
          borderRadius: 0,
          overflow: 'hidden',
          boxShadow: 'none',
        }}
      >
        <Toolbar sx={{ minHeight: 84, px: 3, borderRadius: 0 }}>
          <Stack direction="row" spacing={2} sx={{ width: '100%', alignItems: 'center' }}>
            <Box sx={{ flexGrow: 1 }}>
              <Typography variant="h6">{pageTitle}</Typography>
            </Box>
            <ButtonBase
              onClick={(event) => setUserMenuAnchor(event.currentTarget)}
              sx={{
                px: 1,
                py: 0.75,
                borderRadius: 2,
                display: 'flex',
                alignItems: 'center',
                gap: 0.9,
                mr: -0.5,
                maxWidth: { xs: 48, sm: 220, lg: 280 },
                minWidth: 0,
                whiteSpace: 'nowrap',
                overflow: 'hidden',
              }}
            >
              {/* Mostra l’anteprima condivisa dal provider oppure l’iniziale dello username quando l’immagine non è disponibile. */}
              <Avatar src={user?.avatarDataUrl ?? undefined} sx={{ bgcolor: 'secondary.main', width: 38, height: 38 }}>
                {userDisplayName.charAt(0).toUpperCase()}
              </Avatar>
              <Box
                sx={{
                  textAlign: 'left',
                  minWidth: 0,
                  display: { xs: 'none', sm: 'block' },
                }}
              >
                <Typography
                  sx={{
                    fontWeight: 700,
                    whiteSpace: 'nowrap',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    fontSize: { sm: '0.95rem', lg: '1rem' },
                  }}
                  title={userDisplayName}
                >
                  {userDisplayName}
                </Typography>
                <Typography
                  variant="body2"
                  color="text.secondary"
                  sx={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}
                  title={user?.username ?? userRoleLabel}
                >
                  {userRoleLabel}
                </Typography>
              </Box>
            </ButtonBase>
          </Stack>
        </Toolbar>
      </AppBar>

      {/* Il menu MUI si posiziona sul pulsante memorizzato in userMenuAnchor e si chiude azzerando quel riferimento. */}
      <Menu
        anchorEl={userMenuAnchor}
        open={Boolean(userMenuAnchor)}
        onClose={() => setUserMenuAnchor(null)}
      >
        <MenuItem
          component={NavLink}
          to="/profile"
          onClick={() => setUserMenuAnchor(null)}
        >
          <ListItemIcon sx={{ minWidth: 34 }}>
            <PersonRoundedIcon fontSize="small" />
          </ListItemIcon>
          Profilo
        </MenuItem>
        <MenuItem
          onClick={() => {
            // Chiude il menu prima di richiedere il logout per non lasciarlo visibile durante il flusso di uscita.
            setUserMenuAnchor(null)
            // Avvia il logout asincrono esposto dal context; la navigazione verso Keycloak è delegata al client auth.
            void logoutUser()
          }}
        >
          <ListItemIcon sx={{ minWidth: 34 }}>
            <LogoutRoundedIcon fontSize="small" />
          </ListItemIcon>
          Esci
        </MenuItem>
      </Menu>

      {/* Il contenitore ha ruolo di navigazione e conserva lo spazio orizzontale della sidebar. */}
      <Box component="nav" sx={{ width: currentDrawerWidth, flexShrink: 0 }} aria-label="main navigation">
        {/* Drawer permanente mantiene la sidebar montata; la transizione anima soltanto il cambiamento di larghezza. */}
        <Drawer
          variant="permanent"
          open
          sx={{
            width: currentDrawerWidth,
            '& .MuiDrawer-paper': {
              width: currentDrawerWidth,
              transition: 'width 180ms ease',
              border: 'none',
              borderRadius: 0,
              overflowX: 'hidden',
              boxShadow: 'none',
              top: 0,
            },
          }}
        >
          {/* Inserisce logo e lista delle destinazioni preparati in precedenza in base al ruolo. */}
          {drawerContent}
        </Drawer>
      </Box>

      <Box
        component="main"
        sx={{
          flexGrow: 1,
          minHeight: '100vh',
          // Lascia spazio sopra il contenuto affinché la barra fissa non copra l’inizio della pagina.
          pt: '84px',
          // sx applica padding orizzontale diverso dai breakpoint MUI: più contenuto sugli schermi piccoli.
          px: { xs: 2, md: 3 },
          pb: 3,
          bgcolor: 'background.default',
        }}
      >
        {/* Outlet inserisce la pagina figlia della route corrente dentro la cornice condivisa della shell. */}
        <Outlet />
      </Box>
    </Box>
  )
}
