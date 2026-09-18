# SecureScan Analysis API

L'Analysis API è il servizio backend principale di SecureScan Cloud.  
È responsabile dell'esposizione delle API REST utilizzate dal frontend, della gestione delle analisi dei file, dell'applicazione dei controlli di sicurezza lato server e dell'integrazione con i componenti esterni della piattaforma.

Il servizio è sviluppato con FastAPI e rappresenta il punto di coordinamento tra:

- frontend React;
- API Gateway Kong;
- identity provider Keycloak;
- database PostgreSQL;
- Analysis Worker dedicato alla scansione malware;
- sistemi di monitoraggio e diagnostica.

L'Analysis API non esegue direttamente la scansione antivirus dei file.  
La sua responsabilità è gestire il ciclo di vita dell'analisi: ricevere il caricamento, validare la richiesta, salvare il file nello storage condiviso, creare il job iniziale e fornire al worker tutte le informazioni necessarie per completare la pipeline.

La separazione tra API e worker permette di mantenere il servizio HTTP veloce e disponibile anche durante analisi potenzialmente lunghe.

# Ruolo nell'architettura

All'interno di SecureScan Cloud l'Analysis API rappresenta il livello applicativo centrale.

Il flusso generale è:

```text
                    Utente
                      |
                      v
              React Frontend
                      |
                      v
                Kong Gateway
                      |
                      v
          +-+
          |   Analysis API       |
          +-+
             |        |        |
             |        |        |
             v        v        v
       PostgreSQL  Keycloak  Worker
                         |
                         v
                   ClamAV / YARA
```

Il browser comunica esclusivamente con il livello pubblico esposto da Kong.  
L'API Gateway inoltra le richieste verso le repliche dell'Analysis API, che applicano i controlli applicativi prima di accedere alle risorse interne.

# Responsabilità principali

L'Analysis API raggruppa diverse responsabilità applicative.

## Gestione delle analisi

Il servizio gestisce l'intero ciclo di vita di un'analisi:

- ricezione del file tramite upload HTTP;
- validazione della richiesta;
- salvataggio temporaneo del file;
- creazione del job asincrono;
- esposizione dello stato dell'elaborazione;
- recupero dei risultati prodotti dal worker.

Il caricamento non blocca l'utente fino al completamento della scansione.  
La richiesta viene accettata immediatamente e l'analisi viene completata successivamente dal componente worker.

Il primo stato assegnato a una nuova analisi è:

```text
queued
```

Successivamente il worker aggiorna lo stato durante il processo:

```text
queued
    |
    v
processing
    |
    v
completed
```

In caso di problemi durante la pipeline:

```text
processing
    |
    v
failed
```

## Applicazione della sicurezza

L'Analysis API rappresenta il punto in cui vengono applicate le autorizzazioni reali.

Il frontend può adattare la propria interfaccia in base al ruolo dell'utente, ma la sicurezza effettiva viene sempre verificata lato backend.

Il servizio controlla:

- validità del JWT;
- firma del token;
- issuer Keycloak;
- audience;
- algoritmo utilizzato;
- scadenza;
- subject dell'utente;
- ruoli associati.

## Controllo ownership delle analisi

Ogni analisi viene associata all'utente che l'ha creata attraverso:

```text
owner_sub
owner_username
```

Questo permette di applicare il modello:

### Analyst

Può:

- creare analisi;
- visualizzare solamente le proprie analisi;
- consultare i propri risultati;
- modificare il proprio profilo.

### Admin

Può:

- visualizzare tutte le analisi;
- filtrare per utente;
- accedere alle funzioni amministrative.

Il controllo viene applicato nelle query del backend e non solamente nella UI.

# Struttura del componente

La struttura principale del servizio è:

```text
apps/analysis-api/

├── app/
│   ├── api/
│   ├── auth/
│   ├── core/
│   ├── db/
│   ├── models/
│   ├── repositories/
│   ├── services/
│   └── main.py
│
├── alembic/
├── tests/
├── Dockerfile
├── entrypoint.sh
├── requirements.txt
└── README.md
```

Ogni livello ha un ruolo separato:

| Directory | Responsabilità |
|||
| `api/` | endpoint REST esposti al frontend |
| `auth/` | autenticazione JWT e autorizzazione RBAC |
| `core/` | configurazione runtime |
| `db/` | connessione database e modelli ORM |
| `models/` | modelli applicativi Pydantic |
| `repositories/` | accesso astratto ai dati |
| `services/` | logica applicativa |
| `tests/` | test automatici |

