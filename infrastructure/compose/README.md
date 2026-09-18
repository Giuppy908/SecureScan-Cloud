# SecureScan Docker Compose

Questa directory contiene la configurazione Docker Compose utilizzata per assemblare i servizi di SecureScan Cloud. Lo stack locale viene usato durante sviluppo, test, demo ed esperimenti; una configurazione separata viene invece applicata all'ambiente di produzione.

Docker Compose non svolge soltanto il compito di avviare i container. Nel progetto definisce anche le reti interne, i volumi persistenti, le dipendenze di startup, gli health check, le porte esposte sul Mac e parte della configurazione necessaria ai singoli servizi.

## File presenti

I file principali sono:

```text
compose.yaml
compose.demo.yaml
compose.production.yaml
```

`compose.yaml` rappresenta la configurazione di base dello stack ed è il riferimento per l'esecuzione locale ordinaria.

`compose.demo.yaml` è un overlay destinato alla demo. Non sostituisce il file principale, ma viene applicato insieme a esso per modificare soltanto i parametri che devono differire durante una presentazione o una prova manuale.

`compose.production.yaml` contiene invece le differenze necessarie all'ambiente di produzione. Viene mantenuto separato dalla configurazione locale per evitare che impostazioni pensate per Internet, secret reali o hostname pubblici finiscano per condizionare lo sviluppo quotidiano.

## Servizi dello stack

Lo stack comprende i seguenti servizi principali:

```text
postgres
clamav
keycloak
keycloak-runtime-config
upload-storage-init
analysis-api-1
analysis-api-2
kong
analysis-worker
postgres-exporter
prometheus
grafana
frontend
```

Nel deployment di produzione viene aggiunto anche Caddy, utilizzato come reverse proxy HTTPS davanti ai servizi pubblicamente raggiungibili.

### PostgreSQL

`postgres` è il database condiviso dall'Analysis API e dal worker.

Contiene i dati persistenti dell'applicazione, tra cui analisi, profili applicativi e heartbeat. La stessa istanza PostgreSQL ospita anche il database utilizzato da Keycloak nell'ambiente di produzione, pur mantenendo database e credenziali distinti.

Il servizio usa un named volume dedicato e ha restart policy `unless-stopped`.

### ClamAV

`clamav` fornisce il motore antivirus utilizzato dal worker.

Il database delle firme viene mantenuto in un volume persistente, evitando di dover ripartire da zero ogni volta che il container viene ricreato.

Il servizio dispone di un health check e viene raggiunto dagli altri container attraverso la rete Docker, non tramite una porta pensata per l'utente finale.

### Keycloak

`keycloak` gestisce autenticazione, registrazione, verifica email, reset password, ruoli e sessioni.

Nell'ambiente locale viene avviato con configurazioni adatte allo sviluppo. Il realm, il tema personalizzato e gli altri file necessari vengono montati nel container secondo quanto definito dal Compose.

I dati che devono sopravvivere alla ricreazione del container vengono mantenuti nel volume:

```text
securescan-keycloak-data
```

### Keycloak runtime config

`keycloak-runtime-config` è un servizio di configurazione che viene eseguito dopo l'avvio di Keycloak.

Il suo compito è riallineare impostazioni che non conviene affidare esclusivamente al realm JSON versionato, per esempio redirect URI, web origins, configurazione SMTP, secret dei client backend e altre differenze tra ambiente locale e production.

È normale che questo container termini con:

```text
Exited (0)
```

dopo aver completato correttamente il proprio lavoro. Non è un servizio che deve rimanere permanentemente in esecuzione.

### Upload storage init

`upload-storage-init` prepara lo storage condiviso utilizzato da Analysis API e worker.

Anche questo è un servizio one-shot. Una volta completata correttamente l'inizializzazione può risultare:

```text
Exited (0)
```

senza che ciò rappresenti un errore.

Lo stesso volume contiene le directory applicative utilizzate per upload e avatar.

### Analysis API

