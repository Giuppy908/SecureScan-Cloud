# SecureScan Cloud

SecureScan Cloud è una piattaforma per l'analisi sicura di file sviluppata come progetto per il corso magistrale di Cloud Computing Technologies.

Il progetto nasce con l'obiettivo di studiare in un caso d'uso concreto il ruolo di un API Gateway all'interno di un'architettura composta da più servizi. La piattaforma non si limita quindi a offrire una funzione di scansione dei file: l'architettura è stata progettata per poter osservare e misurare aspetti come autenticazione centralizzata, autorizzazione, load balancing, fault tolerance, elaborazione asincrona e monitoraggio dei componenti.

Il sistema utilizza un frontend React, Keycloak per la gestione dell'identità, Kong come API Gateway, due repliche dell'Analysis API, un worker dedicato all'elaborazione dei file, PostgreSQL per la persistenza dei dati, ClamAV e YARA per la scansione e Prometheus con Grafana per l'osservabilità.

SecureScan Cloud può essere eseguito interamente in locale tramite Docker Compose. Il repository contiene anche una configurazione separata per l'ambiente di produzione, utilizzata per il deployment su una macchina virtuale Microsoft Azure. In produzione l'accesso dall'esterno avviene tramite HTTPS e Caddy svolge il ruolo di reverse proxy davanti ai servizi pubblicamente raggiungibili.

## Obiettivi del progetto

Il caso d'uso scelto è quello di una piattaforma nella quale un utente autenticato può caricare un file, richiederne l'analisi e consultarne successivamente il risultato. Dietro questa operazione apparentemente semplice sono coinvolti componenti distinti, ciascuno con una responsabilità precisa.

L'architettura permette in particolare di studiare:

- il passaggio delle richieste attraverso un API Gateway;
- la distribuzione del traffico tra più repliche dello stesso servizio;
- il comportamento del sistema quando una replica diventa indisponibile;
- il rientro di una replica dopo il ripristino;
- l'autenticazione mediante OpenID Connect e token JWT;
- l'applicazione di RBAC e ownership lato server;
- la separazione tra gestione delle richieste HTTP ed elaborazione asincrona;
- l'integrazione di più strumenti per la scansione dei file;
- la raccolta di metriche e l'osservazione del comportamento dei servizi.

La disponibilità di due repliche dell'Analysis API dietro Kong consente inoltre di effettuare esperimenti riproducibili sul comportamento del gateway, confrontando il funzionamento normale con situazioni di guasto e successivo recovery.

## Architettura

In ambiente locale il percorso principale di una richiesta applicativa è:

```text
          Browser
             |
             v
       Frontend React
             |
             v
      Kong API Gateway
             |
   +---------+---------+
   |                   |
   v                   v
analysis-api-1     analysis-api-2
   |                   |
   +---------+---------+
             |
             v
         PostgreSQL
```

L'autenticazione segue un percorso distinto, perché il frontend comunica con Keycloak per eseguire login, registrazione e gli altri flussi relativi all'identità.

L'elaborazione di un file è invece asincrona:

```text
Upload
  |
  v
Kong
  |
  v
Analysis API
  |
  +----> PostgreSQL
  |
  +----> storage condiviso
              |
              v
       Analysis Worker
          |       |
          v       v
       ClamAV    YARA
          \       /
           \     /
            v   v
          risultato
              |
              v
          PostgreSQL
```

Questa separazione evita di mantenere aperta la richiesta HTTP per tutta la durata della scansione. L'API registra il nuovo lavoro e restituisce immediatamente lo stato iniziale; il worker lo acquisisce successivamente e aggiorna il database quando l'elaborazione è terminata.

Una descrizione più approfondita dei componenti e delle loro relazioni è disponibile in [docs/architecture.md](docs/architecture.md).

## Componenti principali

### Frontend

L'interfaccia è una Single Page Application realizzata con React, Vite e Material UI.

Le pagine principali sono:

- Dashboard;
- Nuova analisi;
- Cronologia;
- Dettaglio analisi;
- Stato del sistema;
- Profilo;
- Modifica profilo;
- Amministrazione;
- Dettaglio utente amministrativo.

Sono presenti anche le viste dedicate agli accessi non autorizzati e alle route inesistenti.

Il frontend non contiene la logica di sicurezza definitiva. Utilizza il ruolo dell'utente per costruire correttamente la navigazione e impedire l'accesso dalla UI alle sezioni non pertinenti, ma ogni autorizzazione rilevante viene nuovamente verificata dall'Analysis API.