Questa separazione evita di inserire logica business direttamente negli endpoint HTTP.

# Tecnologie utilizzate

| Tecnologia | Utilizzo |
|||
| FastAPI | framework REST asincrono |
| Pydantic | validazione e serializzazione dati |
| SQLAlchemy | ORM per PostgreSQL |
| Alembic | gestione migrazioni database |
| PostgreSQL | persistenza dati applicativi |
| PyJWT | verifica token JWT |
| Keycloak | autenticazione e gestione identità |
| Prometheus | raccolta metriche |
| Docker | containerizzazione del servizio |



# Avvio dell'applicazione

L'applicazione viene inizializzata attraverso:

```text
app/main.py
```

Questo file non contiene la logica delle singole funzionalità, ma coordina:

- creazione dell'applicazione FastAPI;
- registrazione dei router;
- middleware comuni;
- heartbeat della replica;
- configurazione CORS.

La creazione dell'applicazione avviene tramite:

```python
create_app()
```

che restituisce l'istanza completa utilizzata dal server Uvicorn.

# Ciclo di vita dell'applicazione

Durante l'avvio l'Analysis API inizializza tutti i componenti necessari al funzionamento del servizio.

Il ciclo di vita viene gestito attraverso il meccanismo `lifespan` di FastAPI.

Le fasi principali sono:

```text
Startup
   |
   v
Creazione heartbeat API
   |
   v
Registrazione router
   |
   v
Avvio server HTTP
   |
   v
Gestione richieste
   |
   v
Shutdown
   |
   v
Arresto heartbeat
```



# Startup e heartbeat della replica API

Ogni replica dell'Analysis API mantiene un proprio heartbeat applicativo.

L'heartbeat viene registrato nella tabella:

```text
api_instance_heartbeats
```

Questo meccanismo è diverso dai semplici health check Docker.

Un container può infatti risultare attivo dal punto di vista del runtime, ma non essere più in grado di:

- elaborare richieste correttamente;
- comunicare con il database;
- aggiornare il proprio stato applicativo.

L'heartbeat permette quindi di distinguere:

| Tipo di controllo | Significato |
|||
| Docker health check | il processo container è raggiungibile |
| API heartbeat | la replica sta funzionando correttamente a livello applicativo |

Ogni istanza registra:

- identificativo della replica;
- hostname;
- stato corrente;
- momento di avvio;
- ultimo heartbeat.

Questo dato viene utilizzato dalla pagina:

```text
Stato del sistema
```

e dalle funzionalità di diagnostica.



# Middleware applicativi

L'Analysis API utilizza middleware globali per applicare funzionalità comuni a tutte le richieste.

## Correlation ID

Ogni richiesta riceve un identificativo univoco:

```text
X-Request-ID
```

Se il client fornisce già un valore valido viene mantenuto, altrimenti viene generato automaticamente.

Questo permette di correlare:

- log applicativi;
- errori;
- richieste HTTP;
- eventi di sicurezza.



## Header della replica

Ogni risposta contiene:

```text
X-Backend-Instance
```

che identifica la replica API che ha elaborato la richiesta.

Questo è utile durante i test di:

- load balancing;
- alta disponibilità;
- distribuzione delle richieste tra repliche.



## Metriche HTTP

Il middleware registra automaticamente:

- metodo HTTP;
- endpoint;
- codice risposta;
- tempo di elaborazione.

Le metriche vengono utilizzate dal sistema di osservabilità basato su Prometheus.

La registrazione centralizzata evita di duplicare logica all'interno dei singoli endpoint.



# Configurazione runtime

La configurazione dell'Analysis API è centralizzata nel file:

```text
app/core/config.py
```

Il servizio utilizza configurazione tramite variabili d'ambiente.

Questo permette di utilizzare lo stesso codice in:

- sviluppo locale;
- Docker Compose;
- eventuali deployment cloud.



# Configurazione generale

Parametri principali:

| Parametro | Descrizione |
|-|-|
| `APP_NAME` | nome applicazione |
| `APP_VERSION` | versione servizio |
| `API_PREFIX` | prefisso degli endpoint |
| `INSTANCE_ID` | identificativo della replica |

Il prefisso predefinito delle API è:

```text
/api/v1
```



# Configurazione CORS

