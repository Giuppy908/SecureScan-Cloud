# Architettura di SecureScan Cloud

SecureScan Cloud è una piattaforma distribuita per il caricamento e l'analisi sicura di file. Il progetto è stato costruito in modo da separare le responsabilità tra più componenti, così da poter studiare non soltanto il funzionamento applicativo, ma anche proprietà come autenticazione centralizzata, autorizzazione, load balancing, fault tolerance, elaborazione asincrona e osservabilità.

La scelta di un'architettura a più servizi è legata direttamente agli obiettivi del progetto. Il punto centrale non è avere il maggior numero possibile di container, ma isolare funzioni diverse in componenti con responsabilità definite e osservabili.

## Vista logica del sistema

A livello logico il percorso principale delle richieste applicative è:

```text
              Browser
                |
                v
          Frontend React
                |
                v
         Kong API Gateway
                |
   +------------+------------+
   |                         |
   v                         v
analysis-api-1          analysis-api-2
   |                         |
   +------------+------------+
                |
                v
            PostgreSQL
```

L'autenticazione segue invece un percorso separato:

```text
Browser
   |
   v
Frontend
   |
   v
Keycloak
```

Dopo il login, il frontend utilizza il token rilasciato da Keycloak nelle richieste dirette all'Analysis API. Il token attraversa Kong senza essere interpretato come fonte definitiva di autorizzazione: è il backend a verificarne validità e ruoli prima di eseguire l'operazione richiesta.

La pipeline di analisi dei file introduce un ulteriore percorso asincrono:

```text
Frontend
   |
   v
Kong
   |
   v
Analysis API
   |
   +------------------+
   |                  |
   v                  v
PostgreSQL       Storage condiviso
   |                  |
   +---------+--------+
             |
             v
       Analysis Worker
         |        |
         v        v
       ClamAV     YARA
          \        /
           \      /
            v    v
         Risultato
             |
             v
         PostgreSQL
```

Questa separazione permette all'API di registrare rapidamente una nuova analisi senza mantenere aperta la richiesta HTTP per tutta la durata della scansione.

## Componenti principali

### Frontend

Il frontend è una Single Page Application sviluppata con React, Vite e Material UI.

Gestisce la navigazione dell'utente, la visualizzazione dei dati e l'interazione con le API. Le informazioni mostrate nelle pagine principali provengono dai servizi backend reali e non da dataset mock.

Le principali sezioni dell'interfaccia sono:

- Dashboard;
- Nuova analisi;
- Cronologia;
- Dettaglio analisi;
- Stato del sistema;
- Profilo;
- Modifica profilo;
- Amministrazione;
- Dettaglio utente amministrativo.

Il frontend conosce il ruolo dell'utente e adatta di conseguenza la navigazione. Questo comportamento migliora l'esperienza d'uso, ma non costituisce il controllo di sicurezza definitivo: le autorizzazioni vengono sempre verificate nuovamente dal backend.

### Keycloak

Keycloak è il componente responsabile dell'identità.

Gestisce autenticazione, registrazione, verifica email, reset password, sessioni e ruoli applicativi. I token emessi da Keycloak vengono utilizzati dal frontend per autenticare le richieste successive verso l'Analysis API.

Il progetto utilizza il realm:

```text
securescan
```

e ruoli applicativi principali:

```text
analyst
admin
```

Keycloak gestisce anche i flussi utilizzati dalla pagina Profilo per operazioni sensibili quali cambio email e cambio password.

La configurazione non si limita al realm JSON versionato. Un servizio di runtime config applica impostazioni che dipendono dall'ambiente, tra cui redirect URI, web origins, configurazione SMTP e secret dei client backend.

### Kong

Kong è l'API Gateway del progetto.

Il suo compito principale è ricevere il traffico diretto all'Analysis API e inoltrarlo alle repliche backend. Il frontend non deve conoscere direttamente gli indirizzi di `analysis-api-1` e `analysis-api-2`.

L'upstream utilizzato da Kong contiene:

