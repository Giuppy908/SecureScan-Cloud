# SecureScan Frontend

Il SecureScan Frontend è l'interfaccia web della piattaforma SecureScan Cloud.

Il componente è sviluppato utilizzando `React`, `TypeScript`, `Vite` e `Material UI (MUI)` e rappresenta il livello di presentazione dell'applicazione.

Attraverso il frontend gli utenti possono autenticarsi, caricare file da analizzare, consultare lo storico delle scansioni, visualizzare i risultati prodotti dalla pipeline malware, monitorare lo stato del sistema e utilizzare le funzionalità amministrative autorizzate.

Il frontend non implementa direttamente operazioni critiche come l'accesso al database, l'esecuzione delle scansioni o la gestione dei motori di sicurezza.

Tutte le operazioni vengono effettuate tramite le API backend esposte dall'architettura SecureScan Cloud.

## Ruolo nell'architettura SecureScan Cloud

Il frontend rappresenta il punto di interazione tra l'utente e la piattaforma.

Il flusso generale delle richieste è il seguente:

L'utente utilizza il frontend web per effettuare operazioni come autenticazione, caricamento file o consultazione dei risultati.

Le richieste vengono inoltrate attraverso `Kong API Gateway`, che rappresenta il punto di accesso pubblico dell'architettura.

Il gateway comunica con `Analysis API`, responsabile della gestione delle operazioni applicative.

Quando viene caricato un file, l'API crea il job di analisi e salva le informazioni iniziali nel database `PostgreSQL`.

Successivamente l'`Analysis Worker` recupera i job pendenti dal database, esegue la pipeline di scansione composta da analisi strutturale, `ClamAV` e `YARA`, quindi aggiorna il risultato finale in `PostgreSQL`.

Il frontend recupera successivamente lo stato aggiornato attraverso le API esposte dal gateway.

Il browser non comunica direttamente con:

- database;
- `ClamAV`;
- `YARA`;
- servizi interni di elaborazione.

## Tecnologie principali

Il frontend utilizza:

- `React` per la costruzione dell'interfaccia utente;
- `TypeScript` per la tipizzazione statica;
- `Vite` come ambiente di sviluppo e build;
- `Material UI (MUI)` per i componenti grafici;
- `Keycloak` per autenticazione e gestione delle identità;
- `JWT Bearer Token` per autorizzare le richieste verso il backend.

La struttura del codice separa le diverse responsabilità applicative:

- autenticazione;
- routing;
- componenti grafici;
- pagine;
- comunicazione API;
- configurazione;
- modelli dati.

## Struttura del progetto

Il codice applicativo è organizzato principalmente all'interno della directory `src`.

### `src/auth`

Contiene tutta la gestione dell'autenticazione:

- configurazione del client `Keycloak`;
- provider globale dell'utente autenticato;
- gestione del contesto di autenticazione;
- protezione delle route;
- verifica dei ruoli.

### `src/api`

Contiene i client utilizzati per comunicare con i servizi backend.

Le richieste includono automaticamente il token JWT necessario per accedere alle risorse protette.

### `src/pages`

Contiene le pagine principali dell'applicazione:

- Dashboard;
- Nuova analisi;
- Cronologia;
- Dettaglio analisi;
- Stato del sistema;
- Profilo;
- Modifica profilo;
- Amministrazione;
- Dettaglio utente amministrativo.

### `src/components`

Contiene componenti grafici riutilizzabili:

- intestazioni delle pagine;
- card informative;
- indicatori di rischio;
- indicatori di stato;
- pannelli informativi.

### `src/layout`

Contiene la struttura comune dell'interfaccia:

- sidebar di navigazione;
- header superiore;
- area centrale delle pagine.

### `src/theme`

Contiene la configurazione del tema grafico basato su `Material UI`.

## Autenticazione e gestione dei ruoli

L'autenticazione è delegata a `Keycloak`.

Il flusso di autenticazione prevede:

1. l'utente accede al frontend;
2. il frontend avvia il login tramite `Keycloak`;
3. `Keycloak` restituisce un token JWT;
4. il frontend utilizza il token nelle richieste verso le API;
5. il backend verifica identità e autorizzazioni.

Il frontend gestisce principalmente due ruoli applicativi:

- `analyst`;
- `admin`.

Il ruolo determina quali funzionalità vengono rese disponibili nell'interfaccia.

Un utente con ruolo `analyst` può lavorare sulle proprie analisi, mentre un utente con ruolo `admin` dispone anche delle funzionalità amministrative.

La protezione reale delle risorse viene comunque applicata lato backend. Il frontend può limitare la visibilità delle sezioni, ma non rappresenta un meccanismo di sicurezza autonomo.

