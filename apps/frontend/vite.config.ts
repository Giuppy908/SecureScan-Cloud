// defineConfig fornisce assistenza sui tipi delle opzioni Vite senza avviare l'applicazione.
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

/**
 * Configurazione di build e sviluppo del frontend React.
 *
 * Non rappresenta una pagina dell'interfaccia: abilita il plugin React usato da
 * Vite per compilare TSX, gestire HMR e produrre gli asset statici serviti poi
 * dal container Nginx.
 */
// Esporta la configurazione letta da Vite per il server di sviluppo e per il bundle di produzione.
export default defineConfig({
  // Il plugin integra React nella compilazione Vite e nell’aggiornamento dei componenti durante lo sviluppo.
  plugins: [react()],
})