### Keycloak

Keycloak è l'Identity and Access Management utilizzato dal progetto.

Gestisce i principali flussi relativi all'identità:

- autenticazione;
- registrazione;
- verifica dell'indirizzo email;
- recupero della password;
- reimpostazione della password;
- sessioni utente;
- ruoli applicativi;
- emissione dei token utilizzati dal frontend.

Il frontend utilizza Authorization Code Flow con PKCE e non conserva le password degli utenti.

Sono definiti due ruoli applicativi principali:

- `analyst`;
- `admin`.

Gli utenti `analyst` utilizzano le funzionalità ordinarie della piattaforma e possono accedere soltanto alle proprie analisi. Gli utenti `admin` dispongono invece delle funzionalità amministrative e di una vista globale dei dati.

Keycloak viene utilizzato anche dalle funzionalità di gestione del profilo. Il database applicativo non conserva le password degli utenti.

### Kong

Kong rappresenta l'API Gateway della piattaforma ed è il punto di ingresso delle richieste dirette all'Analysis API.

In locale il browser non accede direttamente a `analysis-api-1` o `analysis-api-2`. Le richieste vengono inviate a Kong, che le inoltra verso l'upstream composto dalle due repliche.

Il gateway è configurato per gestire:

- routing;
- load balancing round-robin;
- CORS;
- correlation ID;
- rate limiting;
- limite alla dimensione delle richieste;
- metriche Prometheus;
- health check delle repliche;
- retry in caso di problemi di comunicazione con l'upstream.

La presenza del gateway permette di mantenere il frontend indipendente dal numero e dall'identità delle repliche backend.

### Analysis API

L'Analysis API è sviluppata con FastAPI ed è eseguita in due istanze separate:

```text
analysis-api-1
analysis-api-2
```

Entrambe utilizzano lo stesso database PostgreSQL e lo stesso storage persistente dei file.

L'API si occupa della verifica dei token, dell'applicazione delle regole di autorizzazione, della creazione e consultazione delle analisi, della Dashboard, dello Stato del sistema, del Profilo e delle funzionalità amministrative.

Ogni replica mantiene anche un heartbeat applicativo nel database. L'heartbeat consente di distinguere la semplice esistenza di un container dal fatto che l'istanza applicativa stia effettivamente continuando a funzionare.

### Analysis Worker

L'Analysis Worker è separato dalle API HTTP e completa in background le analisi.

Il worker interroga PostgreSQL alla ricerca di job in stato `queued`, li acquisisce e li porta in `processing`. L'acquisizione utilizza `FOR UPDATE SKIP LOCKED`, in modo che più worker possano eventualmente collaborare senza elaborare contemporaneamente lo stesso record.

La gestione dei job comprende anche contatori dei tentativi, timeout, retry limitati e recupero delle elaborazioni rimaste bloccate in stato `processing`.

Il worker mantiene un proprio heartbeat applicativo ed espone metriche Prometheus.

### PostgreSQL

PostgreSQL contiene i dati persistenti dell'applicazione, tra cui:

- analisi;
- profili applicativi;
- heartbeat delle repliche API;
- heartbeat dei worker.

Le credenziali degli utenti non vengono memorizzate nel database applicativo: autenticazione e password restano sotto la responsabilità di Keycloak.

Nel progetto PostgreSQL viene utilizzato anche come base della coda applicativa dei job. Non è stato introdotto un message broker separato come RabbitMQ o Kafka.

### ClamAV e YARA

La pipeline di analisi combina ClamAV e YARA con alcuni controlli strutturali sul file.

ClamAV viene utilizzato per individuare firme antivirus note. YARA applica invece regole che permettono di riconoscere ulteriori pattern di interesse e di associare informazioni più specifiche alle rilevazioni.

I risultati dei due motori vengono aggregati dal worker insieme alle informazioni ottenute dall'analisi strutturale.

### Prometheus e Grafana

Prometheus raccoglie le metriche esposte dai componenti monitorati. Grafana utilizza Prometheus come datasource e presenta queste informazioni attraverso la dashboard `SecureScan Cloud Observability`.

Il monitoraggio tecnico non va confuso con la pagina `Stato del sistema` disponibile nel frontend. Quest'ultima fornisce una vista sintetica dello stato corrente della piattaforma, mentre Grafana permette di osservare serie temporali, distribuzione delle richieste, latenze e comportamento dei componenti durante gli esperimenti.