Il backend permette la comunicazione con il frontend tramite origini configurabili.

Configurazione esempio:

```text
http://localhost:5173
http://localhost:8080
```

Le origini non sono hardcoded perché in ambiente pubblico saranno diverse.



# Configurazione upload

La dimensione massima dei file analizzabili viene controllata tramite:

```text
MAX_UPLOAD_SIZE_MB
```

Il valore viene convertito internamente in byte.

Il limite evita:

- saturazione dello storage;
- richieste HTTP eccessivamente grandi;
- consumo incontrollato di risorse.

Il file viene salvato inizialmente nello storage condiviso e successivamente rimosso al termine della pipeline.



# Configurazione avatar

Gli avatar utente utilizzano una configurazione separata:

```text
MAX_AVATAR_SIZE_MB
AVATAR_DIR
```

Sono previsti controlli dedicati perché gli avatar seguono un ciclo di vita differente rispetto ai file analizzati.



# Configurazione ClamAV

L'API mantiene la configurazione necessaria per comunicare con il servizio antivirus:

| Parametro | Utilizzo |
|-|-|
| `CLAMD_HOST` | indirizzo servizio ClamAV |
| `CLAMD_PORT` | porta del daemon |
| `CLAMD_TIMEOUT_SECONDS` | timeout comunicazione |

La scansione vera e propria viene eseguita dal worker, ma la configurazione rimane condivisa nel modello applicativo.



# Configurazione Keycloak

Keycloak rappresenta il provider di identità della piattaforma.

L'Analysis API utilizza:

## Endpoint interno

```text
KEYCLOAK_INTERNAL_URL
```

utilizzato dalle comunicazioni server-side.



## Realm

```text
KEYCLOAK_REALM
```

Identifica il dominio applicativo:

```text
securescan
```



## Issuer JWT

```text
KEYCLOAK_ISSUER
```

Permette di verificare che il token provenga dal corretto identity provider.



## JWKS endpoint

```text
KEYCLOAK_JWKS_URL
```

Viene utilizzato per recuperare le chiavi pubbliche necessarie alla verifica della firma JWT.



## Audience

```text
KEYCLOAK_AUDIENCE
```

Permette di verificare che il token sia destinato all'API corretta.



# Configurazione amministrativa Keycloak

Il backend utilizza un client dedicato per le operazioni amministrative.

Sono configurati:

```text
KEYCLOAK_ADMIN_CLIENT_ID
KEYCLOAK_ADMIN_CLIENT_SECRET
```

Queste credenziali non vengono mai esposte al frontend.

Le operazioni amministrative passano sempre dal backend:

```text
Frontend
   |
   v
Analysis API
   |
   v
Keycloak Admin API
```



# Configurazione monitoring

L'API mantiene gli endpoint dei servizi di monitoraggio:

| Servizio | Endpoint |
|-|-|
| Kong | status API |
| Prometheus | health endpoint |
| Grafana | health endpoint |
| PostgreSQL exporter | metriche |

Queste informazioni vengono utilizzate dalla pagina:

```text
Stato del sistema
```



# Endpoint disponibili

I router vengono registrati all'interno di `main.py`.

Gli endpoint principali sono:

| Router | Prefisso | Responsabilità |
|-|-|-|
| Health | `/health` | verifica disponibilità |
| Metrics | `/metrics` | metriche Prometheus |
| Analyses | `/api/v1/analyses` | gestione scansioni |
| Profile | `/api/v1/me` | profilo utente |
| Admin | `/api/v1/admin/users` | amministrazione |
| Dashboard | `/api/v1/dashboard` | dati aggregati |
| System Status | `/api/v1/system/status` | stato piattaforma |



# Gestione analisi

Il router principale delle analisi è:

```text
app/api/analyses.py
```

Gestisce:

- caricamento file;
- cronologia;
- dettaglio;
- cancellazione amministrativa.



# Creazione di una nuova analisi

Endpoint:

```http
POST /api/v1/analyses
```

Richiede:

- autenticazione valida;
- ruolo analyst o admin;
- file multipart.



## Flusso completo

```text
Frontend
   |
   | upload file
   v
Analysis API
   |
   | validazione
   v
Upload Storage
   |
   | creazione record
   v
PostgreSQL
   |
   | stato queued
   v
Analysis Worker
```



L'endpoint restituisce:

```http
202 Accepted
```

perché l'elaborazione non è ancora terminata.

