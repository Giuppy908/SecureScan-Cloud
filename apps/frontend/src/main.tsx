/**
 * Entry point minimale del bundle Vite/React.
 *
 * Questo file non rappresenta direttamente una pagina del sito: inizializza
 * l'applicazione nel nodo `#root` del documento HTML e delega tutto il resto a
 * `App.tsx`, dove vengono poi montati tema, autenticazione e routing.
 */
// StrictMode abilita controlli di sviluppo e può ripetere setup e cleanup degli effetti per evidenziare problemi.
import { StrictMode } from 'react'
// createRoot collega un albero di componenti React a un elemento del documento HTML.
import { createRoot } from 'react-dom/client'
// Questo import ha un effetto sullo stile globale: Vite include le regole CSS nel frontend.
import './index.css'
import App from './App'

// Collega React al nodo HTML root; StrictMode abilita controlli aggiuntivi in sviluppo, inclusa la ripetizione degli effetti.
// L’asserzione ! comunica a TypeScript che root esiste; non aggiunge un controllo runtime sull’elemento HTML.
createRoot(document.getElementById('root')!).render(
  <StrictMode>
    {/* App è il componente radice: da qui derivano provider, router, layout e pagine. */}
    <App />
  </StrictMode>,
)
