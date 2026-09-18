# Guida alla codebase

La repository di SecureScan Cloud è organizzata per separare chiaramente i diversi livelli che compongono l'architettura applicativa: componenti frontend, servizi backend, infrastruttura cloud-native, strumenti di sicurezza, esperimenti e documentazione tecnica.

Questa guida ha lo scopo di fornire una visione generale della struttura del progetto e di indicare dove sono implementate le principali funzionalità.

Il documento non sostituisce la documentazione architetturale dei singoli componenti, ma rappresenta una mappa pratica per orientarsi nel codice e individuare rapidamente le parti interessate da una modifica o da un'attività di analisi.

La struttura segue il principio di separazione delle responsabilità adottato nell'architettura:

- il frontend gestisce l'interazione con l'utente;
- l'Analysis API espone le funzionalità applicative principali;
- l'Analysis Worker esegue le elaborazioni asincrone;
- l'infrastruttura definisce gateway, autenticazione, monitoring e servizi di supporto;
- gli esperimenti consentono di valutare il comportamento dell'architettura distribuita.

## Struttura generale del repository

La struttura principale è organizzata nel seguente modo:

```text
SecureScan-Cloud/
|
├── apps/
├── infrastructure/
├── experiments/
├── scripts/
├── security/
├── docs/
└── README.md
```

## Directory `apps/`

La directory `apps/` contiene i componenti applicativi principali della piattaforma.

È suddivisa in tre servizi indipendenti:

```text
apps/
├── analysis-api/
├── analysis-worker/
└── frontend/
```

Questa separazione riflette il modello distribuito adottato dal progetto, dove gestione delle richieste, interfaccia utente ed elaborazione dei file vengono mantenute come responsabilità separate.

# Frontend

## `apps/frontend/`

Il frontend implementa l'interfaccia web di SecureScan Cloud.

La tecnologia utilizzata è:

- React;
- Vite;
- Material UI.

Il frontend si occupa principalmente di:

- autenticazione tramite Keycloak;
- gestione delle pagine applicative;
- visualizzazione dello stato delle analisi;
- consultazione dei risultati;
- amministrazione utenti;
- visualizzazione delle metriche applicative.

La struttura principale è:

```text
src/
├── api/
├── auth/
├── components/
├── layout/
├── pages/
└── types/
```

## Pages

Le principali pagine applicative sono organizzate nella directory:

```text
apps/frontend/src/pages/
```

Tra le principali:

### Dashboard

File principale:

```text
DashboardPage.tsx
```

Gestisce:

- indicatori sintetici;
- distribuzione del rischio;
- riepilogo delle analisi;
- informazioni aggregate.

### Nuova analisi

File:

```text
NewAnalysisPage.tsx
```

Gestisce il caricamento dei file e l'avvio del processo di analisi.

### Cronologia

File:

```text
HistoryPage.tsx
```

Permette di consultare le analisi effettuate attraverso:

- filtri;
- ricerca;
- paginazione;
- stato;
- livello di rischio.

### Dettaglio analisi

File:

```text
AnalysisDetailPage.tsx
```

Visualizza:

- metadati del file;
- indicatori strutturali;
- risultati ClamAV;
- risultati YARA;
- verdict finale.

### Stato del sistema

File:

```text
SystemStatusPage.tsx
```

Mostra una vista applicativa dello stato dei servizi.

## Layer API frontend

Le chiamate verso il backend sono centralizzate in:

```text
apps/frontend/src/api/
```

Questo livello mantiene separata la logica di comunicazione HTTP dalla presentazione grafica.

## Autenticazione frontend

La configurazione Keycloak è contenuta in:

```text
apps/frontend/src/auth/
```

Questa parte gestisce:

- inizializzazione del client OpenID Connect;
- gestione del token JWT;
- informazioni relative all'utente autenticato.

# Analysis API

## `apps/analysis-api/`

