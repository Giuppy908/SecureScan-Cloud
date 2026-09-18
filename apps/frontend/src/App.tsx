/**
 * Questo file definisce il punto di routing principale del frontend SecureScan Cloud.
 *
 * Tutte le pagine visibili dell'applicazione React passano da qui: Dashboard,
 * Nuova analisi, Cronologia, Dettaglio analisi, Stato del sistema, Profilo e
 * Amministrazione. Il componente non contiene logica di business propria, ma
 * collega tema grafico, autenticazione Keycloak e route protette.
 *
 * In pratica il flusso del browser parte qui:
 * utente autenticato -> route React -> controllo ruolo lato frontend ->
 * pagina richiesta -> chiamate HTTP verso Kong / Analysis API.
 *
 * I controlli qui presenti migliorano l'esperienza utente, ma non sostituiscono
 * mai l'autorizzazione server-side applicata dall'Analysis API.
 */
// MUI fornisce sia il provider del tema sia il componente che applica le regole CSS globali.
import { CssBaseline, ThemeProvider } from '@mui/material'
// React Router associa l’URL del browser agli elementi React senza richiedere un documento HTML per ogni pagina.
import { BrowserRouter, Route, Routes } from 'react-router'
// L’autenticazione viene inizializzata prima di montare le pagine che consumano il suo context.
import { AuthProvider } from './auth/AuthProvider'
// Le due guardie separano pagine per analyst e pagine per admin; i permessi server rimangono indipendenti.
import { ProtectedRoute } from './auth/ProtectedRoute'
import { RoleRoute } from './auth/RoleRoute'
// Il layout contiene Outlet, il punto dove React Router inserisce il contenuto della route figlia.
import { AppShell } from './layout/AppShell'
// Le pagine importate diventano gli elementi delle route: l’import non avvia le loro richieste HTTP.
import { AdminPage } from './pages/AdminPage'
import { AdminUserDetailPage } from './pages/AdminUserDetailPage'
import { AnalysisDetailPage } from './pages/AnalysisDetailPage'
import { DashboardPage } from './pages/DashboardPage'
import { HistoryPage } from './pages/HistoryPage'
import { NewAnalysisPage } from './pages/NewAnalysisPage'
import { NotFoundPage } from './pages/NotFoundPage'
import { ProfileEditPage } from './pages/ProfileEditPage'
import { ProfilePage } from './pages/ProfilePage'
import { SystemStatusPage } from './pages/SystemStatusPage'
import { appTheme } from './theme/appTheme'

// Il componente funzionale compone tema MUI, contesto condiviso e router senza mantenere uno stato locale.
function App() {
  // ThemeProvider condivide il tema MUI; CssBaseline applica gli stili globali prima delle pagine.
  return (
    <ThemeProvider theme={appTheme}>
      {/* Applica gli stili globali MUI usando il tema passato al contenitore ThemeProvider. */}
      <CssBaseline />
      {/* Il provider mostra attesa o errore prima di rendere il router disponibile ai suoi figli. */}
      <AuthProvider>
        {/* Usa la cronologia del browser per leggere il percorso e aggiornare la navigazione senza reload completo. */}
        <BrowserRouter>
          {/* Routes sceglie la corrispondenza tra i percorsi dichiarati e l’URL, includendo le route annidate. */}
          <Routes>
            {/* La route senza percorso mantiene AppShell come layout comune mentre cambia la pagina figlia. */}
            <Route element={<AppShell />}>
              {/* La route index corrisponde alla radice e mostra la Dashboard dopo il controllo analyst. */}
              <Route
                index
                element={
                  <ProtectedRoute>
                    <DashboardPage />
                  </ProtectedRoute>
                }
              />
              {/* Il percorso di upload monta Nuova analisi, che avvia le proprie richieste solo dopo il controllo della guardia. */}
              <Route
                path="/new-analysis"
                element={
                  <ProtectedRoute>
                    <NewAnalysisPage />
                  </ProtectedRoute>
                }
              />
              {/* La cronologia è protetta e mantiene filtri e paginazione nello stato della pagina. */}
              <Route
                path="/history"
                element={
                  <ProtectedRoute>
                    <HistoryPage />
                  </ProtectedRoute>
                }
              />
              {/* Il segmento :analysisId è dinamico e viene letto con useParams nella pagina di dettaglio. */}
              <Route
                path="/analyses/:analysisId"
                element={
                  <ProtectedRoute>
                    <AnalysisDetailPage />
                  </ProtectedRoute>
                }
              />
              {/* La pagina di stato legge uno snapshot aggregato via API ed è accessibile attraverso la guardia analyst. */}
              <Route
                path="/system-status"
                element={
                  <ProtectedRoute>
                    <SystemStatusPage />
                  </ProtectedRoute>
                }
              />
              {/* Il profilo opera sull’identità autenticata, senza un subject selezionabile nel percorso. */}
              <Route
                path="/profile"
                element={
                  <ProtectedRoute>
                    <ProfilePage />
                  </ProtectedRoute>
                }
              />
              {/* La modifica del proprio profilo usa la stessa guardia delle altre pagine ordinarie. */}
              <Route
                path="/profile/edit"
                element={
                  <ProtectedRoute>
                    <ProfileEditPage />
                  </ProtectedRoute>
                }
              />
              {/* L’area utenti usa RoleRoute, che richiede il flag admin anziché il solo ruolo analyst. */}
              <Route
                path="/admin"
                element={
                  <RoleRoute>
                    <AdminPage />
                  </RoleRoute>
                }
              />
              {/* Il segmento :subject identifica l’account del dettaglio amministrativo ed è protetto da RoleRoute. */}
              <Route
                path="/admin/users/:subject"
                element={
                  <RoleRoute>
                    <AdminUserDetailPage />
                  </RoleRoute>
                }
              />
              {/* Il percorso jolly mostra la pagina di errore quando nessuna route specifica corrisponde all’URL. */}
              <Route path="*" element={<NotFoundPage />} />
            </Route>
          </Routes>
        </BrowserRouter>
      </AuthProvider>
    </ThemeProvider>
  )
}

export default App
