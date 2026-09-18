# SecureScan Kong Gateway

Kong è il componente che implementa il livello API Gateway all'interno dell'architettura SecureScan Cloud.

Il suo compito principale è fornire un punto unico di ingresso per le richieste provenienti dal frontend, applicando controlli e funzionalità trasversali prima di inoltrare il traffico verso i servizi backend.

Nel progetto Kong viene utilizzato principalmente per:

- routing delle richieste HTTP;
- bilanciamento del traffico tra più repliche dell'Analysis API;
- gestione degli header applicativi;
- configurazione CORS;
- identificazione delle richieste tramite correlation ID;
- limitazione del traffico;
- controllo delle dimensioni delle richieste;
- esposizione delle metriche per Prometheus;
- gestione dei controlli di disponibilità dei servizi upstream.

Kong rappresenta quindi il punto centrale dell'architettura per ottenere maggiore disponibilità, osservabilità e separazione tra frontend e servizi applicativi interni.

## Ruolo nell'architettura SecureScan Cloud

Il frontend non comunica direttamente con le istanze dell'Analysis API.

Il percorso delle richieste applicative è:

```text
Frontend
    |
    v
Kong API Gateway
    |
    v
analysis-api-1
analysis-api-2
```

Il browser conosce solamente l'endpoint pubblico esposto da Kong.

Le repliche backend rimangono invece componenti interni della rete Docker e non vengono pubblicate direttamente.

Questa separazione permette di:

- nascondere la topologia interna dei servizi;
- centralizzare le configurazioni comuni;
- distribuire il traffico tra più istanze;
- applicare policy uniformi;
- sostituire o scalare le repliche backend senza modificare il frontend.

## Alta disponibilità tramite load balancing

Uno degli obiettivi principali dell'utilizzo di Kong è simulare un'architettura backend ad alta disponibilità.

SecureScan Cloud utilizza due repliche indipendenti della Analysis API:

```text
analysis-api-1:8000
analysis-api-2:8000
```

Entrambe le istanze:

- eseguono lo stesso codice applicativo;
- utilizzano lo stesso database PostgreSQL;
- condividono lo storage applicativo;
- espongono gli stessi endpoint;
- vengono monitorate tramite health check e heartbeat.

Kong mantiene un upstream composto da entrambe le repliche e distribuisce le richieste secondo algoritmo:

```text
round-robin
```

Il traffico viene quindi alternato tra le istanze disponibili.

In caso di indisponibilità di una replica, Kong può rimuoverla temporaneamente dal bilanciamento e continuare a inoltrare le richieste verso il nodo funzionante.

Questo comportamento permette di dimostrare:

- fault tolerance;
- continuità del servizio;
- distribuzione del carico;
- recupero automatico dopo un errore.

## Endpoint disponibili nell'ambiente locale

Nello sviluppo locale Kong espone diversi endpoint:

```text
Proxy API:
http://localhost:8000

Admin API:
http://localhost:8001

Status e metriche:
http://localhost:8100
```

### Proxy API

La porta `8000` rappresenta il punto di ingresso utilizzato dal frontend.

Le richieste applicative vengono inoltrate alle Analysis API attraverso questa porta.

Esempio:

```text
Frontend
    |
    v
http://localhost:8000/api/v1/analyses
    |
    v
Analysis API
```

### Admin API

La porta `8001` espone l'interfaccia amministrativa di Kong.

Viene utilizzata principalmente per:

- diagnostica;
- verifica della configurazione;
- controllo degli upstream;
- esperimenti locali.

Nell'ambiente production non viene resa pubblicamente disponibile.

### Status endpoint

La porta `8100` espone endpoint utilizzati per:

- health check;
- metriche;
- monitoraggio dello stato interno.

Questi endpoint vengono utilizzati anche dai sistemi di osservabilità.

## Configurazione degli upstream

L'upstream principale gestito da Kong è costituito dalle due repliche dell'Analysis API.

Target configurati:

```text
analysis-api-1:8000
analysis-api-2:8000
```

La distribuzione delle richieste utilizza:

```text
Algorithm:
round-robin
```

Ogni target dispone di controlli di disponibilità che permettono a Kong di valutare se una replica è ancora utilizzabile.

## Health check e gestione dei fault

Kong utilizza due tipologie di controllo:

### Active health check

Gli active health check inviano periodicamente richieste ai servizi backend per verificare la loro disponibilità.

Nel progetto sono configurati con:

```text
interval = 1 secondo
```

Questo permette di rilevare rapidamente un servizio non disponibile.

### Passive health check

I passive health check osservano il comportamento delle richieste reali.

Se un upstream produce errori consecutivi oltre la soglia configurata, Kong può considerarlo temporaneamente non disponibile.

Parametri principali:

```text
retries = 5

unhealthy threshold = 1
```

Questa configurazione consente di reagire rapidamente a problemi delle repliche.

## Timeout e resilienza delle richieste