La risposta contiene il record iniziale dell'analisi con:

```json
{
  "status": "queued"
}
```

Il worker aggiornerà successivamente:

- stato;
- rischio;
- verdict;
- indicatori;
- risultati ClamAV;
- risultati YARA.

# Cronologia e paginazione server-side

La pagina Cronologia utilizza una gestione completamente server-side dei dati.

Il frontend non scarica l'intero insieme delle analisi per applicare successivamente filtri e paginazione locale.

Questo approccio è stato scelto per:

- ridurre il traffico tra frontend e backend;
- evitare di caricare in memoria grandi quantità di dati;
- mantenere coerente il controllo RBAC;
- permettere la scalabilità anche con un numero elevato di analisi.

Il backend restituisce esclusivamente la porzione di dati richiesta dalla pagina corrente.

# Endpoint Cronologia

Endpoint:

```http
GET /api/v1/analyses
```

Parametri supportati:

| Parametro | Descrizione |
|-|-|
| `page` | numero pagina richiesta |
| `page_size` | numero elementi per pagina |
| `search` | ricerca per nome file |
| `status` | filtro stato analisi |
| `risk` | filtro livello rischio |
| `owner` | filtro utente disponibile agli admin |

Esempio:

```http
GET /api/v1/analyses?page=2&page_size=10&status=completed&risk=high
```

# Ordine delle operazioni lato backend

L'ordine con cui vengono applicate le operazioni è fondamentale.

Il repository esegue:

```text
1. Applicazione RBAC
        |
        v
2. Applicazione filtri
        |
        v
3. Calcolo totale filtrato
        |
        v
4. Ordinamento risultati
        |
        v
5. Offset e limit
```

Questo garantisce che il valore:

```json
{
  "total": 125
}
```

rappresenti realmente tutti gli elementi compatibili con i filtri selezionati e non solamente quelli presenti nella pagina corrente.

# Controllo ownership nella Cronologia

Prima di qualsiasi query viene determinato lo scope dell'utente.

Per un utente analyst:

```python
owner_sub = user.subject
```

La query viene limitata automaticamente alle proprie analisi.

Per un amministratore:

```python
owner_sub = None
```

e viene permessa la consultazione globale.

L'eventuale filtro:

```text
owner
```

è disponibile solamente agli amministratori.

Questo impedisce a un utente normale di modificare parametri HTTP per accedere ai dati di altri utenti.

# Risposta paginata

La risposta dell'endpoint utilizza il modello:

```json
{
  "items": [],
  "total": 0,
  "page": 1,
  "page_size": 10,
  "total_pages": 0
}
```

Dove:

| Campo | Significato |
|-|-|
| `items` | risultati della pagina corrente |
| `total` | numero totale filtrato |
| `page` | pagina corrente |
| `page_size` | dimensione pagina |
| `total_pages` | numero pagine disponibili |

# Dettaglio analisi

Endpoint:

```http
GET /api/v1/analyses/{analysis_id}
```

Questo endpoint restituisce tutte le informazioni relative a una singola analisi.

Il recupero comprende:

- identificativo analisi;
- nome file;
- dimensione;
- stato;
- rischio;
- metadati strutturali;
- hash SHA-256;
- risultati ClamAV;
- risultati YARA;
- indicatori;
- verdict finale.

# Sicurezza del dettaglio

Anche conoscendo direttamente l'identificativo:

```text
ANL-2026-0001
```

un utente non può accedere arbitrariamente al risultato.

La query applica sempre lo scope autorizzato.

Esempio:

```text
Analyst A
    |
    +--> ANL-0001  OK
    |
    +--> ANL-0002  404

Analyst B
    |
    +--> ANL-0002  OK
```

Il controllo viene eseguito lato database e non tramite il frontend.

# Modello dati delle analisi

Il modello applicativo principale è definito in:

```text
app/models/analysis.py
```

Il sistema distingue tra:

- modelli Pydantic utilizzati dalle API;
- modelli ORM utilizzati dal database.

# Stati dell'analisi

Gli stati applicativi disponibili sono:

| Stato | Significato |
|-|-|
| `queued` | analisi creata e in attesa del worker |
| `processing` | scansione in corso |
| `completed` | pipeline terminata correttamente |
| `failed` | impossibile completare l'analisi |

# Verdict malware

Il risultato della pipeline utilizza:

| Verdict | Descrizione |
|-|-|
| `clean` | nessun indicatore rilevante |
| `suspicious` | elementi anomali da approfondire |
| `malicious` | rilevazione malevola |
| `scan_error` | analisi non completata correttamente |

È importante distinguere:

```text
completed
```

dallo stato del lavoro asincrono:

```text
clean / suspicious / malicious / scan_error
```

Un job può terminare tecnicamente ma produrre:

```text
scan_error
```

perché uno dei motori obbligatori non ha completato correttamente la scansione.

# Livelli di rischio

Il campo:

```text
risk_level
```

viene utilizzato dal frontend per rappresentare la gravità del risultato.

Valori disponibili:

| Livello | Significato |
|-|-|
| `low` | rischio limitato |
| `medium` | indicatori sospetti |
| `high` | elementi fortemente anomali |
| `critical` | rischio elevato |

Il valore viene utilizzato in:

- badge rischio;
- filtri Cronologia;
- Dashboard;
- statistiche aggregate.

# Repository Layer

L'accesso al database non viene effettuato direttamente dagli endpoint.

L'architettura segue il modello:

```text
API Router
     |
     v
Service Layer
     |
     v
Repository Layer
     |
     v
SQLAlchemy
     |
     v
PostgreSQL
```

Il repository principale è:

```text
app/repositories/sqlalchemy_repository.py
```

# Responsabilità del repository

Il repository gestisce:

- creazione analisi;
- creazione job asincroni;
- recupero analisi;
- paginazione;
- filtri;
- completamento job;
- gestione errori;
- cancellazione dataset.

In questo modo la logica HTTP rimane separata dalla persistenza.

# Creazione di un job asincrono

Quando arriva un upload:

l'API crea un record iniziale nella tabella:

```text
analyses
```

con:

```text
status = queued
```

e informazioni iniziali:

- nome file;
- dimensione;
- percorso storage;
- proprietario.

I campi relativi alla scansione rimangono inizialmente vuoti:

```text
sha256 = null
mime_type = null
verdict = null
```

Saranno valorizzati dal worker.

# Identificativo analisi

Ogni analisi possiede:

```text
sequence_number
```

come progressivo interno del database.

Da questo viene generato l'identificativo pubblico:

```text
ANL-YYYY-NNNN
```

Il progressivo viene assegnato dal database in modo atomico.

Questo evita collisioni quando più repliche API creano analisi contemporaneamente.

# Acquisizione dei job da parte del worker

Il repository implementa il recupero concorrente tramite:

```sql
FOR UPDATE SKIP LOCKED
```

Questo meccanismo è fondamentale per supportare più worker contemporaneamente.

Esempio:

```text
Worker 1
    |
    prende Job A
    


Worker 2
    |
    vede Job A bloccato
    |
    prende Job B
```

Due worker non possono quindi elaborare lo stesso file.

# Transizione verso processing

Quando un worker acquisisce un job:

```text
queued
   |
   v
processing
```

vengono aggiornati:

- worker_id;
- processing_started_at;
- attempt_count;
- timestamp aggiornamento.

Gli eventuali risultati precedenti vengono cancellati per evitare che un retry mostri informazioni parziali.

# Completamento dell'analisi

Quando la pipeline termina:

```text
processing
      |
      v
completed
```

il repository salva:

- MIME type;
- hash SHA-256;
- entropia;
- risultato ClamAV;
- risultato YARA;
- indicatori;
- verdict;
- rischio finale.

Il file temporaneo può quindi essere rimosso dallo storage.

# Gestione dei fault

Il repository supporta anche:

- errori database;
- rollback transazioni;
- retry worker;
- recupero job bloccati.

Un errore durante la scansione non porta automaticamente il file a essere considerato sicuro.

# Modello database

Il database applicativo utilizzato da SecureScan Cloud è PostgreSQL.

L'Analysis API utilizza SQLAlchemy come livello ORM e separa:

- modello applicativo;
- modello di persistenza;
- schema API.

I modelli ORM sono definiti in:

```text
app/db/models.py
```

Le migrazioni dello schema vengono invece gestite tramite:

```text
alembic/
```

# Tabella analyses

La tabella principale del sistema è:

```text
analyses
```

che contiene sia i job asincroni sia i risultati finali delle scansioni.

Le informazioni memorizzate comprendono:

## Identificazione

