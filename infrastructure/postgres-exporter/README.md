# SecureScan PostgreSQL Exporter

`postgres-exporter` è il componente che permette di esporre metriche tecniche relative a PostgreSQL nel formato compatibile con Prometheus.

All'interno dell'architettura SecureScan Cloud viene utilizzato per integrare il database applicativo nel sistema di osservabilità.

Il componente non modifica il comportamento del database e non partecipa alla logica applicativa. Il suo unico compito è leggere informazioni statistiche da PostgreSQL e renderle disponibili ai sistemi di monitoraggio.

## Ruolo nell'architettura SecureScan Cloud

PostgreSQL non viene interrogato direttamente da Grafana o Prometheus.

Il flusso corretto delle metriche è:

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

Questa separazione permette di:

- mantenere isolato il database applicativo;
- evitare accessi diretti da parte dei sistemi di visualizzazione;
- utilizzare il formato standard Prometheus;
- integrare PostgreSQL nello stesso sistema di monitoraggio degli altri servizi.

## Funzionamento

`postgres-exporter` si collega al database PostgreSQL utilizzando una connessione dedicata.

Periodicamente raccoglie informazioni tecniche relative allo stato del database e le converte in metriche Prometheus.

Prometheus esegue successivamente lo scraping dell'endpoint:

```text
http://postgres-exporter:9187/metrics
```

Le metriche vengono quindi rese disponibili a Grafana per la visualizzazione.

## Metriche monitorate

Le metriche PostgreSQL permettono di osservare aspetti operativi del database.

Tra le informazioni disponibili:

- stato del database;
- numero di connessioni;
- attività delle sessioni;
- utilizzo delle risorse;
- informazioni sulle transazioni;
- statistiche operative delle tabelle;
- comportamento generale dell'istanza PostgreSQL.

Questi dati sono utili per individuare eventuali problemi di disponibilità o sovraccarico.

## Integrazione con Prometheus

Prometheus considera `postgres-exporter` come uno dei target monitorati.

Il target configurato nello stack è:

```text
postgres-exporter:9187
```

Il servizio viene raggiunto attraverso la rete Docker interna.

Non è necessario pubblicare la porta direttamente sull'host perché solamente Prometheus deve accedere all'endpoint delle metriche.

## Integrazione con Grafana

Grafana utilizza le metriche raccolte da Prometheus per costruire dashboard di osservabilità.

Le informazioni provenienti da PostgreSQL possono essere utilizzate insieme a quelle degli altri componenti:

- Kong;
- Analysis API;
- Analysis Worker;
- servizi infrastrutturali.

Questo permette una visione complessiva dello stato della piattaforma.

## Sicurezza e isolamento

`postgres-exporter` non espone PostgreSQL all'esterno.

Il componente:

- non sostituisce il database;
- non modifica dati applicativi;
- non espone query SQL agli utenti;
- non è raggiungibile dal browser.

La comunicazione avviene esclusivamente attraverso la rete Docker interna.

## Endpoint

L'endpoint delle metriche è:

```text
http://postgres-exporter:9187/metrics
```

Non viene esposta una porta pubblica dedicata sul computer locale.

L'accesso è limitato ai servizi interni autorizzati, principalmente Prometheus.

## Configurazione

La configurazione principale è contenuta nel file:

```text
postgres_exporter.yml
```

Il file definisce i parametri necessari al funzionamento del servizio.

Nell'ambiente production la connessione al database utilizza secret obbligatori definiti tramite variabili ambiente.

Questo evita di mantenere credenziali operative all'interno del repository.

## Utilizzo negli esperimenti di osservabilità

Il monitoraggio PostgreSQL è importante per valutare il comportamento complessivo della piattaforma.

Durante gli esperimenti permette di verificare:

- eventuali colli di bottiglia del database;
- variazioni del carico durante le scansioni;
- impatto delle richieste generate dal frontend;
- stato del database durante prove di fault.

Le metriche del database vengono analizzate insieme a quelle degli altri componenti per ottenere una visione completa del sistema distribuito.

## Differenza tra metriche applicative e database

Le metriche applicative descrivono il comportamento dei servizi SecureScan:

- richieste API;
- job elaborati;
- scansioni completate;
- errori.

Le metriche PostgreSQL descrivono invece lo stato interno del database:

- connessioni;
- attività;
- utilizzo;
- statistiche operative.

L'integrazione di entrambe permette di correlare problemi applicativi e infrastrutturali.

## File principali

La directory contiene:

```text
postgres_exporter.yml
```

Configurazione del componente.

```text
README.md
```

Documentazione del servizio.

## Collegamenti documentazione

Per la raccolta e visualizzazione delle metriche:

[Prometheus](../prometheus/README.md)

[Grafana](../grafana/README.md)

Per la descrizione generale dell'osservabilità:

[Osservabilità](../../docs/observability.md)

Per l'architettura complessiva:

[Architettura](../../docs/architecture.md)