L'Analysis API rappresenta il backend principale della piattaforma.

È sviluppata con:

- FastAPI;
- SQLAlchemy;
- PostgreSQL.

Il servizio espone le API utilizzate dal frontend e coordina la creazione e consultazione delle analisi.

La struttura principale è:

```text
app/
├── api/
├── auth/
├── models/
├── repositories/
└── services/
```

## API layer

Directory:

```text
app/api/
```

Contiene gli endpoint REST.

Esempi:

```text
analyses.py
dashboard.py
profile.py
system_status.py
admin_users.py
```

Questi moduli gestiscono:

- upload file;
- consultazione analisi;
- dashboard;
- profilo utente;
- amministrazione.

## Modelli dati

Directory:

```text
app/models/
```

Contiene le rappresentazioni applicative delle entità persistenti.

Il modello principale è quello relativo alle analisi dei file.

## Repository layer

Directory:

```text
app/repositories/
```

Implementa l'accesso ai dati.

Il repository layer permette di separare:

- logica applicativa;
- persistenza su database.

Sono presenti implementazioni dedicate sia alla persistenza reale tramite SQLAlchemy sia a scenari di test.

## Service layer

Directory:

```text
app/services/
```

Contiene la logica applicativa.

Esempi:

- gestione dashboard;
- gestione profilo;
- storage dei file;
- integrazione con servizi esterni.

## Autenticazione backend

Directory:

```text
app/auth/
```

Gestisce:

- validazione JWT;
- verifica identità utente;
- controllo dei ruoli.

Il backend utilizza Keycloak come Identity Provider tramite OpenID Connect.

# Analysis Worker

## `apps/analysis-worker/`

L'Analysis Worker esegue le elaborazioni asincrone della piattaforma.

La separazione dal backend permette di evitare che operazioni potenzialmente lunghe, come la scansione malware, blocchino il servizio API.

Le responsabilità principali sono:

- acquisizione dei job;
- aggiornamento dello stato dell'analisi;
- analisi strutturale;
- scansione ClamAV;
- scansione YARA;
- aggregazione risultato finale.

La struttura comprende:

```text
app/
├── repositories/
└── services/
```

## Pipeline malware

Le principali componenti sono:

```text
file_analyzer.py
clamav_client.py
yara_scanner.py
malware_pipeline.py
worker.py
```

Questi moduli implementano il flusso completo di analisi.

Le regole YARA sono contenute in:

```text
apps/analysis-worker/rules/
```

# Database e persistenza

SecureScan Cloud utilizza PostgreSQL come database applicativo.

Il database viene utilizzato per:

- memorizzare utenti e configurazioni applicative;
- salvare analisi;
- mantenere lo stato dei job;
- conservare risultati prodotti dalla pipeline.

Le migrazioni del database sono gestite tramite:

```text
apps/analysis-api/alembic/
```

# Directory `infrastructure/`

La directory `infrastructure/` contiene le configurazioni necessarie per eseguire lo stack distribuito.

Struttura principale:

```text
infrastructure/
├── caddy/
├── clamav/
├── compose/
├── grafana/
├── keycloak/
├── kong/
├── postgres/
├── postgres-exporter/
└── prometheus/
```

# Docker Compose

Directory:

```text
infrastructure/compose/
```

Contiene le configurazioni di deployment tramite Docker Compose:

```text
compose.yaml
compose.demo.yaml
compose.production.yaml
```

Le configurazioni permettono di separare:

- ambiente locale;
- ambiente demo;
- configurazione predisposta per produzione.

# Kong API Gateway

Directory:

```text
infrastructure/kong/
```

Contiene:

```text
kong.template.yaml
render-config.sh
validate-config.sh
```

Kong rappresenta il punto centrale di ingresso delle richieste verso le repliche dell'Analysis API.

La configurazione comprende:

- routing;
- upstream;
- health check;
- bilanciamento del traffico.

# Keycloak

Directory:

```text
infrastructure/keycloak/
```

Contiene la configurazione dell'Identity Provider.

Sono presenti:

```text
realm-securescan.json
Dockerfile
apply_runtime_config.py
```

Questi file gestiscono:

- realm;
- utenti e ruoli;
- configurazione runtime.

# Monitoring

La parte di osservabilità è organizzata in:

```text
infrastructure/prometheus/
infrastructure/grafana/
infrastructure/postgres-exporter/
```

Prometheus raccoglie metriche dai servizi.

Grafana fornisce dashboard per la visualizzazione.

Postgres exporter espone metriche relative al database.

# ClamAV

Directory:

```text
infrastructure/clamav/
```

Contiene la configurazione del servizio antivirus.

Il componente viene utilizzato dall'Analysis Worker durante la pipeline malware.

# Caddy

Directory:

```text
infrastructure/caddy/
```

Contiene:

```text
Caddyfile
```

La configurazione è predisposta per la gestione del reverse proxy nello scenario di deployment.

# Esperimenti

Directory:

```text
experiments/
```

Contiene gli strumenti utilizzati per la valutazione sperimentale dell'architettura.

Struttura:

```text
experiments/
├── scenarios/
├── scripts/
└── results/
```

## Scenari

Directory:

```text
experiments/scenarios/
```

Contiene:

- baseline_two_replicas;
- single_replica;
- failover_during_load;
- recovery_after_restart.

## Script

Directory:

```text
experiments/scripts/
```

Contiene il runner:

```text
run_experiments.py
```

utilizzato per automatizzare l'esecuzione dei benchmark.

## Risultati

Directory:

```text
experiments/results/
```

Contiene gli output generati dagli esperimenti.

# Script operativi

La directory:

```text
scripts/
```

contiene procedure operative.

Principali script:

```text
start-local.sh
```

Avvio ambiente locale.

```text
start-demo.sh
```

Preparazione ambiente demo.

```text
reset-demo-analyses.sh
```

Reset dei dati demo.

```text
validate-production-env.sh
```

Validazione configurazione production.

# Security

Directory:

```text
security/
```

Contiene strumenti di verifica relativi alla sicurezza applicativa.

Sono presenti:

```text
check_keycloak_self_service.py
demo_rbac.py
```

utilizzati per validare configurazioni relative a:

- autenticazione;
- ruoli;
- comportamento RBAC.

# Configurazioni ambiente

I principali file di riferimento sono:

```text
.env.example
.env.demo.example
.env.production.example
```

Questi file definiscono le variabili necessarie per configurare i diversi ambienti senza includere valori sensibili direttamente nel repository.

# Percorso consigliato di esplorazione

Per comprendere progressivamente il progetto è consigliato seguire questo ordine:

1. `README.md`
2. `docs/architecture.md`
3. `docs/request-flow.md`
4. `docs/authentication-rbac.md`
5. `apps/frontend/src/App.tsx`
6. `apps/frontend/src/layout/AppShell.tsx`
7. `apps/analysis-api/app/api/analyses.py`
8. `apps/analysis-worker/app/services/worker.py`
9. `docs/high-availability.md`
10. `docs/observability.md`
11. `docs/experiments.md`

# Collegamento tra codice e documentazione

Ogni componente principale della codebase dispone di una documentazione dedicata:

| Area | Documento |
|---|---|
| Architettura generale | `docs/architecture.md` |
| Flusso richieste | `docs/request-flow.md` |
| Autenticazione e ruoli | `docs/authentication-rbac.md` |
| Alta disponibilità | `docs/high-availability.md` |
| Esperimenti | `docs/experiments.md` |
| Monitoring | `docs/observability.md` |
| Analisi malware | `docs/malware-scanning.md` |

Questa suddivisione permette di mantenere separati il livello implementativo e quello descrittivo, mantenendo però un collegamento diretto tra codice e documentazione tecnica.