| Campo | Descrizione |
|-|-|
| `sequence_number` | progressivo interno database |
| `id` | identificativo pubblico analisi |
| `file_name` | nome originale file |

## Ownership

| Campo | Descrizione |
|-|-|
| `owner_sub` | subject Keycloak dell'utente |
| `owner_username` | username associato |

Questi campi permettono di applicare il controllo di accesso basato sull'utente autenticato.

## Stato elaborazione

| Campo | Descrizione |
|-|-|
| `status` | stato corrente analisi |
| `processing_started_at` | momento inizio elaborazione |
| `completed_at` | completamento pipeline |
| `worker_id` | worker che ha preso il job |
| `attempt_count` | numero tentativi |

## Metadati file

Sono memorizzati:

- dimensione;
- MIME type;
- hash SHA-256;
- entropia;
- compatibilità estensione/MIME.

Questi dati vengono prodotti dalla fase di analisi strutturale.

## Risultati antivirus

La tabella contiene:

- stato ClamAV;
- firma rilevata;
- eventuale errore;
- stato YARA;
- regole YARA trovate;
- indicatori prodotti.

# Tabella user_profiles

La tabella:

```text
user_profiles
```

contiene solamente dati applicativi aggiuntivi.

Non vengono salvati:

- password;
- token;
- credenziali.

Sono memorizzati principalmente:

- avatar;
- informazioni locali associate al subject Keycloak.

La separazione permette di mantenere Keycloak come unica fonte per l'identità.

# Heartbeat worker

La tabella:

```text
worker_heartbeats
```

mantiene lo stato dei processi worker.

Sono registrati:

- identificativo worker;
- hostname;
- stato;
- avvio processo;
- ultimo heartbeat.

Queste informazioni permettono di verificare la disponibilità della pipeline asincrona.

# Heartbeat API

La tabella:

```text
api_instance_heartbeats
```

rappresenta lo stato delle repliche API.

Ogni istanza registra:

- `instance_id`;
- hostname;
- stato;
- timestamp ultimo aggiornamento.

Questa informazione supporta:

- alta disponibilità;
- diagnostica;
- monitoraggio repliche.

# Autenticazione e autorizzazione

La gestione dell'identità è affidata a:

```text
Keycloak
```

L'Analysis API non gestisce direttamente:

- registrazione password;
- login;
- sessioni utente.

Il flusso completo è:

```text
Utente
   |
   v
Keycloak Login
   |
   v
JWT Access Token
   |
   v
Frontend
   |
   v
Kong Gateway
   |
   v
Analysis API
```

# Verifica JWT

La verifica viene implementata in:

```text
app/auth/security.py
```

Prima di accettare una richiesta autenticata vengono controllati:

- firma digitale;
- algoritmo;
- issuer;
- audience;
- scadenza;
- subject;
- tipo token.

# Verifica firma tramite JWKS

Keycloak espone pubblicamente le chiavi utilizzate per firmare i token.

L'API recupera:

```text
JSON Web Key Set
```

e utilizza la chiave pubblica corrispondente al parametro:

```text
kid
```

presente nell'header JWT.

La cache locale delle chiavi evita richieste continue verso Keycloak.

# Ruoli applicativi

SecureScan Cloud utilizza due ruoli principali.

# Ruolo analyst

Un utente analyst può:

- caricare file;
- creare analisi;
- consultare la propria cronologia;
- aprire dettagli delle proprie analisi;
- modificare il proprio profilo.

Non può:

- vedere analisi di altri utenti;
- accedere al pannello amministrativo.

# Ruolo admin

Un amministratore può:

- consultare tutte le analisi;
- filtrare per proprietario;
- gestire utenti;
- modificare ruoli;
- eliminare account;
- eseguire operazioni amministrative.

# Profilo utente

Gli endpoint del profilo sono definiti in:

```text
app/api/profile.py
```

Le operazioni disponibili sono:

| Metodo | Endpoint | Funzione |
|-|-|-|
| GET | `/me/profile` | lettura profilo |
| PUT | `/me/profile` | modifica dati |
| POST | `/me/password` | cambio password |
| POST | `/me/avatar` | caricamento avatar |
| DELETE | `/me/avatar` | rimozione avatar |

# Gestione profilo tramite Keycloak

I dati principali dell'identità restano in Keycloak:

- username;
- nome;
- cognome;
- email;
- password;
- ruoli.

PostgreSQL mantiene solo informazioni aggiuntive applicative.