L'Analysis API viene eseguita in due servizi distinti:

```text
analysis-api-1
analysis-api-2
```

Entrambe le istanze vengono costruite dallo stesso codice sorgente, ma vengono mantenute come servizi Compose separati per permettere a Kong di trattarle come due target distinti.

Ogni replica dispone di:

- connessione allo stesso database PostgreSQL;
- accesso allo storage condiviso;
- health check;
- heartbeat applicativo;
- identificatore di istanza differente.

Le due API non vengono normalmente esposte direttamente al browser. Il traffico applicativo passa attraverso Kong.

### Kong

`kong` è l'API Gateway del progetto.

Riceve le richieste destinate al backend e le inoltra all'upstream composto da:

```text
analysis-api-1:8000
analysis-api-2:8000
```

Kong viene utilizzato per routing, load balancing, CORS, correlation ID, rate limiting, request size limiting, health check e metriche Prometheus.

Nell'ambiente locale vengono esposte anche Admin API e status endpoint, così da poter utilizzare gli strumenti di diagnostica e gli script sperimentali.

### Analysis Worker

`analysis-worker` esegue in background la pipeline di analisi dei file.

Il worker legge i job da PostgreSQL, accede allo stesso volume utilizzato dalle API e comunica con ClamAV. Le regole YARA sono disponibili all'interno del proprio ambiente di esecuzione.

Il servizio espone internamente health e metriche e mantiene inoltre un heartbeat applicativo nel database.

### PostgreSQL exporter

`postgres-exporter` espone metriche PostgreSQL nel formato utilizzato da Prometheus.

Non è necessario pubblicare la sua porta direttamente sul Mac: Prometheus lo raggiunge attraverso la rete Docker.

### Prometheus

`prometheus` raccoglie le metriche dei componenti configurati.

I dati raccolti sono persistenti attraverso il volume:

```text
securescan-prometheus-data
```

Nell'ambiente locale l'interfaccia Prometheus è disponibile sulla porta `9090`.

### Grafana

`grafana` utilizza Prometheus come datasource.

La configurazione del datasource e la dashboard SecureScan vengono provisionate automaticamente dai file presenti nel repository.

I dati persistenti di Grafana vengono salvati nel volume:

```text
securescan-grafana-data
```

### Frontend

`frontend` contiene la build React/Vite servita tramite Nginx.

In locale viene esposto sulla porta `8080`. Le richieste backend utilizzano Kong come API Gateway e Keycloak come Identity Provider.

## Rete Docker

I servizi comunicano attraverso una rete bridge denominata:

```text
securescan-local
```

All'interno di questa rete i container si raggiungono mediante il nome del servizio Compose.

Esempi:

```text
postgres:5432
clamav:3310
keycloak:8080
analysis-api-1:8000
analysis-api-2:8000
kong:8000
prometheus:9090
```

Questi indirizzi sono validi nella rete Docker e non devono essere confusi con `localhost`.

Per un processo in esecuzione nel container `analysis-api-1`, per esempio:

```text
postgres
```

indica il container PostgreSQL.

`localhost` indicherebbe invece lo stesso container `analysis-api-1`.

## Volumi persistenti locali

Lo stack base definisce named volume per i dati che non devono essere persi quando i container vengono arrestati o ricreati.

I principali sono:

```text
securescan-postgres-data
securescan-upload-data
securescan-keycloak-data
securescan-clamav-db
securescan-prometheus-data
securescan-grafana-data
```

Il volume PostgreSQL conserva i database applicativi.

`securescan-upload-data` viene condiviso tra i componenti che devono accedere ai file caricati e agli avatar.

Il volume Keycloak conserva lo stato persistente del servizio. ClamAV mantiene separatamente il proprio database delle firme, mentre Prometheus e Grafana conservano dati e configurazioni necessarie alle rispettive funzioni.

La normale procedura di arresto dello stack non deve cancellare questi volumi.

## Porte dell'ambiente locale