```text
analysis-api-1:8000
analysis-api-2:8000
```

con algoritmo round-robin.

Oltre al load balancing, Kong gestisce routing, CORS, correlation ID, rate limiting, limite alla dimensione delle richieste, health check e metriche Prometheus.

La verifica dei JWT non viene delegata al gateway. Kong inoltra il bearer token e l'Analysis API esegue i controlli necessari lato server.

### Analysis API

L'Analysis API è sviluppata con FastAPI ed è eseguita in due repliche separate:

```text
analysis-api-1
analysis-api-2
```

Le due istanze condividono:

- database PostgreSQL;
- volume degli upload;
- volume degli avatar;
- configurazione applicativa compatibile.

Ogni replica mantiene però un identificatore distinto, che permette di osservare quale istanza abbia gestito una richiesta.

Le responsabilità dell'Analysis API comprendono:

- verifica dei JWT;
- applicazione di RBAC e ownership;
- creazione delle analisi;
- interrogazione della Cronologia;
- recupero del Dettaglio analisi;
- aggregazione dei dati della Dashboard;
- costruzione dello snapshot per Stato del sistema;
- gestione del Profilo;
- funzioni amministrative.

Ogni replica aggiorna inoltre un heartbeat applicativo in PostgreSQL.

### Analysis Worker

L'Analysis Worker completa in background i job creati dall'API.

Il worker interroga PostgreSQL alla ricerca di analisi in stato `queued`. L'acquisizione utilizza `FOR UPDATE SKIP LOCKED`, in modo che più worker possano eventualmente operare sullo stesso database senza elaborare contemporaneamente lo stesso job.

Il ciclo di lavorazione comprende:

```text
queued
  |
  v
processing
  |
  v
pipeline malware
  |
  v
risultato finale
```

Sono previsti anche timeout, contatori dei tentativi, retry limitati e recupero dei job rimasti bloccati in stato `processing`.

Il worker mantiene un heartbeat applicativo separato dai normali health check Docker.

### PostgreSQL

PostgreSQL è il principale livello di persistenza applicativa.

Contiene:

- analisi;
- profili applicativi;
- heartbeat delle API;
- heartbeat dei worker.

Le password degli utenti non vengono memorizzate nel database applicativo. Rimangono sotto la responsabilità di Keycloak.

PostgreSQL svolge anche il ruolo di coda applicativa per i job di analisi. Il progetto non utilizza un message broker esterno come RabbitMQ o Kafka.

### Storage condiviso

Analysis API e worker devono poter accedere agli stessi file.

Gli upload vengono quindi salvati in uno storage persistente condiviso. Anche gli avatar sono mantenuti nello stesso volume applicativo, ma in directory distinte.

I percorsi principali all'interno dei container sono:

```text
/data/uploads
/data/avatars
```

Il database conserva i riferimenti necessari a collegare i record ai file persistiti.

### ClamAV

ClamAV fornisce il motore antivirus della pipeline.

Il worker gli invia i file da controllare e interpreta il risultato della scansione. Il database delle firme ClamAV viene mantenuto in un volume persistente dedicato.

ClamAV viene raggiunto attraverso la rete Docker e non costituisce un endpoint pubblico della piattaforma.

### YARA

YARA viene utilizzato come secondo livello di analisi.

Le regole permettono di individuare pattern di interesse non necessariamente rappresentati dalle sole firme antivirus. I match vengono aggregati insieme ai risultati di ClamAV e ai controlli strutturali.

### Prometheus

Prometheus raccoglie le metriche tecniche esposte dai componenti configurati.

I target principali comprendono:

```text
prometheus
kong
analysis-api-1
analysis-api-2
analysis-worker
postgres-exporter
```

Prometheus conserva serie temporali che permettono di osservare il comportamento del sistema durante normale utilizzo, fault injection e recovery.

### PostgreSQL exporter

`postgres-exporter` espone metriche relative a PostgreSQL nel formato atteso da Prometheus.

