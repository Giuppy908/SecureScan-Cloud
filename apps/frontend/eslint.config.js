/**
 * Regole statiche di lint per il codice TypeScript/React del frontend.
 *
 * Questo file non modifica il comportamento runtime: aiuta a mantenere il codice
 * coerente e a intercettare errori comuni durante lo sviluppo.
 */
import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'
import { defineConfig, globalIgnores } from 'eslint/config'

export default defineConfig([
  // Esclude il bundle generato dai controlli statici.
  globalIgnores(['dist']),
  {
    // Applica ai sorgenti TS e TSX le regole JavaScript, TypeScript, hook React e React Refresh.
    files: ['**/*.{ts,tsx}'],
    extends: [
      // Le regole JavaScript segnalano costrutti problematici comuni anche nei sorgenti TypeScript.
      js.configs.recommended,
      // Le regole TypeScript analizzano anche i costrutti di tipo non presenti in JavaScript.
      tseslint.configs.recommended,
      // Le regole React controllano l'uso degli hook e le dipendenze degli effetti.
      reactHooks.configs.flat.recommended,
      // Le regole React Refresh verificano le esportazioni compatibili con l'aggiornamento durante lo sviluppo.
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      // Riconosce i nomi globali del browser, come window e document, senza dichiararli nei sorgenti.
      globals: globals.browser,
    },
  },
])