Quando lo stack locale è in esecuzione sono disponibili i seguenti endpoint:

| Componente | Indirizzo |
| --- | --- |
| Frontend | `http://localhost:8080` |
| Kong proxy | `http://localhost:8000` |
| Kong Admin API | `http://localhost:8001` |
| Kong status/metrics | `http://localhost:8100` |
| Keycloak | `http://localhost:8180` |
| Grafana | `http://localhost:3000` |
| Prometheus | `http://localhost:9090` |

Le Analysis API non vengono normalmente utilizzate dal browser attraverso porte dedicate. L'obiettivo è mantenere Kong come punto di ingresso della parte backend.

## File `.env`

L'ambiente locale utilizza un file:

```text
.env
```

nella root del repository.

Il file contiene i valori necessari all'esecuzione locale e non deve essere confuso con:

```text
.env.example
.env.demo.example
.env.production.example
```

I file `*.example` servono come riferimento e possono essere versionati. Il file `.env` reale non deve contenere credenziali che si vogliono pubblicare nel repository.

Prima del primo avvio è necessario verificare che `.env` esista e contenga i valori richiesti dallo stack.

## Primo avvio locale

Dalla root del repository:

```bash
cd /Users/giuseppefavata/Progetti/SecureScan-Cloud
```

Verificare innanzitutto che Docker sia disponibile:

```bash
docker version
docker compose version
```

Per un primo avvio, oppure dopo modifiche che richiedono la ricostruzione delle immagini:

```bash
docker compose \
  --env-file .env \
  -f infrastructure/compose/compose.yaml \
  up -d --build
```

`--build` chiede a Compose di ricostruire le immagini prima di avviare i servizi.

Non è necessario utilizzarlo a ogni avvio se il codice contenuto nelle immagini non è cambiato.

## Avvio locale ordinario

Per una normale sessione di lavoro è disponibile:

```bash
./scripts/start-local.sh
```

Lo script richiama il Compose base in modalità detached.

L'equivalente esplicito è:

```bash
docker compose \
  --env-file .env \
  -f infrastructure/compose/compose.yaml \
  up -d
```

`start-local.sh` non forza una nuova build.

Se sono state modificate applicazioni, Dockerfile o dipendenze incluse nelle immagini, occorre quindi ricostruire esplicitamente i componenti interessati oppure utilizzare `up -d --build`.

## Avvio della demo locale

Per la demo è disponibile:

```bash
./scripts/start-demo.sh
```

Lo script applica insieme:

```text
infrastructure/compose/compose.yaml
infrastructure/compose/compose.demo.yaml
```

L'equivalente esplicito è:

```bash
docker compose \
  --env-file .env \
  -f infrastructure/compose/compose.yaml \
  -f infrastructure/compose/compose.demo.yaml \
  up -d
```

L'overlay demo può modificare parametri che rendono più facilmente osservabili alcuni stati dell'applicazione.

Questo ambiente è pensato per presentazioni e prove manuali. I suoi tempi non devono essere utilizzati automaticamente come riferimento per i benchmark prestazionali.

## Verifica dello stato dopo l'avvio

Dopo l'avvio è consigliabile controllare lo stato dello stack:

```bash
docker compose \
  --env-file .env \
  -f infrastructure/compose/compose.yaml \
  ps
```

Per la demo:

```bash
docker compose \
  --env-file .env \
  -f infrastructure/compose/compose.yaml \
  -f infrastructure/compose/compose.demo.yaml \
  ps
```

I servizi dotati di health check possono attraversare inizialmente lo stato:

```text
starting
```

prima di diventare:

```text
healthy
```

Questo è normale, soprattutto per componenti come Keycloak, PostgreSQL e ClamAV che richiedono un tempo di inizializzazione.

I container one-shot come `upload-storage-init` e `keycloak-runtime-config` possono invece terminare correttamente con codice `0`.

## Controllo dei log

Per osservare i log dell'intero stack locale:

```bash
docker compose \
  --env-file .env \
  -f infrastructure/compose/compose.yaml \
  logs
```