Il database non viene interrogato direttamente da Grafana.

Il flusso è:

```text
PostgreSQL
   |
   v
postgres-exporter
   |
   v
Prometheus
   |
   v
Grafana
```

### Grafana

Grafana utilizza Prometheus come datasource.

La dashboard principale del progetto è:

```text
SecureScan Cloud Observability
```

La dashboard viene provisionata automaticamente e viene utilizzata soprattutto per osservare traffico, richieste per replica, latenze, stato dei target e comportamento del worker.

## Autenticazione e autorizzazione

Il login viene delegato a Keycloak.

Il flusso principale è:

```text
Browser
   |
   v
Frontend
   |
   v
Keycloak
   |
   v
JWT
   |
   v
Frontend
   |
   v
Kong
   |
   v
Analysis API
```

Il backend valida il token utilizzando JWKS.

Tra le informazioni ricavate dal JWT rientrano:

```text
sub
preferred_username
realm_access.roles
jti
sid
session_state
```

`sid` viene utilizzato quando disponibile come identificatore della sessione. `session_state` può essere usato come fallback.

I ruoli vengono estratti da:

```text
realm_access.roles
```

Il frontend utilizza queste informazioni per costruire la UI, ma RBAC e ownership vengono applicati lato backend.

## Ownership

Ogni analisi è associata al proprio creatore tramite:

```text
owner_sub
owner_username
```

`owner_sub` è il riferimento principale perché deriva dal subject del token e rimane stabile anche se l'utente modifica lo username.

Per un `analyst`, il backend applica automaticamente lo scope sul proprio `owner_sub`.

Un `admin` può invece utilizzare lo scope globale previsto dalle funzionalità amministrative.

Lo stesso principio viene applicato a Cronologia, Dettaglio analisi e Dashboard.

## Flusso di una nuova analisi

Quando un utente carica un file:

1. il frontend invia `POST /api/v1/analyses`;
2. Kong inoltra la richiesta a una delle due repliche;
3. l'API valida il file;
4. il file viene scritto nello storage condiviso;
5. viene creato un record `queued` in PostgreSQL;
6. la risposta iniziale viene restituita al frontend;
7. il worker acquisisce il job;
8. lo stato passa a `processing`;
9. vengono eseguiti analisi strutturale, ClamAV e YARA;
10. il record viene aggiornato con il risultato finale.

Il frontend può mantenere il polling finché il job non raggiunge uno stato conclusivo.

## Stati e risultati della pipeline

Gli stati principali del job sono:

```text
queued
processing
completed
failed
```

`failed` rappresenta un errore reale di elaborazione o infrastruttura, non un file semplicemente sospetto o anomalo.

Il risultato della pipeline malware utilizza invece verdict distinti:

```text
clean
suspicious
malicious
scan_error
```

Questa distinzione evita di confondere lo stato operativo del job con il risultato della scansione.

Un'analisi può quindi fallire per problemi di pipeline, oppure completarsi correttamente producendo un verdict che descrive il file.

## Cronologia

La Cronologia utilizza paginazione e filtri server-side.

L'API supporta:

```text
page
page_size
search
status
risk
owner
```

Il backend applica prima scope RBAC e filtri, poi calcola il totale, applica ordinamento, offset e limite.

Il frontend utilizza di default `5` elementi per pagina, con opzioni:

```text
5
10
20
```

Il default dell'endpoint backend resta `page_size=10` nel caso in cui il parametro non venga specificato.

Durante il polling delle analisi ancora in corso vengono mantenuti pagina e filtri selezionati.

## Profilo utente

La gestione del profilo coinvolge sia Keycloak sia PostgreSQL.

Keycloak conserva le informazioni identitarie e di sicurezza. PostgreSQL conserva i dati applicativi che non appartengono direttamente all'Identity Provider.

### Modifica dei dati personali

Nome, cognome e username possono essere aggiornati attraverso il backend.

L'Analysis API coordina le modifiche con Keycloak e mantiene coerente la vista restituita al frontend.