Per evitare che una singola richiesta rimanga bloccata indefinitamente, Kong applica timeout specifici.

Configurazione utilizzata:

```text
connect_timeout = 500 ms

read_timeout = 60000 ms

write_timeout = 60000 ms
```

I timeout consentono di:

- evitare connessioni pendenti;
- liberare risorse inutilizzate;
- mantenere stabile il gateway durante condizioni anomale.

## Plugin Kong utilizzati

SecureScan utilizza diversi plugin Kong per aggiungere funzionalità trasversali.

## CORS

Il plugin CORS gestisce le richieste provenienti dal frontend.

Permette di:

- autorizzare le origin previste;
- controllare gli header consentiti;
- gestire richieste preflight HTTP OPTIONS.

Il controllo CORS facilita la comunicazione tra frontend React e backend senza spostare questa logica nelle singole API.

## Correlation ID

Il plugin correlation ID assegna un identificativo univoco alle richieste.

Questo permette di:

- correlare richieste tra gateway e backend;
- semplificare il troubleshooting;
- migliorare l'analisi dei log.

## Rate limiting

Il plugin rate limiting permette di limitare il numero di richieste ricevute dal gateway.

Lo scopo è:

- prevenire abusi;
- proteggere i servizi backend;
- evitare sovraccarichi accidentali.

Il rate limiting non sostituisce i controlli di autenticazione e autorizzazione.

## Request size limiting

Il plugin request size limiting controlla la dimensione massima delle richieste HTTP.

Nel contesto SecureScan è importante perché il sistema gestisce caricamento di file.

Questo controllo impedisce che richieste eccessivamente grandi raggiungano inutilmente i servizi applicativi.

## Prometheus

Il plugin Prometheus espone metriche relative al traffico gestito da Kong.

Le informazioni raccolte includono:

- richieste ricevute;
- latenza;
- codici HTTP;
- stato degli upstream;
- errori.

Le metriche vengono raccolte da Prometheus e visualizzate tramite Grafana.

## Gestione dell'autenticazione

Kong inoltra il token JWT ricevuto dal frontend verso l'Analysis API.

Il gateway non rappresenta il punto finale della verifica delle autorizzazioni applicative.

La validazione completa rimane responsabilità del backend.

L'Analysis API verifica:

- firma del token;
- issuer;
- audience;
- ruoli associati all'utente.

Questa scelta evita di concentrare tutta la sicurezza nel gateway e mantiene il controllo delle autorizzazioni vicino alla logica applicativa.

## Configurazione tramite template

La configurazione Kong non viene mantenuta come file statico finale.

Il repository contiene un template:

```text
kong.template.yaml
```

che viene trasformato nella configurazione effettiva tramite:

```text
render-config.sh
```

Questo approccio permette di:

- separare configurazione e valori runtime;
- utilizzare ambienti differenti;
- evitare configurazioni duplicate;
- gestire facilmente locale e produzione.

## Validazione della configurazione

Prima dell'avvio di Kong è disponibile lo script:

```text
validate-config.sh
```

Lo script verifica che la configurazione generata sia corretta.

La validazione riduce il rischio di errori di sintassi o configurazioni incomplete prima dell'avvio del gateway.

## File principali

La directory contiene:

```text
kong.template.yaml
```

Template principale della configurazione Kong.

```text
render-config.sh
```

Script utilizzato per generare la configurazione runtime.

```text
validate-config.sh
```

Script per verificare la validità della configurazione.

## Differenza tra ambiente locale e produzione

Nell'ambiente locale Kong espone:

```text
8000
8001
8100
```

per permettere sviluppo, diagnostica ed esperimenti.

Nell'ambiente production Kong viene mantenuto dietro Caddy.

Il traffico pubblico arriva quindi attraverso:

```text
Internet
    |
    v
Caddy HTTPS Reverse Proxy
    |
    v
Kong
    |
    v
Analysis API
```

In produzione:

- la proxy port interna non viene pubblicata direttamente;
- la Admin API resta accessibile solamente localmente;
- il gateway viene protetto dal reverse proxy HTTPS.

## Integrazione con gli esperimenti HA

Kong è il componente principale utilizzato negli esperimenti di alta disponibilità.

Gli esperimenti valutano:

- distribuzione del traffico tra due repliche API;
- comportamento durante il fault di una replica;
- recupero dopo il ripristino del servizio;
- mantenimento della disponibilità del sistema.

La presenza di Kong permette di simulare un ambiente distribuito realistico senza modificare il frontend o la logica applicativa.

## Collegamenti documentazione

Per la descrizione generale dell'architettura:

[Architettura](../../docs/architecture.md)

Per il comportamento delle repliche e gli esperimenti:

[High availability](../../docs/high-availability.md)

Per il flusso completo delle richieste:

[Request flow](../../docs/request-flow.md)

Per monitoraggio e metriche:

[Osservabilità](../../docs/observability.md)