Per seguire l'output in tempo reale:

```bash
docker compose \
  --env-file .env \
  -f infrastructure/compose/compose.yaml \
  logs -f
```

È generalmente più utile limitarsi al servizio che si sta diagnosticando.

Esempio:

```bash
docker compose \
  --env-file .env \
  -f infrastructure/compose/compose.yaml \
  logs -f analysis-worker
```

Oppure:

```bash
docker compose \
  --env-file .env \
  -f infrastructure/compose/compose.yaml \
  logs -f kong
```

L'interruzione di `logs -f` con `Ctrl+C` interrompe soltanto la visualizzazione dei log e non arresta i container.

## Arresto controllato dello stack locale

Per terminare una sessione di sviluppo senza rimuovere container, rete e volumi:

```bash
docker compose \
  --env-file .env \
  -f infrastructure/compose/compose.yaml \
  stop
```

Questa è la procedura consigliata per il normale utilizzo.

I container vengono arrestati, mentre i dati persistenti restano disponibili.

Per riprendere il lavoro:

```bash
docker compose \
  --env-file .env \
  -f infrastructure/compose/compose.yaml \
  start
```

oppure:

```bash
./scripts/start-local.sh
```

## Arresto della modalità demo

Se lo stack è stato avviato utilizzando l'overlay demo, per mantenere la stessa configurazione Compose durante l'arresto utilizzare:

```bash
docker compose \
  --env-file .env \
  -f infrastructure/compose/compose.yaml \
  -f infrastructure/compose/compose.demo.yaml \
  stop
```

Il successivo avvio può essere effettuato nuovamente con:

```bash
./scripts/start-demo.sh
```

## Rimozione dei container mantenendo i dati

Quando si vuole smontare completamente lo stack locale, rimuovendo container e rete Compose ma mantenendo i named volume:

```bash
docker compose \
  --env-file .env \
  -f infrastructure/compose/compose.yaml \
  down
```

L'operazione non equivale a un reset dei dati.

I named volume continuano a esistere e verranno riutilizzati al successivo avvio.

Per la modalità demo:

```bash
docker compose \
  --env-file .env \
  -f infrastructure/compose/compose.yaml \
  -f infrastructure/compose/compose.demo.yaml \
  down
```

## Operazioni da non usare come arresto ordinario

Non utilizzare come normale procedura di spegnimento:

```text
docker compose down -v
docker volume rm ...
docker system prune
```

`down -v` rimuove anche i volumi associati allo stack e può quindi eliminare database, configurazioni o altri dati persistenti.

`docker volume rm` rimuove direttamente i volumi indicati.

`docker system prune` opera invece su risorse Docker a livello più generale e non è necessario per il normale funzionamento di SecureScan Cloud.

Questi comandi non fanno parte della procedura standard di demo.

## Reset controllato delle analisi

Quando si vuole ripulire soltanto la parte relativa alle analisi della demo, senza cancellare utenti, avatar o configurazioni, utilizzare lo script:

```bash
./scripts/reset-demo-analyses.sh
```

Lo script non esegue immediatamente la cancellazione. Mostra prima lo stato corrente e richiede di digitare:

```text
RESET
```

per confermare.

È possibile verificare preventivamente l'operazione con:

```bash
./scripts/reset-demo-analyses.sh --dry-run
```

La modalità dry-run non modifica alcun dato.

Il reset interessa:

```text
tabella analyses
/data/uploads
```

Non vengono cancellati:

```text
/data/avatars
user_profiles
worker_heartbeats
api_instance_heartbeats
alembic_version
configurazione Keycloak
ruoli Keycloak
altri volumi dello stack
```

Per evitare race condition, durante la cancellazione lo script sospende temporaneamente le Analysis API e il worker che risultano in esecuzione. Al termine ripristina soltanto i servizi che erano attivi prima dell'operazione.

Lo script è destinato esclusivamente all'ambiente locale di sviluppo e demo.