Questa separazione riduce la superficie di attacco del database applicativo.

# Cambio password

Il cambio password viene delegato completamente a Keycloak.

Il backend:

- verifica la richiesta;
- valida i vincoli applicativi;
- comunica con Keycloak;
- non memorizza mai la nuova password.

È possibile richiedere anche la disconnessione delle altre sessioni attive.

# Cambio email

Il cambio email utilizza il meccanismo di verifica Keycloak.

Sono richiesti:

- verifica email abilitata;
- SMTP configurato;
- email corrente verificata.

Il backend non modifica direttamente l'identità senza completare il flusso previsto.

# Amministrazione utenti

Gli endpoint amministrativi sono definiti in:

```text
app/api/admin_users.py
```

Il frontend non comunica direttamente con Keycloak Admin API.

Il flusso è:

```text
Admin UI
    |
    v
Analysis API
    |
    v
Keycloak Admin API
```

# Operazioni amministrative disponibili

| Operazione | Descrizione |
|-|-|
| elenco utenti | visualizzazione utenti registrati |
| modifica ruolo | aggiornamento permessi |
| modifica profilo | aggiornamento dati personali |
| dettaglio utente | statistiche e analisi associate |
| reinvio verifica email | gestione verifica account |
| eliminazione account | rimozione utente |

# Dashboard

Il servizio Dashboard è implementato in:

```text
app/services/dashboard.py
```

La Dashboard non calcola statistiche nel browser.

Il backend produce direttamente aggregazioni dal database.

Sono disponibili:

- numero totale analisi;
- analisi completate;
- analisi in elaborazione;
- analisi fallite;
- distribuzione rischio;
- andamento temporale;
- ultime analisi.

# Stato del sistema e osservabilità

L'Analysis API espone informazioni utilizzate dalla pagina:

```text
Stato del sistema
```

Vengono controllati:

- stato API;
- heartbeat repliche;
- stato worker;
- disponibilità Keycloak;
- disponibilità Kong;
- Prometheus;
- Grafana.

# Metriche Prometheus

L'endpoint:

```http
GET /metrics
```

espone metriche relative a:

- richieste HTTP;
- tempi di risposta;
- errori;
- stato runtime.

Queste informazioni possono essere raccolte da Prometheus e visualizzate tramite Grafana.

# Testing

Il servizio include una suite di test automatizzati:

```text
tests/
```

Le principali categorie sono:

| Test | Obiettivo |
|-|-|
| authentication | verifica JWT e RBAC |
| analyses | gestione analisi |
| repository | accesso dati |
| ownership | isolamento utenti |
| dashboard | aggregazioni |
| profile | gestione profilo |
| metrics | osservabilità |
| system status | health e heartbeat |

I test permettono di verificare sia il comportamento funzionale sia i vincoli di sicurezza.

# Esecuzione locale

L'intero ambiente viene normalmente avviato tramite Docker Compose:

```bash
docker compose \
  --env-file .env \
  -f infrastructure/compose/compose.yaml \
  up -d --build
```

L'Analysis API viene eseguita come servizio containerizzato.

In uno scenario ad alta disponibilità possono essere presenti più repliche:

```text
analysis-api-1
analysis-api-2
```

Il traffico viene distribuito tramite Kong.

# Considerazioni architetturali

L'Analysis API è progettata seguendo alcuni principi fondamentali:

## Separazione delle responsabilità

Il servizio separa:

- API HTTP;
- logica applicativa;
- persistenza;
- autenticazione;
- scansione malware.

## Sicurezza by design

Sono applicati:

- controllo accessi server-side;
- verifica JWT;
- separazione credenziali;
- assenza password locali;
- isolamento worker;
- validazione upload.

## Scalabilità

La separazione tra API e worker permette:

- aumento indipendente delle repliche;
- elaborazione concorrente;
- fault isolation;
- monitoraggio dedicato.

## Alta disponibilità

L'utilizzo di:

- heartbeat;
- repository condiviso;
- acquisizione job concorrente;
- API replicate;

permette di sperimentare scenari di fault tolerance e load balancing.

# Collegamenti utili

- [Documentazione architettura](../../docs/architecture.md)
- [Autenticazione e RBAC](../../docs/authentication-rbac.md)
- [Pipeline malware](../../docs/malware-scanning.md)
- [Request flow](../../docs/request-flow.md)
- [Esperimenti HA](../../docs/experiments.md)