## Autenticazione, JWT e autorizzazione

Dopo il login, Keycloak rilascia al frontend i token necessari alla sessione. Le chiamate alle API protette includono il bearer token e raggiungono l'Analysis API passando attraverso Kong.

Il backend verifica il JWT utilizzando le chiavi pubbliche fornite da Keycloak tramite JWKS. Tra i controlli effettuati rientrano firma, issuer, audience e scadenza del token.

Dal payload vengono ricavate anche le informazioni necessarie all'applicazione, tra cui il subject dell'utente, lo username e i ruoli presenti in `realm_access.roles`. Il backend gestisce inoltre gli identificatori disponibili per token e sessione, tra cui `jti`, `sid` e, quando necessario, `session_state`.

Il comportamento atteso distingue chiaramente autenticazione e autorizzazione:

- una richiesta priva di credenziali valide viene rifiutata con `401 Unauthorized`;
- un utente autenticato che tenta un'operazione per la quale non possiede il ruolo necessario riceve `403 Forbidden`.

Il frontend applica gli stessi ruoli alla navigazione per offrire un'interfaccia coerente, ma questa logica non sostituisce i controlli server-side.

Per maggiori dettagli: [docs/authentication-rbac.md](docs/authentication-rbac.md).

## Ownership delle analisi

Ogni analisi viene associata all'utente che l'ha creata attraverso `owner_sub` e `owner_username`.

`owner_sub` rappresenta l'identificatore stabile utilizzato per l'applicazione dell'ownership. In questo modo eventuali modifiche allo username non cambiano la proprietà delle analisi già esistenti.

Un utente `analyst` può consultare esclusivamente i propri record. Questo vincolo viene applicato dal backend e non dipende dai filtri mostrati nel browser.

Un `admin` dispone invece dello scope globale previsto per le funzioni amministrative. Lo stesso principio viene applicato alla Cronologia, al Dettaglio analisi e agli aggregati restituiti alla Dashboard.

## Creazione e ciclo di vita di un'analisi

Quando viene caricato un file, il frontend invia una richiesta a:

```text
POST /api/v1/analyses
```

La richiesta attraversa Kong e raggiunge una delle due repliche dell'Analysis API.

L'API valida l'upload, salva il file nello storage condiviso e crea in PostgreSQL un record iniziale con stato `queued`. Il browser non deve aspettare il completamento della scansione.

Il worker acquisisce successivamente il job, imposta lo stato `processing` ed esegue la pipeline. Al termine aggiorna il record con le informazioni ottenute.

Il frontend può effettuare polling del dettaglio durante l'elaborazione, permettendo all'utente di osservare il passaggio dagli stati intermedi al risultato finale.

## Pipeline di scansione

L'analisi comprende tre parti principali.

La prima riguarda le caratteristiche strutturali del file. Vengono ricavate informazioni quali SHA-256, MIME type, estensione, entropia e corrispondenza tra estensione e MIME type.

La seconda parte è affidata a ClamAV, mentre la terza utilizza le regole YARA.

I risultati vengono combinati per produrre un verdict finale. I valori attualmente gestiti sono:

- `clean`;
- `suspicious`;
- `malicious`;
- `scan_error`.

`scan_error` viene utilizzato quando almeno uno dei motori considerati obbligatori non riesce a completare correttamente il proprio lavoro. In questa situazione il sistema evita di classificare come pulito un file che non è stato effettivamente controllato da tutta la pipeline prevista.

Al risultato è associato anche un livello di rischio:

- `Basso`;
- `Medio`;
- `Alto`;
- `Critico`.

La pipeline non costituisce una sandbox di analisi dinamica: i file non vengono eseguiti e non viene effettuata analisi comportamentale.

La logica completa è descritta in [docs/malware-scanning.md](docs/malware-scanning.md).

## Cronologia e paginazione server-side

La Cronologia non scarica tutte le analisi per poi paginarle nel browser. Filtri e paginazione vengono applicati dal backend prima di restituire i risultati.

L'endpoint:

```text
GET /api/v1/analyses
```

supporta i parametri:

```text
page
page_size
search
status
risk
owner
```

Il filtro `owner` è utilizzabile nello scope amministrativo. Per un analyst il backend applica automaticamente l'ownership associata al subject autenticato.

L'ordine logico delle operazioni è:

```text
scope RBAC
    -> filtri
    -> COUNT dei risultati filtrati
    -> ordinamento
    -> OFFSET
    -> LIMIT
```

Il default dell'endpoint backend è `page_size=10`. La Cronologia del frontend sceglie invece esplicitamente `5` elementi come dimensione iniziale della pagina e mette a disposizione le opzioni:

```text
5 / 10 / 20
```

L'interfaccia mostra il range nel formato `X - Y di Z`.

Se nella pagina corrente sono presenti analisi ancora in stato `queued` o `processing`, il polling mantiene la pagina, la dimensione e i filtri selezionati, evitando di riportare l'utente alla configurazione iniziale.

## Dashboard

La Dashboard utilizza dati reali aggregati dal backend.

Il frontend non ricostruisce le statistiche scaricando l'intera Cronologia. L'endpoint dedicato restituisce uno snapshot già coerente con il ruolo e con lo scope dell'utente.

La Dashboard può quindi rappresentare conteggi, distribuzione del rischio, andamento temporale e analisi recenti senza aggirare le regole di ownership.

## Profilo utente

La gestione del profilo coinvolge sia Keycloak sia PostgreSQL.

Keycloak rimane la sorgente delle informazioni relative all'identità e alla sicurezza dell'account. PostgreSQL conserva invece i dati applicativi locali necessari alla piattaforma, come le informazioni associate all'avatar.

Dalla sezione Profilo è possibile consultare le informazioni dell'account. La pagina di modifica permette di aggiornare i dati consentiti, gestire l'avatar e utilizzare i flussi relativi a email e password.

### Cambio dell'indirizzo email

La modifica dell'indirizzo email utilizza un flusso di verifica dedicato.

Quando viene richiesto un nuovo indirizzo, quello corrente non viene sostituito immediatamente. Il nuovo valore resta in attesa di conferma e l'indirizzo precedente continua a essere quello attivo finché l'utente non completa la verifica attraverso il link ricevuto.

Il sistema gestisce anche il reinvio della verifica e controlla i casi in cui l'indirizzo richiesto sia già associato a un altro account.

Il funzionamento dipende dalla disponibilità della verifica email e da una configurazione SMTP valida.

### Cambio password

Un utente autenticato può cambiare la propria password dalla pagina di modifica del profilo.

Prima dell'aggiornamento viene richiesta la password corrente. La nuova password deve rispettare i requisiti configurati e deve essere confermata.

Il frontend esegue controlli preliminari per fornire un feedback immediato, ma il backend effettua comunque le verifiche necessarie e demanda a Keycloak l'effettivo aggiornamento della credenziale.

È disponibile anche l'opzione per disconnettere le altre sessioni attive dopo il cambio della password.

### Avatar

L'avatar viene gestito come dato applicativo. Il backend valida il file ricevuto, lo salva nello storage previsto e mantiene nel profilo il riferimento necessario per recuperarlo.

La sostituzione e la rimozione dell'avatar tengono conto della coerenza tra database e storage, in modo da evitare di lasciare riferimenti non validi o file non più utilizzati.

## Amministrazione

Gli utenti con ruolo `admin` dispongono di una sezione dedicata alla gestione degli utenti.

Le operazioni amministrative non vengono eseguite dal browser direttamente contro le API amministrative di Keycloak. Il frontend comunica con l'Analysis API, che verifica il ruolo e utilizza server-side le funzionalità necessarie di Keycloak.

Questo evita di esporre al browser credenziali o privilegi amministrativi.

La sezione permette di consultare gli utenti gestiti, aprire il relativo dettaglio e visualizzare le analisi associate. Le operazioni disponibili rispettano i vincoli implementati dal backend per evitare modifiche che possano lasciare la piattaforma in uno stato amministrativo non valido.

## Stato del sistema

La pagina `Stato del sistema` presenta una vista applicativa sintetica della salute dei componenti.

L'Analysis API costruisce lo snapshot combinando heartbeat e controlli tecnici. In questo modo la UI può fornire informazioni sullo stato di API, worker, database, gateway, motore antivirus e componenti di monitoring senza richiedere all'utente di consultare direttamente ogni servizio.

Questa vista è pensata per una lettura immediata. L'analisi temporale e diagnostica rimane invece affidata a Prometheus e Grafana.

## Load balancing e fault tolerance

Kong utilizza un upstream composto da:

```text
analysis-api-1:8000
analysis-api-2:8000
```

con algoritmo round-robin.

La configurazione HA validata nel progetto utilizza:

```text
connect_timeout = 500 ms
read_timeout    = 60000 ms
write_timeout   = 60000 ms
retries         = 5
```

Gli active health check vengono eseguiti con intervallo di `1 s`; la configurazione utilizzata negli esperimenti imposta inoltre soglie che permettono di reagire rapidamente alla mancata disponibilità di un target.

Quando entrambe le repliche sono healthy, Kong distribuisce le richieste tra le due istanze. Se una replica smette di rispondere, il gateway può escluderla dal routing e continuare a utilizzare quella rimasta disponibile. Quando la replica viene ripristinata e torna healthy, può essere reinserita nella distribuzione del traffico.

Questa proprietà riguarda il livello gateway/Analysis API e non implica che ogni componente della piattaforma sia replicato. PostgreSQL, Keycloak, worker e altri servizi hanno caratteristiche di disponibilità differenti e non devono essere considerati automaticamente ridondati solo perché il livello API utilizza due repliche.

I dettagli sono disponibili in [docs/high-availability.md](docs/high-availability.md).

## Esperimenti

Il repository contiene una suite dedicata alla valutazione del comportamento del gateway e delle repliche API.

Gli scenari implementati sono:

```text
baseline_two_replicas
single_replica
failover_during_load
recovery_after_restart
```

La baseline osserva il sistema con entrambe le repliche disponibili. Lo scenario `single_replica` permette il confronto con una sola istanza. `failover_during_load` introduce l'indisponibilità di una replica mentre il traffico è in corso. `recovery_after_restart` misura invece il comportamento quando una replica precedentemente assente torna disponibile.

Tra le metriche raccolte rientrano throughput, latenze, error rate, distribuzione delle richieste tra le repliche e tempi di transizione osservati durante fault e recovery.

Nei risultati locali conservati nel repository, la baseline con due repliche ha elaborato `24331` richieste con error rate pari a `0.0`, distribuendole quasi esattamente a metà tra `analysis-api-1` e `analysis-api-2`.

Anche gli scenari di failover e recovery presenti nei risultati finali hanno registrato error rate pari a `0.0`. Questi dati vanno interpretati nel contesto in cui sono stati ottenuti: dimostrano il comportamento osservato durante gli esperimenti eseguiti sullo stack locale e non costituiscono, da soli, una certificazione generale di disponibilità della piattaforma in qualsiasi ambiente.

Metodologia e risultati sono descritti in [docs/experiments.md](docs/experiments.md).

## Osservabilità

Prometheus raccoglie metriche dai principali componenti tecnici dello stack. I target configurati comprendono:

```text
Prometheus
Kong
analysis-api-1
analysis-api-2
analysis-worker
postgres-exporter
```

`postgres-exporter` permette di esporre a Prometheus informazioni relative a PostgreSQL senza utilizzare Grafana per interrogare direttamente il database.

La dashboard Grafana `SecureScan Cloud Observability` consente di osservare, tra le altre informazioni:

- traffico gestito da Kong;
- codici HTTP;
- latenze del gateway e dell'upstream;
- richieste servite dalle singole repliche API;
- disponibilità delle repliche;
- attività del worker;
- job completati e falliti;
- durata delle elaborazioni;
- disponibilità dei target Prometheus;
- stato dell'exporter PostgreSQL.

Queste metriche sono particolarmente utili durante gli esperimenti di load balancing, failover e recovery.

La configurazione è descritta in [docs/observability.md](docs/observability.md).

## Ambienti di esecuzione

Il repository distingue esplicitamente l'ambiente locale dalla configurazione destinata alla produzione.

### Ambiente locale

L'ambiente locale è basato su Docker Compose ed è quello utilizzato per sviluppo, test, dimostrazioni ed esperimenti.

Il file principale è:

```text
infrastructure/compose/compose.yaml
```

Per la demo è disponibile anche:

```text
infrastructure/compose/compose.demo.yaml
```

che viene applicato come overlay al Compose principale.

In locale vengono mantenute deliberatamente alcune caratteristiche adatte allo sviluppo e alla dimostrazione, tra cui URL `localhost`, utenti demo e configurazioni Keycloak non destinate a un servizio Internet-facing.

### Ambiente di produzione

La configurazione di produzione è mantenuta separata da quella locale attraverso:

```text
infrastructure/compose/compose.production.yaml
.env.production.example
scripts/validate-production-env.sh
```

Il progetto è stato distribuito su una macchina virtuale Microsoft Azure. In questo ambiente Caddy gestisce l'ingresso HTTPS e il reverse proxy verso i servizi che devono essere raggiungibili dall'esterno.

La configurazione production introduce vincoli differenti rispetto alla demo locale, tra cui gestione esplicita dei secret, rifiuto dei valori placeholder destinati alla demo, disabilitazione degli utenti demo e configurazione degli URL pubblici.

La presenza del deployment remoto non cambia il ruolo dell'ambiente locale: sviluppo, prove distruttive, fault injection e benchmark vengono mantenuti separati dalla macchina pubblica.

Per evitare modifiche accidentali e consumo non controllato delle risorse cloud, questa documentazione non tratta le operazioni distruttive o di arresto della macchina Azure come normali procedure di demo.

## Avvio locale

### Prerequisiti

Per eseguire l'intero stack è necessario disporre almeno di:

- Docker;
- Docker Compose;
- repository SecureScan Cloud;
- file `.env` locale configurato.

Prima dell'avvio è consigliabile verificare che Docker sia in esecuzione e posizionarsi nella root del repository.

### Avvio ordinario

Lo script previsto per l'avvio dello stack locale è:

```bash
./scripts/start-local.sh
```

Lo script esegue il Compose locale canonico in modalità detached.

L'equivalente comando Docker Compose è:

```bash
docker compose \
  --env-file .env \
  -f infrastructure/compose/compose.yaml \
  up -d
```

Lo script `start-local.sh` utilizza direttamente il Compose base. Non forza una nuova build delle immagini a ogni esecuzione.

Quando è necessario ricostruire le immagini, ad esempio dopo modifiche al codice o ai Dockerfile, è possibile eseguire:

```bash
docker compose \
  --env-file .env \
  -f infrastructure/compose/compose.yaml \
  up -d --build
```

### Avvio della modalità demo

Per utilizzare l'overlay dedicato alla demo locale:

```bash
./scripts/start-demo.sh
```

L'operazione corrisponde all'applicazione congiunta di:

```text
compose.yaml
compose.demo.yaml
```

Anche `start-demo.sh` non forza automaticamente una nuova build.

La modalità demo può introdurre configurazioni utili a rendere più facilmente osservabili alcuni stati dell'applicazione. Non deve essere utilizzata come riferimento per benchmark prestazionali.

## Servizi locali

Con lo stack in esecuzione, i principali endpoint raggiungibili dal Mac sono:

| Componente | Indirizzo locale |
| --- | --- |
| Frontend | `http://localhost:8080` |
| Kong proxy | `http://localhost:8000` |
| Kong Admin API | `http://localhost:8001` |
| Kong status/metrics | `http://localhost:8100` |
| Keycloak | `http://localhost:8180` |
| Grafana | `http://localhost:3000` |
| Prometheus | `http://localhost:9090` |

Le porte esposte in locale sono pensate per sviluppo, diagnostica e demo. La topologia pubblica dell'ambiente production è differente e non deve essere dedotta direttamente da questa tabella.

## Arresto controllato dell'ambiente locale

Per una normale sessione di sviluppo o dopo una demo è preferibile arrestare i container senza eliminare dati e volumi.

Dalla root del repository:

```bash
docker compose \
  --env-file .env \
  -f infrastructure/compose/compose.yaml \
  stop
```

`stop` arresta i container dello stack ma mantiene container, reti e volumi necessari a riprendere successivamente il lavoro.

Se la demo è stata avviata con l'overlay dedicato, è opportuno mantenere la stessa combinazione di file Compose:

```bash
docker compose \
  --env-file .env \
  -f infrastructure/compose/compose.yaml \
  -f infrastructure/compose/compose.demo.yaml \
  stop
```

Quando si desidera rimuovere i container e la rete Compose mantenendo comunque i dati persistenti nei named volume, è possibile utilizzare `down`:

```bash
docker compose \
  --env-file .env \
  -f infrastructure/compose/compose.yaml \
  down
```

Questa operazione è diversa dalla cancellazione dei volumi.

Non utilizzare `down -v` come normale procedura di arresto: l'opzione `-v` rimuove i volumi associati allo stack e può quindi cancellare dati persistenti necessari al progetto.

## Reset delle analisi della demo