## Riavvio di un singolo servizio

Durante lo sviluppo può essere utile intervenire soltanto su un componente.

Per esempio:

```bash
docker compose \
  --env-file .env \
  -f infrastructure/compose/compose.yaml \
  restart analysis-worker
```

Il riavvio non ricostruisce l'immagine.

Se invece il codice incluso nell'immagine è cambiato:

```bash
docker compose \
  --env-file .env \
  -f infrastructure/compose/compose.yaml \
  up -d --build analysis-worker
```

Lo stesso principio vale per frontend, API e altri servizi costruiti localmente.

Durante gli esperimenti HA è possibile che alcuni servizi vengano arrestati intenzionalmente per simulare un fault. Queste operazioni devono essere eseguite soltanto nell'ambiente previsto per l'esperimento.

## Health check e heartbeat

Docker health check e heartbeat applicativo non rappresentano la stessa cosa.

Un health check verifica che un container risponda a un controllo tecnico definito nel Compose.

L'heartbeat delle Analysis API e del worker viene invece aggiornato periodicamente nel database dall'applicazione stessa. Serve a verificare che il processo continui realmente a comunicare e non soltanto che il container esista.

La pagina `Stato del sistema` utilizza queste informazioni insieme ad altri probe.

## Configurazione production

`compose.production.yaml` viene applicato sopra `compose.yaml` nell'ambiente di produzione.

L'overlay modifica gli aspetti che non devono essere condivisi con la demo locale. Tra questi rientrano configurazione Keycloak per un ambiente Internet-facing, secret obbligatori, URL pubblici e limitazione delle porte esposte direttamente dall'host.

La configurazione production introduce anche Caddy, che gestisce HTTPS e reverse proxy per l'applicazione pubblica e per Keycloak.

Il deployment reale utilizza variabili production mantenute fuori dal repository. Il file versionato:

```text
.env.production.example
```

documenta soltanto la struttura prevista e non contiene i secret operativi.

Prima di un utilizzo production la configurazione può essere verificata tramite:

```text
scripts/validate-production-env.sh
```

La gestione operativa del server remoto non viene descritta in questo README. Arresti, ricostruzioni, fault injection e procedure distruttive sono intenzionalmente documentati soltanto per l'ambiente locale, dove non possono provocare interruzioni del servizio pubblico o consumo involontario di risorse cloud.

## Differenza tra locale e produzione

L'ambiente locale è progettato per poter essere manipolato durante sviluppo e demo.

È quindi normale:

- avviare e arrestare i container;
- osservare direttamente Prometheus e Grafana;
- usare Kong Admin API;
- eseguire fault injection controllata;
- ripulire le analisi della demo;
- ricostruire singoli servizi.

L'ambiente production ha invece uno scopo differente. Serve a rendere SecureScan Cloud raggiungibile pubblicamente e deve mantenere persistenza, configurazione e disponibilità.

Le procedure operative usate per sviluppo e test non devono essere trasferite automaticamente alla macchina pubblica.

## Script correlati

Dalla root del repository sono disponibili:

```text
scripts/start-local.sh
scripts/start-demo.sh
scripts/reset-demo-analyses.sh
scripts/validate-production-env.sh
```

`start-local.sh` avvia il Compose base.

`start-demo.sh` avvia il Compose base insieme all'overlay demo.

`reset-demo-analyses.sh` ripulisce in modo controllato le sole analisi locali.

`validate-production-env.sh` verifica che la configurazione production rispetti i vincoli richiesti prima dell'utilizzo.

## Collegamenti

Per una descrizione generale del progetto:

[README principale](../../README.md)

Per la struttura complessiva dei componenti:

[Architettura](../../docs/architecture.md)

Per il comportamento delle due repliche dietro Kong:

[High availability](../../docs/high-availability.md)

Per le metriche:

[Osservabilità](../../docs/observability.md)

Per gli esperimenti:

[Esperimenti e benchmark](../../docs/experiments.md)