### Modifica email

Il cambio dell'indirizzo email utilizza un flusso dedicato.

Il nuovo indirizzo non sostituisce immediatamente quello corrente. Rimane in stato pending e viene attivato soltanto dopo la verifica tramite email.

Questo permette di mantenere valido l'indirizzo precedente finché il nuovo non è stato confermato.

Il sistema impedisce inoltre che venga impostato un indirizzo già utilizzato da un altro account.

### Modifica password

La modifica della password richiede la password corrente.

Il backend utilizza un client Keycloak dedicato alla verifica della credenziale corrente e aggiorna la password soltanto dopo il controllo.

L'utente può scegliere se terminare le altre sessioni attive.

Quando questa opzione è selezionata, il backend identifica la sessione corrente tramite `sid` e termina le altre sessioni dell'utente, preservando quella utilizzata per effettuare la modifica.

### Avatar

Gli avatar sono memorizzati nello storage applicativo e associati al profilo tramite PostgreSQL.

Il sistema gestisce caricamento, sostituzione, recupero e cancellazione mantenendo coerenti database e filesystem.

## Heartbeat e health check

Nel progetto vengono utilizzati due concetti distinti.

Il Docker health check verifica che il servizio risponda a un controllo tecnico.

L'heartbeat applicativo viene invece prodotto direttamente dall'applicazione e scritto periodicamente in PostgreSQL.

Questo vale per:

```text
analysis-api-1
analysis-api-2
analysis-worker
```

La differenza è importante: un container può esistere senza che il processo applicativo continui necessariamente a svolgere il proprio lavoro.

La pagina `Stato del sistema` utilizza heartbeat e probe tecnici per produrre uno snapshot comprensibile all'utente.

## Load balancing

Kong utilizza un upstream statico con due target:

```text
analysis-api-1:8000
analysis-api-2:8000
```

L'algoritmo è round-robin.

Quando entrambe le repliche sono disponibili, il traffico tende quindi a essere distribuito in maniera simmetrica.

La risposta backend contiene anche un identificatore della replica, utilizzabile negli esperimenti per verificare quale istanza abbia servito la richiesta.

## Fault tolerance

La fault tolerance del livello API deriva dall'uso congiunto di:

```text
Kong
+
analysis-api-1
+
analysis-api-2
```

Se una replica diventa indisponibile, Kong può escluderla dal routing e continuare a utilizzare l'altra.

Quando la replica torna disponibile e supera nuovamente gli health check, può essere reinserita nel pool.

Questa proprietà non implica che l'intero sistema disponga di ridondanza completa.

Nella configurazione attuale:

```text
Analysis API     -> 2 repliche
Kong             -> 1 istanza
PostgreSQL       -> 1 istanza
Keycloak         -> 1 istanza
Analysis Worker  -> 1 istanza
VM Azure         -> 1 macchina virtuale
```

Il progetto dimostra quindi in modo diretto la fault tolerance del livello gateway/API, ma non pretende di rappresentare un'architettura multi-region o completamente ridondata.

## Osservabilità

L'osservabilità permette di leggere gli eventi del sistema oltre il semplice stato `up/down`.

Prometheus raccoglie metriche dai target e Grafana le visualizza in forma temporale.

Tra le informazioni osservabili rientrano:

```text
richieste Kong
codici HTTP
latenze
richieste per replica
repliche disponibili
attività worker
job completati
job falliti
durata elaborazione
stato target Prometheus
metriche PostgreSQL
```

Durante gli esperimenti HA queste metriche permettono di confrontare ciò che accade nel gateway con ciò che viene osservato dalle singole applicazioni.

## Architettura locale

L'ambiente locale viene eseguito interamente tramite Docker Compose.

Il file principale è:

```text
infrastructure/compose/compose.yaml
```

La variante demo aggiunge:

```text
infrastructure/compose/compose.demo.yaml
```

I servizi comunicano sulla rete:

```text
securescan-local
```