Per preparare nuovamente l'ambiente locale senza cancellare account, avatar o configurazioni è disponibile:

```bash
./scripts/reset-demo-analyses.sh
```

Prima di modificare i dati lo script mostra una fotografia dello stato corrente e richiede una conferma esplicita.

È disponibile anche la modalità:

```bash
./scripts/reset-demo-analyses.sh --dry-run
```

che permette di verificare cosa verrebbe interessato senza effettuare modifiche.

Il reset riguarda esclusivamente i record della tabella `analyses` e i file residui nella directory degli upload. Non elimina avatar, profili utenti, heartbeat, configurazioni Keycloak o gli altri volumi dello stack.

Durante la fase distruttiva lo script arresta temporaneamente API e worker che risultavano attivi, evitando race condition con nuove analisi o aggiornamenti concorrenti. Al termine ripristina soltanto i servizi che erano effettivamente in esecuzione prima del reset.

Questo script è destinato all'ambiente locale di sviluppo e demo.

## Persistenza locale

Docker Compose utilizza named volume per i dati che devono sopravvivere al normale arresto dei container.

Tra i volumi definiti nello stack sono presenti quelli relativi a:

- PostgreSQL;
- storage degli upload e degli avatar;
- Keycloak;
- database delle firme ClamAV;
- Prometheus;
- Grafana.

La persistenza è uno dei motivi per cui la normale procedura di arresto non deve rimuovere i volumi.

## Principali script disponibili

Gli script più utili per la gestione e la verifica del progetto sono:

```text
scripts/start-local.sh
scripts/start-demo.sh
scripts/reset-demo-analyses.sh
scripts/validate-production-env.sh
```

Gli strumenti dedicati ai controlli di sicurezza si trovano invece sotto:

```text
security/
```

mentre la suite sperimentale si trova sotto:

```text
experiments/
```

## Struttura del repository

La struttura principale è:

```text
SecureScan-Cloud/
├── apps/
│   ├── analysis-api/
│   ├── analysis-worker/
│   └── frontend/
├── docs/
├── experiments/
├── infrastructure/
│   ├── clamav/
│   ├── compose/
│   ├── grafana/
│   ├── keycloak/
│   ├── kong/
│   ├── postgres-exporter/
│   └── prometheus/
├── scripts/
└── security/
```

`apps/analysis-api` contiene il backend FastAPI e la logica applicativa esposta tramite API.

`apps/analysis-worker` contiene l'elaborazione asincrona e la pipeline di scansione.

`apps/frontend` contiene la SPA React.

`infrastructure` raccoglie la configurazione dei servizi che compongono l'ambiente di esecuzione.

`experiments` contiene scenari, runner e risultati dei benchmark.

`security` raccoglie utility per verificare alcuni comportamenti relativi a RBAC e configurazione Keycloak.

`docs` contiene la documentazione tecnica più approfondita.

## Documentazione

Per approfondire le singole parti del progetto:

- [Architettura](docs/architecture.md)
- [Autenticazione e RBAC](docs/authentication-rbac.md)
- [Flussi end-to-end](docs/request-flow.md)
- [Pipeline malware](docs/malware-scanning.md)
- [High availability e fault tolerance](docs/high-availability.md)
- [Osservabilità](docs/observability.md)
- [Esperimenti e benchmark](docs/experiments.md)
- [Guida alla codebase](docs/codebase-guide.md)

Sono inoltre presenti README specifici all'interno delle directory dei principali componenti.

## Limiti e perimetro del progetto

SecureScan Cloud è un progetto universitario costruito per studiare concretamente tecnologie e proprietà tipiche di un'architettura cloud. Alcune scelte sono quindi intenzionalmente più semplici rispetto a quelle richieste da una piattaforma commerciale su larga scala.

La coda dei job è basata su PostgreSQL e non su un broker dedicato. La pipeline malware esegue analisi statica e scansioni tramite ClamAV e YARA, ma non esegue i file in una sandbox. L'alta disponibilità sperimentata riguarda principalmente Kong e le due repliche dell'Analysis API; non tutti i componenti sono replicati.

I risultati quantitativi conservati nel repository derivano dagli esperimenti effettuati nell'ambiente locale e devono essere interpretati rispetto a tale configurazione.

Questi limiti non sono nascosti dall'architettura ma fanno parte delle scelte progettuali e delimitano con precisione ciò che gli esperimenti svolti permettono effettivamente di dimostrare.