## Routing e protezione delle pagine

Il routing dell'applicazione utilizza componenti dedicati alla protezione delle sezioni private.

### `ProtectedRoute`

Verifica che l'utente sia autenticato prima di consentire l'accesso alle pagine protette.

### `RoleRoute`

Verifica che l'utente disponga del ruolo necessario per accedere a determinate funzionalità.

Gli utenti privi delle autorizzazioni richieste vengono indirizzati verso una pagina dedicata.

## Struttura dell'interfaccia

L'applicazione utilizza una shell comune composta da:

- sidebar di navigazione;
- header superiore;
- area centrale dinamica.

La struttura permette di mantenere una navigazione uniforme tra tutte le sezioni della piattaforma.

Le funzionalità mostrate vengono adattate in base al ruolo dell'utente autenticato.

## Dashboard

La Dashboard rappresenta la vista sintetica dello stato della piattaforma.

Le informazioni visualizzate vengono recuperate dai servizi backend e permettono di osservare:

- numero complessivo delle analisi;
- distribuzione dei livelli di rischio;
- stato delle elaborazioni;
- indicatori sintetici del sistema.

Le informazioni principali non dipendono da dati statici locali.

## Nuova analisi

La pagina Nuova analisi permette il caricamento di un file verso l'`Analysis API`.

Il flusso operativo è:

1. selezione del file;
2. invio della richiesta autenticata;
3. creazione del job lato backend;
4. aggiornamento dello stato dell'analisi.

Il frontend non esegue direttamente alcuna scansione.

L'elaborazione viene completata successivamente dall'`Analysis Worker`.

## Cronologia analisi

La pagina Cronologia utilizza una gestione della paginazione completamente server-side.

Il frontend richiede solamente i dati necessari alla pagina corrente.

Sono disponibili:

- ricerca per nome file;
- filtro per stato;
- filtro per livello di rischio;
- filtro per utente amministrativo;
- modifica della dimensione della pagina.

Il backend restituisce il totale reale dei risultati filtrati, permettendo alla UI di mostrare informazioni coerenti anche con dataset più grandi.

## Dettaglio analisi

La pagina Dettaglio analisi mostra il risultato completo prodotto dalla pipeline di scansione.

Sono disponibili informazioni relative a:

- stato dell'analisi;
- livello di rischio;
- verdict finale;
- indicatori tecnici;
- risultati `ClamAV`;
- risultati `YARA`.

I dati vengono recuperati attraverso le API backend.

## Profilo utente

La sezione Profilo permette agli utenti autenticati di gestire le proprie informazioni.

Sono disponibili funzionalità relative a:

- visualizzazione del profilo;
- modifica delle informazioni personali;
- gestione dell'avatar;
- aggiornamento della password.

Le operazioni sono riferite esclusivamente all'identità autenticata.

## Amministrazione

La sezione Amministrazione è disponibile solamente agli utenti con ruolo `admin`.

Le funzionalità principali includono:

- visualizzazione utenti;
- apertura del dettaglio utente;
- modifica delle informazioni amministrative;
- gestione dello stato dell'account;
- consultazione delle analisi associate.

Le autorizzazioni vengono sempre verificate dal backend.

## Comunicazione con le API

Il frontend utilizza client API dedicati per comunicare con i servizi backend.

Le richieste:

- utilizzano il gateway come punto di accesso;
- includono il token JWT;
- utilizzano modelli TypeScript per rappresentare i dati;
- gestiscono le risposte provenienti dai servizi applicativi.

La configurazione degli endpoint viene mantenuta separata dal codice delle pagine.

## Tema grafico e componenti riutilizzabili

L'interfaccia utilizza un tema personalizzato basato su `Material UI`.

Sono presenti componenti riutilizzabili per mantenere uniformità grafica:

- card informative;
- badge di rischio;
- badge di stato;
- pannelli informativi;
- componenti della shell principale.

Questa organizzazione permette di mantenere una UI coerente tra tutte le sezioni della piattaforma.

## Build e sviluppo locale

Installazione delle dipendenze:

`npm install`

Avvio ambiente sviluppo:

`npm run dev`

Creazione della build di produzione:

`npm run build`

Controllo qualità del codice:

`npm run lint`

## Esecuzione tramite Docker

Il frontend viene distribuito come servizio indipendente nello stack Docker Compose.

Il container utilizza un server web dedicato per pubblicare gli asset statici generati dalla build.

## Collegamenti documentazione

- README principale
- Analysis API
- Analysis Worker
- Autenticazione e RBAC
- Request flow
- Guida al codice