e possono utilizzare i rispettivi nomi Compose come hostname.

In locale vengono esposte porte aggiuntive utili a sviluppo e diagnostica, come Kong Admin API, Prometheus e Grafana.

## Deployment production

SecureScan Cloud è stato distribuito anche su una macchina virtuale Microsoft Azure.

La configurazione production utilizza:

```text
compose.yaml
compose.production.yaml
```

e mantiene i valori operativi sensibili in una configurazione esterna al repository.

Il deployment production introduce Caddy come reverse proxy e terminatore TLS.

La vista semplificata dell'ingresso pubblico è:

```text
                         Internet
                            |
                            v
                          Caddy
                            |
              +-------------+-------------+
              |                           |
              v                           v
    hostname applicazione        hostname autenticazione
              |                           |
      +-------+-------+                   |
      |               |                   |
      v               v                   v
   Frontend          Kong              Keycloak
                      |
              +-------+-------+
              |               |
              v               v
        analysis-api-1   analysis-api-2
```

Sul dominio principale Caddy serve il frontend e inoltra le richieste `/api/*` verso Kong.

Keycloak viene invece pubblicato tramite un hostname dedicato.

Questa separazione rende più chiari issuer, redirect URI e flow OIDC senza esporre direttamente le porte interne dei container.

## Caddy

Caddy viene utilizzato soltanto nel deployment production.

Le sue responsabilità principali sono:

- esposizione HTTP/HTTPS;
- gestione TLS;
- reverse proxy verso frontend;
- reverse proxy verso Kong per le route applicative;
- reverse proxy verso Keycloak sul relativo hostname.

I certificati e lo stato ACME vengono mantenuti in volumi persistenti dedicati.

Caddy non sostituisce Kong.

I due componenti operano su livelli differenti:

```text
Caddy
  -> ingresso HTTPS e reverse proxy pubblico

Kong
  -> API Gateway applicativo, routing, load balancing e policy API
```

## Persistenza in production

La ricreazione di un container non deve comportare la perdita dei dati persistenti.

Nel deployment Azure vengono utilizzati volumi dedicati per:

```text
PostgreSQL
upload e avatar
Keycloak
database firme ClamAV
Prometheus
Grafana
Caddy data
Caddy config
```

In questo modo codice e container possono essere aggiornati separatamente dallo stato persistente.

La configurazione production e i secret operativi non vengono mantenuti nel repository Git.

## Separazione tra sviluppo e produzione

Lo sviluppo, la fault injection e gli esperimenti vengono svolti prevalentemente nell'ambiente locale.

La VM pubblica viene invece utilizzata per verificare che l'architettura possa essere distribuita su Internet con configurazione production, HTTPS e persistenza reale.

Questa separazione è intenzionale.

Operazioni come arresto di repliche, failure injection o reset dei dati sono adatte all'ambiente locale controllato e non devono essere trasferite automaticamente al server pubblico.

## Limiti architetturali

L'architettura è stata progettata per gli obiettivi del progetto e non per sostituire una piattaforma commerciale completamente ridondata.

I principali limiti attuali sono:

- un'unica VM Azure;
- una sola istanza PostgreSQL;
- una sola istanza Keycloak;
- un solo Kong;
- un solo worker;
- target Kong statici;
- assenza di service discovery dinamica;
- assenza di broker di messaggi dedicato;
- assenza di sandbox per analisi dinamica dei file.

Le due repliche dell'Analysis API permettono comunque di studiare in modo concreto load balancing, failover e recovery senza introdurre complessità non necessaria rispetto agli obiettivi dell'esame.

## Documenti correlati

Per approfondire i singoli aspetti:

- [Autenticazione e RBAC](authentication-rbac.md)
- [Flussi end-to-end](request-flow.md)
- [Malware scanning](malware-scanning.md)
- [High availability](high-availability.md)
- [Osservabilità](observability.md)
- [Esperimenti e benchmark](experiments.md)
- [Guida alla codebase](codebase-guide.md)